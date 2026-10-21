#!/usr/bin/env python3
"""A browser that died under a turn: the pool must answer it as a provider error, so the
provider's cooldown counts and the next turn opens the profile again, instead of a worker error
that neither cools down nor drops the dead page (the review of 2026-10-21: every job then failed
within a second of the last, refunded, health still ready, until a restart by hand).

    ~/cloakbrowser-env/bin/python tests/test_pool_dead_browser.py

Prints N/N PASSED. No account, no browser: a fake provider raises what Playwright raises.
"""

import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from playwright._impl._errors import Error as PlaywrightError, TargetClosedError  # noqa: E402

from src.pool import BrowserPool  # noqa: E402
from src.providers.base import FeatureType, GenerationResult  # noqa: E402

results = []


def record(name, ok, detail):
    results.append(ok)
    print("[{}] {}  {}".format("PASS" if ok else "FAIL", name, detail), flush=True)


class Fake:
    """A provider whose turn raises what it is told to, and that counts its stops."""

    name = "chatgpt"
    supported_features = {FeatureType.CHAT}

    def __init__(self, raises=None):
        self.raises = raises
        self.stops = 0
        self.turns = 0

    def supports(self, feature):
        return feature == "chat"

    def bind(self, phase_hook=None, stop_hook=None):
        return None

    def chat(self, message, history=None, thread_url=None):
        self.turns += 1
        if self.raises is not None:
            raise self.raises
        return GenerationResult(success=True, text="pong", thread_url="https://chatgpt.com/c/1")

    def stop(self):
        self.stops += 1


def pool_with(fake):
    pool = BrowserPool()
    pool._providers["chatgpt"] = fake
    pool._locks["chatgpt"] = threading.Lock()
    return pool


def turn(fake):
    pool = pool_with(fake)
    result = pool.execute("chatgpt", "chat", {"message": "ping"})
    pool.note_result("chatgpt", result, 1.0)
    return pool, result


def main():
    pool, result = turn(Fake(TargetClosedError()))
    record("a closed target is a provider error: the provider is stopped and cools down",
           not result.success and result.error_kind == "provider_error" and pool.cooling_down("chatgpt")
           and pool._providers["chatgpt"].stops == 1 and "closed" in (result.error or ""),
           "kind {} cooling {} stops {} error {!r}".format(
               result.error_kind, pool.cooling_down("chatgpt"), pool._providers["chatgpt"].stops,
               (result.error or "")[:70]))

    pool, result = turn(Fake(PlaywrightError("Browser has been closed")))
    record("a plain Playwright error saying the browser is closed is read the same way",
           not result.success and result.error_kind == "provider_error" and pool.cooling_down("chatgpt")
           and pool._providers["chatgpt"].stops == 1,
           "kind {} cooling {} stops {}".format(result.error_kind, pool.cooling_down("chatgpt"),
                                                  pool._providers["chatgpt"].stops))

    pool, result = turn(Fake(RuntimeError("a driver bug")))
    record("any other exception stays a worker error, the provider left as it is",
           not result.success and result.error_kind == "worker_error" and not pool.cooling_down("chatgpt")
           and pool._providers["chatgpt"].stops == 0,
           "kind {} cooling {} stops {}".format(result.error_kind, pool.cooling_down("chatgpt"),
                                                  pool._providers["chatgpt"].stops))

    pool, result = turn(Fake())
    record("a turn that works is untouched",
           result.success and result.text == "pong" and pool._providers["chatgpt"].stops == 0
           and not pool.cooling_down("chatgpt"),
           "success {} stops {}".format(result.success, pool._providers["chatgpt"].stops))

    passed = sum(results)
    print("{}/{} PASSED".format(passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
