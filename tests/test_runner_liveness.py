#!/usr/bin/env python3
"""A busy runner keeps telling the api it is alive, measured without a browser or an api.

    ~/cloakbrowser-env/bin/python tests/test_runner_liveness.py

Traced 2026-09-29 from the third Gemini real gate: while a runner deleted a thread (55s on Gemini),
and while it finished a job the api had cancelled, it claimed and pinged nothing, so past the
served window the api refused the next turn with 503 and failed a queued job as no_worker.
Prints N/2 PASSED.
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
            self.calls.append((time.time(), path))
        for part, response in self.answers.items():
            if part in path:
                return response
        return Response(200)

    def pings(self, start, end):
        return [t for t, path in self.calls if path == PING and start <= t <= end]


class Pool:
    """Busy for a while in whatever it is asked to do."""

    def __init__(self, busy):
        self.busy = busy

    def delete_thread(self, provider, url):
        time.sleep(self.busy)
        return SimpleNamespace(success=True, error=None)

    def execute(self, provider, feature, payload, thread_url, phase_hook, should_stop):
        time.sleep(self.busy)
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
    record("a runner deleting a thread keeps saying it is alive, and stops when done",
           len(during) >= 3 and not after,
           "{} pings in the {:.1f}s deletion, {} after it".format(len(during), ended - started, len(after)))

    # The api answers the first heartbeat that the job is gone (cancelled); the driver goes on for
    # a while before it returns, as the Gemini one did.
    client = Client({"/heartbeat": Response(200, {"alive": False})})
    runner = runner_module.Runner(Pool(busy=2.0), "gemini")
    job = {"id": "job-1", "attempt": 1, "feature": "chat", "provider": "gemini", "payload": {},
           "thread_url": None, "lease_seconds": 0.6}
    runner._handle(client, job)
    ended = time.time()
    time.sleep(0.8)
    told = next((t for t, path in client.calls if path.endswith("/heartbeat")), None)
    during = client.pings(told, ended) if told else []
    after = client.pings(ended + 0.01, time.time())
    record("a runner finishing a cancelled job keeps saying it is alive, and stops when done",
           told is not None and len(during) >= 3 and not after,
           "told the job was gone {}, {} pings until the driver returned, {} after".format(
               told is not None, len(during), len(after)))

    passed = sum(1 for ok in results if ok)
    print("{}/{} PASSED".format(passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
