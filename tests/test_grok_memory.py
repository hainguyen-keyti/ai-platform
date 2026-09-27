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

from src.providers.base import ProviderError  # noqa: E402
from src.providers.grok import GrokProvider  # noqa: E402

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

    passed = sum(1 for ok in results if ok)
    print("{}/{} PASSED".format(passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
