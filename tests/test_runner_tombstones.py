#!/usr/bin/env python3
"""When a runner asks for a thread to delete, measured without a browser or an api.

    ~/cloakbrowser-env/bin/python tests/test_runner_tombstones.py

Measured 2026-09-26: a real grok run holds 150s between turns, and the runner
skipped tombstones for the whole hold, so a deleted conversation's thread waited
out every pacing gap and was never removed while the provider cooled down. A
thread deletion is one call, not a turn: pacing must not starve it. An error
cooldown still must, because the site is unwell then and each miss burns one of
three attempts. Prints N/3 PASSED.
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from src import runner as runner_module  # noqa: E402


class Response:
    def __init__(self, status):
        self.status_code = status

    def raise_for_status(self):
        return None

    def json(self):
        return {}


class Client:
    """Stands in for httpx.Client: records every path, has no work to give."""

    paths = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, path, json=None):
        Client.paths.append(path)
        return Response(204)


class Pool:
    def __init__(self, hold, cooling):
        self.hold = hold
        self.cooling = cooling

    def close_idle(self, account):
        pass

    def hold_seconds(self, provider=None):
        return self.hold

    def cooling_down(self, provider):
        return self.cooling

    def can_clean_library(self, provider):
        return False

    def pacing_report(self, provider):
        return {}


def asked_for_tombstone(hold, cooling):
    Client.paths = []
    runner_module.httpx.Client = Client
    runner = runner_module.Runner(Pool(hold, cooling), "grok")
    runner.start()
    time.sleep(0.5)
    seen = list(Client.paths)
    # stop() wakes the runner's wait at once; the short sleep lets it leave
    # before the next case resets Client.paths.
    runner.stop()
    time.sleep(0.3)
    return "/internal/tombstones/claim" in seen, seen


results = []


def record(name, ok, detail):
    results.append(ok)
    print("[{}] {}  {}".format("PASS" if ok else "FAIL", name, detail), flush=True)


def main():
    asked, paths = asked_for_tombstone(hold=150.0, cooling=False)
    record("a pacing gap does not starve a thread deletion", asked,
           "holding 150s between turns, requests {}".format(paths))

    asked, paths = asked_for_tombstone(hold=600.0, cooling=True)
    record("an error cooldown leaves the site alone", not asked,
           "cooling down after errors, requests {}".format(paths))

    asked, paths = asked_for_tombstone(hold=0.0, cooling=False)
    record("an idle runner still asks", asked, "idle, requests {}".format(paths))

    passed = sum(1 for ok in results if ok)
    print("{}/{} PASSED".format(passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
