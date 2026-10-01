#!/usr/bin/env python3
"""The Grok memory guard on a stub page. No browser, no turn.

    ~/cloakbrowser-env/bin/python tests/test_grok_memory.py

Measured 2026-09-27 (docs/research/2026-09-25-grok-measurements.md): GET /rest/user-settings from
inside grok.com answers {"enableMemory": ..., ...}, and the switch is Settings, Data Controls,
"Personalize Grok with your conversation history". On a shared account it lets one user's turn be
remembered in another user's, so the driver must read it before every turn. Prints N/N PASSED.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from src.providers.base import JobCancelled, ProviderError  # noqa: E402
from src.providers.grok import SIGNED_OUT, GrokProvider  # noqa: E402

results = []


def record(name, ok, detail):
    results.append(ok)
    print("[{}] {}  {}".format("PASS" if ok else "FAIL", name, detail), flush=True)


class Sent(Exception):
    """Raised by the stub send, so a turn stops the moment it would have gone out."""


class StubPage:
    """Answers the driver's in-page fetch of /rest/user-settings from `settings`: a (status, body)
    pair, or an exception the fetch raises."""

    def __init__(self, settings):
        self.settings = settings
        self.url = "https://grok.com/"
        self.asked = []

    def evaluate(self, script, arg=None):
        path = arg[0] if isinstance(arg, (list, tuple)) else arg
        # (path, method, body): the read must stay a read, never a write to the shared account.
        self.asked.append(tuple(arg) if isinstance(arg, (list, tuple)) else (arg, None, None))
        if path == "/rest/user-settings":
            if isinstance(self.settings, Exception):
                raise self.settings
            status, body = self.settings
            return {"status": status, "body": body}
        return {"status": 404, "body": ""}


class AccountPage(StubPage):
    """Also answers the account read with `account`, and gets its thread's address only after
    `lands_after` waits, as a new chat does a few seconds after its first message."""

    def __init__(self, settings, account=200, lands_after=None):
        super().__init__(settings)
        self.account = account
        self.lands_after = lands_after
        self.waits = 0

    def goto(self, *args, **kwargs):
        return None

    def wait_for_timeout(self, ms):
        self.waits += 1
        if self.lands_after is not None and self.waits >= self.lands_after:
            self.url = "https://grok.com/c/0f3a9c1e-1b2d-4c3e-8f4a-5b6c7d8e9f00"

    def evaluate(self, script, arg=None):
        path = arg[0] if isinstance(arg, (list, tuple)) else arg
        if isinstance(path, str) and path.startswith("/rest/app-chat/conversations"):
            self.asked.append(tuple(arg))
            return {"status": self.account, "body": ""}
        return super().evaluate(script, arg)


ON = (200, '{"enableMemory":true,"agentCustomizations":[],"allowGrokFinishedNotification":true,'
           '"mutedBotPushAgentIds":[]}')
OFF = (200, '{"enableMemory":false,"agentCustomizations":[],"allowGrokFinishedNotification":true,'
            '"mutedBotPushAgentIds":[]}')


def provider():
    return GrokProvider(Path("/tmp/grok-memory-test"), ROOT / "storage" / "sessions")


def turn_with(settings):
    """(what happened, prompts sent, provider): 'sent', 'refused: kind message', or 'crashed: ...'."""
    p, page, sent = provider(), StubPage(settings), []

    def send(_page, _composer, prompt):
        sent.append(prompt)
        raise Sent()

    p._open = lambda thread_url=None: (page, "composer")
    p._send = send
    try:
        p._run("hello")
        return "returned", sent, p
    except Sent:
        return "sent", sent, p
    except ProviderError as exc:
        return "refused: {} {}".format(exc.kind, exc), sent, p
    except Exception as exc:
        return "crashed: {}: {}".format(type(exc).__name__, str(exc)[:80]), sent, p


def main():
    reader = getattr(GrokProvider, "_read_memory", None)
    readings = (
        ("memory on reads on", ON, "on"),
        ("memory off reads off", OFF, "off"),
        ("a missing key reads unknown", (200, '{"allowGrokFinishedNotification":true}'), "unknown"),
        ("a value that is not true or false reads unknown", (200, '{"enableMemory":"yes"}'), "unknown"),
        ("a failed read reads unknown", (500, ""), "unknown"),
        ("a body that is not json reads unknown", (200, "<html>just a moment</html>"), "unknown"),
        ("json that is not an object reads unknown", (200, "[]"), "unknown"),
        ("a fetch that throws reads unknown", RuntimeError("Execution context was destroyed"), "unknown"),
    )
    for name, settings, expected in readings:
        if reader is None:
            record(name, False, "no memory read in the driver")
            continue
        p = provider()
        try:
            got = reader(p, StubPage(settings))
        except Exception as exc:
            got = "crashed: {}".format(type(exc).__name__)
        record(name, got == expected and p.memory == expected,
               "read {!r}, memory {!r}, expected {!r}".format(got, getattr(p, "memory", None), expected))

    what, sent, p = turn_with(ON)
    record("a turn with memory on is refused before anything is sent",
           what.startswith("refused: provider_misconfigured") and sent == [],
           "{} sent {}".format(what[:90], sent))
    record("the refusal names Grok's own switch",
           "Data Controls" in what and "Personalize Grok" in what, repr(what[:200]))
    record("health shows memory on after the refused turn",
           getattr(p, "memory", None) == "on", repr(getattr(p, "memory", None)))

    what, sent, p = turn_with(OFF)
    record("a turn with memory off goes out once",
           what == "sent" and sent == ["hello"] and getattr(p, "memory", None) == "off",
           "{} sent {} memory {!r}".format(what[:90], sent, getattr(p, "memory", None)))

    what, sent, p = turn_with((500, ""))
    record("a turn whose reading failed is not blocked (unknown does not block)",
           what == "sent" and sent == ["hello"] and getattr(p, "memory", None) == "unknown",
           "{} sent {} memory {!r}".format(what[:90], sent, getattr(p, "memory", None)))

    what, sent, p = turn_with((200, "[]"))
    record("a turn whose settings are not an object is not blocked and does not crash",
           what == "sent" and sent == ["hello"], "{} sent {}".format(what[:90], sent))

    # The review of 7555b93: one provider serves many turns, so the switch is read again before
    # each one, and a failed read never keeps the previous turn's answer (its mutants M5 and M6).
    p, pages, sent, seen = provider(), [], [], []
    for settings in (OFF, ON, OFF, (500, "")):
        pages.append(StubPage(settings))
    queue = list(pages)

    def send(_page, _composer, prompt):
        sent.append(prompt)
        raise Sent()

    p._open = lambda thread_url=None: (queue.pop(0), "composer")
    p._send = send
    for prompt in ("one", "two", "three", "four"):
        try:
            p._run(prompt)
        except (Sent, ProviderError):
            pass
        seen.append(getattr(p, "memory", None))
    record("the switch is read again before every turn of one provider",
           sent == ["one", "three", "four"], "sent {}".format(sent))
    record("each turn's reading is its own, never the previous one's",
           seen == ["off", "on", "off", "unknown"], "readings {}".format(seen))

    # The review's mutant M9: a read turned into a POST would write the shared account's setting.
    reads = [ask for page in pages for ask in page.asked if ask[0] == "/rest/user-settings"]
    record("the read is a GET with no body, never a write",
           len(reads) == 4 and all(ask[1] == "GET" and ask[2] is None for ask in reads),
           "requests {}".format(reads))

    # Signed out is what holds a provider out for ten minutes and tells its admin to log in again
    # (since 2026-10-01), so only the server refusing the account may read as that; a throttle or a
    # server error is the provider being unwell for a moment.
    def account_read(status):
        try:
            return "in" if provider()._signed_in(AccountPage(OFF, account=status)) else "out"
        except ProviderError as exc:
            return "error {}".format(exc.kind)
        except Exception as exc:
            return "crashed {}".format(type(exc).__name__)

    reads = {status: account_read(status) for status in (200, 401, 403, 429, 500, 503)}
    record("only the server refusing the account reads as signed out",
           reads == {200: "in", 401: "out", 403: "out", 429: "error provider_error",
                     500: "error provider_error", 503: "error provider_error"}, repr(reads))

    def open_with(status):
        p, page = provider(), AccountPage(OFF, account=status)
        p._ensure_page = lambda: page
        p._wait_for_challenge = lambda _page: True
        p._dismiss_overlays = lambda _page: None
        p._composer = lambda _page, seconds=30: "composer"
        try:
            p._open(None)
            return "opened"
        except ProviderError as exc:
            return "{}: {}".format(exc.kind, exc)
        except Exception as exc:
            return "crashed {}: {}".format(type(exc).__name__, str(exc)[:60])

    throttled, refused = open_with(429), open_with(401)
    record("a throttled account read fails the open as a provider error, a refused one as signed out",
           throttled.startswith("provider_error") and "signed out" not in throttled
           and refused == "provider_misconfigured: {}".format(SIGNED_OUT) and open_with(200) == "opened",
           "429 {!r}; 401 {!r}".format(throttled[:80], refused[:80]))

    # A stop now reaches the driver within seconds of the send (it used to take up to 140s), when a
    # new chat has no address yet: it has to be waited for, or the thread is lost to the account.
    p, page, sent = provider(), AccountPage(OFF, lands_after=4), []
    p._open = lambda thread_url=None: (page, "composer")
    p._send = lambda _page, _composer, prompt: sent.append(prompt)
    p.bind(None, lambda: bool(sent))
    try:
        p._run("hello")
        what = "returned"
    except JobCancelled:
        what = "cancelled"
    except Exception as exc:
        what = "crashed {}: {}".format(type(exc).__name__, str(exc)[:60])
    record("a turn stopped right after its send still reports the thread it landed in",
           what == "cancelled" and sent == ["hello"]
           and p.last_cancelled_thread == "https://grok.com/c/0f3a9c1e-1b2d-4c3e-8f4a-5b6c7d8e9f00",
           "{}, sent {}, thread {!r} after {} waits".format(what, sent, p.last_cancelled_thread, page.waits))

    passed = sum(1 for ok in results if ok)
    print("{}/{} PASSED".format(passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
