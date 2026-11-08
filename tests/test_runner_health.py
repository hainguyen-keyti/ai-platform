#!/usr/bin/env python3
"""A runner that has ended must still answer what /health asks of it. No browser, no api.

    ~/cloakbrowser-env/bin/python tests/test_runner_health.py

Reproduced 2026-09-28 on the worker's python (3.10): the runner kept its stop Event in `_stop`,
which hides the method threading.Thread calls once the thread is done, so an ended runner raised
TypeError from is_alive(), snapshot() and join(), and /health, which snapshots every runner, went
down with it. Prints N/N PASSED.
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from src import runner as runner_module  # noqa: E402

results = []


def record(name, ok, detail):
    results.append(ok)
    print("[{}] {}  {}".format("PASS" if ok else "FAIL", name, detail), flush=True)


def answer(call):
    try:
        return call()
    except Exception as exc:
        return "{}: {}".format(type(exc).__name__, exc)


class Response:
    status_code = 204

    def raise_for_status(self):
        return None

    def json(self):
        return {}


class Client:
    """Stands in for httpx.Client: there is never any work to give."""

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, path, json=None):
        return Response()


class Pool:
    """What an idle runner's loop asks of its pool. Measured 2026-11-07: without stands_aside the
    runner thread died at its first look, and the running-runner check failed on that, not on stop."""

    def hold_seconds(self, provider=None):
        return 0

    def cooling_down(self, provider):
        return False

    def stands_aside(self, account):
        return False

    def close_idle(self, account):
        return None

    def can_clean_library(self, account):
        return False

    def pacing_report(self, account):
        return {}


def main():
    runner_module.httpx.Client = Client

    ended = runner_module.Runner(Pool(), "chatgpt")
    ended.run = lambda: None
    ended.start()
    time.sleep(0.5)
    alive = answer(ended.is_alive)
    record("an ended runner says it is not alive", alive is False, repr(alive))
    snapshot = answer(ended.snapshot)
    record("an ended runner's snapshot, what /health reads, says alive false",
           isinstance(snapshot, dict) and snapshot.get("alive") is False, repr(snapshot)[:120])
    joined = answer(lambda: ended.join(1))
    record("an ended runner can be joined", joined is None, repr(joined))

    running = runner_module.Runner(Pool(), "grok")
    running.start()
    time.sleep(0.5)
    before = answer(running.is_alive)
    running.stop()
    joined = answer(lambda: running.join(3))
    after = answer(running.is_alive)
    record("a running runner told to stop leaves its loop",
           before is True and joined is None and after is False,
           "alive before {!r}, join {!r}, alive after {!r}".format(before, joined, after))

    passed = sum(1 for ok in results if ok)
    print("{}/{} PASSED".format(passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
