import threading
import time

import httpx

from src.config import settings


class Runner(threading.Thread):
    """Pulls jobs from the API and posts results back.

    The worker holds no database handle: the API owns all state, which is what
    lets the worker sit outside Docker today and on another host later. While a
    job runs, a heartbeat keeps its lease alive and carries back the one thing
    the worker needs to know mid-flight: that the job is no longer its to finish.
    """

    def __init__(self, pool):
        super().__init__(name="job-runner", daemon=True)
        self.pool = pool
        self._stop = threading.Event()
        self.processed = 0
        self.failed = 0
        self.refused = 0
        self.last_error = None
        self.current_job = None

    def stop(self):
        self._stop.set()

    def run(self):
        headers = {"X-Worker-Token": settings.worker_token}
        with httpx.Client(base_url=settings.api_url, headers=headers, timeout=30.0) as client:
            while not self._stop.is_set():
                hold = self.pool.hold_seconds()
                if hold > 0:
                    self._stop.wait(min(hold, 5.0))
                    continue

                job = None
                try:
                    job = self._claim(client)
                except Exception as exc:
                    self.last_error = "claim failed, {}: {}".format(type(exc).__name__, exc)

                if job is None:
                    self._stop.wait(settings.poll_interval)
                    continue

                try:
                    self._handle(client, job)
                except Exception as exc:
                    self.last_error = "handle failed, {}: {}".format(type(exc).__name__, exc)
                    self.failed += 1
                finally:
                    self.current_job = None

    def _claim(self, client):
        response = client.post("/internal/jobs/claim")
        if response.status_code == 204:
            return None
        response.raise_for_status()
        return response.json()

    def _heartbeat(self, client, job_id, attempt, lease_seconds, lost, finished):
        interval = max(0.5, lease_seconds / 3.0)
        while not finished.wait(interval):
            try:
                response = client.post("/internal/jobs/{}/heartbeat".format(job_id),
                                       json={"attempt": attempt})
                if response.status_code == 200 and not response.json().get("alive", False):
                    lost.set()
                    return
            except Exception:
                # A missed beat is not a lost job; the lease is generous.
                continue

    def _handle(self, client, job):
        job_id, attempt = job["id"], job["attempt"]
        self.current_job = {"id": job_id, "attempt": attempt, "feature": job["feature"]}
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
                job["provider"], job["feature"], job.get("payload") or {},
                job.get("thread_url"), phase_hook, lost.is_set,
            )
        finally:
            finished.set()
            beat.join(timeout=5)
        self.pool.note_result(job["provider"], result, time.time() - started)

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
        response = client.post("/internal/jobs/{}/result".format(job_id), json=body)
        if response.status_code == 409:
            # Cancelled or reclaimed while we worked; the api already settled it.
            self.refused += 1
            self.last_error = "result refused: {}".format(response.json().get("detail"))
            return
        response.raise_for_status()
        if result.success:
            self.processed += 1
        else:
            self.failed += 1
            self.last_error = result.error
