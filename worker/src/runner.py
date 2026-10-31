import threading
import time
from datetime import datetime, timezone

import httpx

from src.config import settings

# How often an idle worker asks whether a deleted conversation left a thread to
# remove from the provider's account. Rare work; no need to ask every poll.
TOMBSTONE_INTERVAL_SECONDS = 10.0
# How often a runner busy outside a live job (deleting a thread, finishing a cancelled one) says it
# is alive, as often as its pauses between turns do.
BUSY_PING_SECONDS = 5.0
# How long a runner in a job goes at most without asking whether the job is still its own, whatever the
# lease: a third of production's lease was 140s, and a Stop reached the driver after its turn had ended.
CANCEL_CHECK_SECONDS = 5.0
# How long to wait before each new try at handing the api a finished job's result, about a minute in all: the
# api restarts on every change to its code, and a result it never got means the turn is made again.
RESULT_RETRY_SECONDS = (2.0, 5.0, 10.0, 15.0, 30.0)


class Runner(threading.Thread):
    """Pulls one provider's jobs from the API and posts results back.

    The worker holds no database handle: the API owns all state, which is what
    lets the worker sit outside Docker today and on another host later. While a
    job runs, a heartbeat keeps its lease alive and carries back the one thing
    the worker needs to know mid-flight: that the job is no longer its to finish.

    One runner per account, because an account's browser belongs to the thread
    that created it: two stealth browsers cannot be launched from one thread, and
    an account paused by its own cooldown must not park anybody else.
    """

    def __init__(self, pool, provider, account=None):
        self.account = account or provider
        super().__init__(name="job-runner-{}".format(self.account), daemon=True)
        self.pool = pool
        self.provider = provider
        # Not _stop: threading.Thread calls its own _stop() once the thread has ended.
        self._halt = threading.Event()
        self.processed = 0
        self.failed = 0
        self.refused = 0
        self.last_error = None
        self.current_job = None
        self.threads_deleted = 0
        self.thread_deletions_failed = 0
        self._next_tombstone_check = 0.0
        # The nightly Library cleanup (#27): where the run stands, the last day it ran, what it did.
        self._cleaning = None
        self._cleaned_day = None
        self.library_cleanup = None

    def snapshot(self) -> dict:
        return {
            "thread": self.name,
            "alive": self.is_alive(),
            "current_job": self.current_job,
            "jobs_processed": self.processed,
            "jobs_failed": self.failed,
            "results_refused": self.refused,
            "threads_deleted": self.threads_deleted,
            "thread_deletions_failed": self.thread_deletions_failed,
            "library_cleanup": self.library_cleanup,
            "last_error": self.last_error,
        }

    def stop(self):
        self._halt.set()

    def run(self):
        headers = {"X-Worker-Token": settings.worker_token}
        with httpx.Client(base_url=settings.api_url, headers=headers, timeout=30.0) as client:
            while not self._halt.is_set():
                hold = self.pool.hold_seconds(self.account)
                if hold > 0:
                    # Pausing on purpose is not being dead: say so, or the api
                    # fails the jobs waiting for this provider as unserved.
                    try:
                        client.post("/internal/workers/ping", json=self._ping_body())
                    except Exception:
                        pass
                    # A thread deletion is one call, not a turn: a pacing gap
                    # must not starve it. An error cooldown still does.
                    if not self.pool.cooling_down(self.account):
                        self._maybe_delete_one_thread(client)
                    self.pool.close_idle(self.account)
                    self._halt.wait(min(hold, 5.0))
                    continue

                job = None
                try:
                    job = self._claim(client)
                except Exception as exc:
                    self.last_error = "claim failed, {}: {}".format(type(exc).__name__, exc)

                if job is None:
                    self._maybe_delete_one_thread(client)
                    self._maybe_clean_library(client)
                    self.pool.close_idle(self.account)
                    self._halt.wait(settings.poll_interval)
                    continue

                try:
                    self._handle(client, job)
                except Exception as exc:
                    self.last_error = "handle failed, {}: {}".format(type(exc).__name__, exc)
                    self.failed += 1
                finally:
                    self.current_job = None

    def _who(self):
        """Who this runner serves; the default account needs no name of its own."""
        return {"providers": [self.provider], **({"account": self.account} if self.account != self.provider else {})}

    def _ping_body(self):
        """Who this runner serves, and what it has spent of its picture budget."""
        pacing = self.pool.pacing_report(self.account)
        return {**self._who(), "pacing": pacing or None}

    def _claim(self, client):
        response = client.post("/internal/jobs/claim", json=self._ping_body())
        if response.status_code == 204:
            return None
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _utcnow():
        return datetime.now(timezone.utc)

    def _maybe_clean_library(self, client):
        """One page of the day's Library cleanup, when the runner has no job (issue #27): a person's
        request is served between pages. Only from LIBRARY_CLEANUP_AT, once a day; a failed page ends
        the day's run and says why."""
        if not settings.library_cleanup_at or not self.pool.can_clean_library(self.account):
            return
        now = self._utcnow()
        day = now.date().isoformat()
        if self._cleaning is None:
            if self._cleaned_day == day or now.strftime("%H:%M") < settings.library_cleanup_at:
                return
            self._cleaning = {"day": day, "cursor": None}
            self.library_cleanup = {"day": day, "running": True, "removed": 0, "bytes": 0, "not_ours": 0,
                                    "failed": 0, "error": None}
        report = self.library_cleanup
        try:
            page = self.pool.clean_library_page(self.account, self._cleaning["cursor"], self._cleaning["day"],
                                                lambda urls: self._known_threads(client, urls))
        except Exception as exc:
            report["error"] = "{}: {}".format(type(exc).__name__, exc)
            report["running"] = False
            self.last_error = "library cleanup failed, {}".format(report["error"])
            self._cleaned_day, self._cleaning = self._cleaning["day"], None
            return
        report["removed"] += page["removed"]
        report["bytes"] += page["bytes"]
        report["not_ours"] += page["not_ours"]
        report["failed"] += len(page["failed"])
        if page["cursor"]:
            self._cleaning["cursor"] = page["cursor"]
        else:
            report["running"] = False
            self._cleaned_day, self._cleaning = self._cleaning["day"], None

    def _known_threads(self, client, thread_urls):
        """Which of these thread addresses the platform stores: anything else on the account is not ours."""
        response = client.post("/internal/threads/known",
                               json={"provider": self.provider, "thread_urls": thread_urls})
        response.raise_for_status()
        return set(response.json()["known"])

    def _maybe_delete_one_thread(self, client):
        if time.time() < self._next_tombstone_check:
            return
        self._next_tombstone_check = time.time() + TOMBSTONE_INTERVAL_SECONDS
        try:
            self._delete_one_thread(client)
        except Exception as exc:
            self.last_error = "tombstone failed, {}: {}".format(type(exc).__name__, exc)

    def _delete_one_thread(self, client):
        response = client.post("/internal/tombstones/claim", json=self._who())
        if response.status_code != 200:
            return
        stone = response.json()
        # Measured 2026-09-29: a Gemini deletion drives the page for about a minute.
        done = threading.Event()
        pinger = threading.Thread(target=self._keep_alive, args=(client, done),
                                  name="alive-{}".format(self.provider), daemon=True)
        pinger.start()
        try:
            result = self.pool.delete_thread(self.account, stone["thread_url"])
        finally:
            done.set()
            pinger.join(timeout=5)
        client.post("/internal/tombstones/{}/result".format(stone["id"]),
                    json={"ok": result.success, "error": result.error})
        if result.success:
            self.threads_deleted += 1
        else:
            self.thread_deletions_failed += 1
            self.last_error = "thread deletion failed: {}".format(result.error)

    def _heartbeat(self, client, job_id, attempt, lease_seconds, lost, finished):
        interval = max(0.5, min(lease_seconds / 3.0, CANCEL_CHECK_SECONDS))
        while not finished.wait(interval):
            try:
                response = client.post("/internal/jobs/{}/heartbeat".format(job_id),
                                       json={"attempt": attempt})
                if response.status_code == 200 and not response.json().get("alive", False):
                    lost.set()
                    # The driver is still finishing the cancelled turn: busy, not dead.
                    self._keep_alive(client, finished)
                    return
            except Exception:
                # A missed beat is not a lost job; the lease is generous.
                continue

    def _keep_alive(self, client, done):
        """Ping for this provider until done is set, or the api counts the busy runner as gone."""
        while not done.wait(BUSY_PING_SECONDS):
            try:
                client.post("/internal/workers/ping", json=self._who())
            except Exception:
                pass

    def _post_result(self, client, job_id, body):
        """Hand the api a finished job's result: (its answer, whether a try before it went unanswered).

        Only an api that did not answer, or answered 5xx, is tried again; its last failure goes up.
        """
        path = "/internal/jobs/{}/result".format(job_id)
        retried = False
        for pause in RESULT_RETRY_SECONDS:
            try:
                response = client.post(path, json=body)
                if response.status_code < 500:
                    return response, retried
                self.last_error = "result not taken, status {}".format(response.status_code)
            except httpx.TransportError as exc:
                self.last_error = "result not taken, {}: {}".format(type(exc).__name__, exc)
            retried = True
            if self._halt.wait(pause):
                break
        return client.post(path, json=body), retried

    def _handle(self, client, job):
        if job.get("provider") != self.provider:
            # This runner owns one browser, on this thread. Driving another
            # provider's browser from here is the error the whole design exists
            # to prevent, so it is refused rather than attempted.
            self.last_error = "refused a {} job on the {} runner".format(
                job.get("provider"), self.provider)
            client.post("/internal/jobs/{}/result".format(job["id"]), json={
                "status": "failed", "attempt": job["attempt"], "text": "", "media": [],
                "error": self.last_error, "error_kind": "worker_error"})
            self.failed += 1
            return
        job_id, attempt = job["id"], job["attempt"]
        self.current_job = {"id": job_id, "attempt": attempt, "feature": job["feature"],
                            "provider": job["provider"]}
        lost = threading.Event()
        finished = threading.Event()
        beat = threading.Thread(
            target=self._heartbeat,
            args=(client, job_id, attempt, job.get("lease_seconds", 420), lost, finished),
            name="heartbeat-{}".format(job_id[:8]), daemon=True,
        )
        beat.start()

        def phase_hook(name):
            client.post("/internal/jobs/{}/progress".format(job_id),
                        json={"attempt": attempt, "phase": name})

        started = time.time()
        try:
            result = self.pool.execute(
                self.account, job["feature"], job.get("payload") or {},
                job.get("thread_url"), phase_hook, lost.is_set,
            )
        finally:
            finished.set()
            beat.join(timeout=5)
        self.pool.note_result(self.account, result, time.time() - started)

        body = {
            "status": "done" if result.success else "failed",
            "attempt": attempt,
            "text": result.text,
            "media": [
                {"filename": m.filename, "type": m.type, "metadata": m.metadata}
                for m in result.media
            ],
            "error": result.error,
            "error_kind": result.error_kind,
            "thread_url": result.thread_url,
        }
        response, retried = self._post_result(client, job_id, body)
        if response.status_code == 409:
            # Cancelled or reclaimed while we worked; the api already settled it,
            # so what this attempt saved has no row to belong to. Remove it. After a
            # retry the 409 may be the api refusing a result it took the first time,
            # its answer lost, so those files may be the job's own: they stay.
            if not retried:
                for item in result.media:
                    try:
                        (settings.media_path / item.filename).unlink(missing_ok=True)
                    except OSError:
                        pass
            self.refused += 1
            self.last_error = "result refused: {}".format(response.json().get("detail"))
            return
        response.raise_for_status()
        if result.success:
            self.processed += 1
        else:
            self.failed += 1
            self.last_error = result.error
