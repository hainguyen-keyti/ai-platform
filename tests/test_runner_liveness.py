#!/usr/bin/env python3
"""A busy runner keeps telling the api it is alive, measured without a browser or an api.

    ~/cloakbrowser-env/bin/python tests/test_runner_liveness.py

Traced 2026-09-29 from the third Gemini real gate: while a runner deleted a thread (55s on Gemini),
and while it finished a job the api had cancelled, it claimed and pinged nothing, so past the
served window the api refused the next turn with 503 and failed a queued job as no_worker.
Measured 2026-10-01 in the owner's acceptance walk: a turn stopped 2.5s after Send ran on at
ChatGPT, because the runner asked about its job only every lease/3, 140s with production's 420s.
Prints N/4 PASSED.
"""

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from src import runner as runner_module  # noqa: E402

PING = "/internal/workers/ping"
runner_module.BUSY_PING_SECONDS = 0.2
# The cadence the runner ships with is what the check below holds to 5s; the test itself runs faster.
SHIPPED_CANCEL_CHECK = getattr(runner_module, "CANCEL_CHECK_SECONDS", None)
runner_module.CANCEL_CHECK_SECONDS = 0.3


class Response:
    def __init__(self, status, body=None):
        self.status_code = status
        self.body = body or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


class Client:
    """Stands in for httpx.Client: records every path with the moment it was asked."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []
        self.lock = threading.Lock()

    def post(self, path, json=None):
        with self.lock:
            self.calls.append((time.time(), path, json))
        for part, response in self.answers.items():
            if part in path:
                return response
        return Response(200)

    def pings(self, start, end):
        return [t for t, path, _ in self.calls if path == PING and start <= t <= end]

    def ping_bodies(self):
        return [body for _, path, body in self.calls if path == PING]


class Pool:
    """Busy for a while in whatever it is asked to do; notes when it is first told to stop."""

    def __init__(self, busy, delete_raises=False):
        self.busy = busy
        self.delete_raises = delete_raises
        self.stop_seen = None

    def delete_thread(self, provider, url):
        time.sleep(self.busy)
        if self.delete_raises:
            raise RuntimeError("the page went away mid-deletion")
        return SimpleNamespace(success=True, error=None)

    def execute(self, provider, feature, payload, thread_url, phase_hook, should_stop):
        until = time.time() + self.busy
        while time.time() < until:
            if self.stop_seen is None and should_stop():
                self.stop_seen = time.time()
            time.sleep(0.05)
        return SimpleNamespace(success=False, text="", media=[], error="cancelled by the user",
                               error_kind="cancelled", thread_url=None)

    def note_result(self, provider, result, seconds):
        pass


results = []


def record(name, ok, detail):
    results.append(ok)
    print("[{}] {}  {}".format("PASS" if ok else "FAIL", name, detail), flush=True)


def main():
    stone = {"id": "stone-1", "provider": "gemini", "thread_url": "https://gemini.google.com/app/0123456789abcdef"}
    client = Client({"/internal/tombstones/claim": Response(200, stone)})
    runner = runner_module.Runner(Pool(busy=1.5), "gemini")
    started = time.time()
    runner._delete_one_thread(client)
    ended = time.time()
    time.sleep(0.8)
    during, after = client.pings(started, ended), client.pings(ended + 0.01, time.time())
    # A ping names its provider, or the api counts it for nobody.
    named = all(body == {"providers": ["gemini"]} for body in client.ping_bodies())
    record("a runner deleting a thread keeps saying it is alive, and stops when done",
           len(during) >= 3 and not after and named,
           "{} pings in the {:.1f}s deletion, {} after it, each naming gemini {}".format(
               len(during), ended - started, len(after), named))

    client = Client({"/internal/tombstones/claim": Response(200, stone)})
    runner = runner_module.Runner(Pool(busy=1.0, delete_raises=True), "gemini")
    started = time.time()
    try:
        runner._delete_one_thread(client)
    except RuntimeError:
        pass
    ended = time.time()
    time.sleep(0.8)
    during, after = client.pings(started, ended), client.pings(ended + 0.01, time.time())
    record("a deletion that raises still stops the pings", len(during) >= 2 and not after,
           "{} pings during, {} after".format(len(during), len(after)))

    # The api answers the first heartbeat that the job is gone (cancelled); the driver goes on for
    # a while before it returns, as the Gemini one did, and must still be told to stop at once.
    client = Client({"/heartbeat": Response(200, {"alive": False})})
    pool = Pool(busy=2.0)
    runner = runner_module.Runner(pool, "gemini")
    job = {"id": "job-1", "attempt": 1, "feature": "chat", "provider": "gemini", "payload": {},
           "thread_url": None, "lease_seconds": 0.6}
    runner._handle(client, job)
    ended = time.time()
    time.sleep(0.8)
    told = next((t for t, path, _ in client.calls if path.endswith("/heartbeat")), None)
    during = client.pings(told, ended) if told else []
    after = client.pings(ended + 0.01, time.time())
    stopped_in = round(pool.stop_seen - told, 2) if told and pool.stop_seen else None
    record("a runner finishing a cancelled job keeps saying it is alive, and stops when done",
           told is not None and len(during) >= 3 and not after
           and stopped_in is not None and stopped_in < 0.5,
           "told the job was gone {}, the driver told to stop {}s later, {} pings until it returned, "
           "{} after".format(told is not None, stopped_in, len(during), len(after)))

    # Production's lease: the api answers at once that the job is gone, and the driver, three seconds
    # into its turn, must hear it within the cancel cadence rather than at lease/3.
    client = Client({"/heartbeat": Response(200, {"alive": False})})
    pool = Pool(busy=3.0)
    runner = runner_module.Runner(pool, "chatgpt")
    job = {"id": "job-2", "attempt": 1, "feature": "chat", "provider": "chatgpt", "payload": {},
           "thread_url": None, "lease_seconds": 420}
    started = time.time()
    runner._handle(client, job)
    stopped_after = round(pool.stop_seen - started, 2) if pool.stop_seen else None
    record("a cancel reaches the driver within the cancel cadence whatever the lease",
           SHIPPED_CANCEL_CHECK is not None and SHIPPED_CANCEL_CHECK <= 5
           and stopped_after is not None and stopped_after < 1.5,
           "shipped cadence {}s; with a 420s lease the driver was told to stop {}s into a 3s turn".format(
               SHIPPED_CANCEL_CHECK, stopped_after))

    passed = sum(1 for ok in results if ok)
    print("{}/{} PASSED".format(passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
