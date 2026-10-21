#!/usr/bin/env python3
"""The Grok settle rule, against recorded shapes of what the server returns.

    ~/cloakbrowser-env/bin/python tests/test_grok_settle.py

Mock mode never loads the Grok driver, so nothing else in the suite can see this
rule break. The shapes below are the ones measured on 2026-09-24: a turn still
streaming, a turn finished with words, a turn finished with only a picture, and
a turn that finished carrying nothing at all, which is what a spent free tier
looks like from every endpoint. Prints N/N PASSED.
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from src.providers.grok import GrokProvider  # noqa: E402

results = []


def record(name, ok, detail):
    results.append(ok)
    print("[{}] {}  {}".format("PASS" if ok else "FAIL", name, detail), flush=True)


class StubPage:
    """Answers the two reads the settle rule makes, and nothing else."""

    def __init__(self, responses, inflight):
        self.payloads = {
            "responses": json.dumps({"responses": responses}),
            "response-node": json.dumps({"responseNodes": [], "inflightResponses": inflight}),
        }

    def evaluate(self, script, arg=None):
        path = arg[0] if isinstance(arg, (list, tuple)) else arg
        key = "responses" if "/responses" in path else "response-node"
        return {"status": 200, "body": self.payloads[key]}


def state_for(responses, inflight):
    provider = GrokProvider.__new__(GrokProvider)
    page = StubPage(responses, inflight)
    _, state, status = GrokProvider._server_turn(provider, page, "cid", set())
    return state, status


HUMAN = {"responseId": "h1", "sender": "human", "message": "ask", "partial": False}
STREAMING = {"responseId": "a1", "sender": "assistant", "message": "po", "partial": True}
WORDS = {"responseId": "a1", "sender": "assistant", "message": "pong", "partial": False}
PICTURE = {"responseId": "a1", "sender": "assistant", "partial": False,
           "message": '<grok:render card_id="x" card_type="generated_image_card"></grok:render>',
           "fileAttachmentsMetadata": [{"fileMetadataId": "asset-1", "fileMimeType": "image/jpeg"}]}
NOTHING = {"responseId": "a1", "sender": "assistant", "message": "", "partial": False}

CASES = (
    ("a streaming turn is still working", [HUMAN, STREAMING], [], "working"),
    ("a turn still inflight is still working", [HUMAN, WORDS], ["a1"], "working"),
    ("words finish a turn", [HUMAN, WORDS], [], "done"),
    ("a picture alone finishes a turn", [HUMAN, PICTURE], [], "done"),
    ("a finished turn carrying nothing is a refusal", [HUMAN, NOTHING], [], "empty"),
    ("no assistant turn yet is still working", [HUMAN], [], "working"),
)


# The read before the send (the safety plan, 2026-10-21): a follow-up whose thread cannot be read
# before the send must never return the earlier turn's answer. The reviewer's stub, rerun by the
# agent on 2026-10-21: a read answering 429 or 500 gave "Paris", the earlier answer, after 4s.
EARLIER_HUMAN = {"responseId": "h0", "sender": "human", "message": "capital of France?", "partial": False}
EARLIER = {"responseId": "a0", "sender": "assistant", "message": "The capital of France is Paris.",
           "partial": False}
THIS_HUMAN = {"responseId": "h1", "sender": "human", "message": "and Germany?", "partial": False}
THIS = {"responseId": "a1", "sender": "assistant", "message": "The capital of Germany is Berlin.",
        "partial": False}
THREAD = "https://grok.com/c/0f3a9c1e-1b2d-4c3e-8f4a-5b6c7d8e9f00"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FollowPage:
    """A thread with an answer already in it. Its reads before the send answer `before` in turn, the
    last one repeating, a 200 giving the thread as it is; after the send this turn's question is
    there at once and its answer `settled_after` seconds later, as on the real site, where an
    answer takes tens of seconds. A fresh page has no thread until the send."""

    def __init__(self, clock, before=(200,), settled_after=20.0, fresh=False):
        self.clock, self.before, self.settled_after, self.fresh = clock, list(before), settled_after, fresh
        self.url = "https://grok.com/" if fresh else THREAD
        self.sent, self.reads, self.sent_at = [], 0, None

    def wait_for_timeout(self, ms):
        self.clock.now += ms / 1000.0

    def evaluate(self, script, arg=None):
        path = arg[0] if isinstance(arg, (list, tuple)) else arg
        if path == "/rest/user-settings":
            return {"status": 200, "body": json.dumps({"enableMemory": False})}
        if "/responses" in path:
            earlier = [] if self.fresh else [EARLIER_HUMAN, EARLIER]
            if self.sent_at is None:
                self.reads += 1
                status = self.before[min(self.reads, len(self.before)) - 1]
                if status != 200:
                    return {"status": status, "body": ""}
                return {"status": 200, "body": json.dumps({"responses": earlier})}
            rows = earlier + [THIS_HUMAN]
            if self.clock.now - self.sent_at >= self.settled_after:
                rows.append(THIS)
            return {"status": 200, "body": json.dumps({"responses": rows})}
        if "/response-node" in path:
            return {"status": 200, "body": json.dumps({"responseNodes": [], "inflightResponses": []})}
        return {"status": 404, "body": ""}


def follow_up(clock, page, stop=None):
    """(what happened, the words, turns sent, seconds) of one turn on the stub page."""
    from src.providers import grok as grok_module
    from src.providers.base import JobCancelled, ProviderError
    grok_module.time = clock
    scratch = Path(tempfile.mkdtemp(prefix="grok-settle-"))
    provider = GrokProvider(scratch, scratch)
    provider._open = lambda thread_url=None: (page, "composer")

    def send(_page, _composer, prompt):
        page.sent.append(prompt)
        page.sent_at = clock.now
        page.url = THREAD
    provider._send = send
    provider.bind(None, stop)
    started = clock.now
    try:
        got = provider._run("and Germany?", thread_url=None if page.fresh else page.url)
        what, text = ("success" if got.success else "failed as {}".format(got.error_kind)), got.text or ""
    except JobCancelled:
        what, text = "cancelled", ""
    except ProviderError as exc:
        what, text = "refused as {}: {}".format(exc.kind, str(exc)[:60]), ""
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return what, text, len(page.sent), clock.now - started


def follow_up_cases():
    clock = Clock()
    what, text, sent, took = follow_up(clock, FollowPage(clock))
    record("a follow-up whose read before the send answers 200 returns this turn's words",
           what == "success" and text == THIS["message"] and sent == 1,
           "{} {!r} sent {} after {:.0f}s".format(what, text, sent, took))

    for status in (429, 500):
        what, text, sent, took = follow_up(clock, FollowPage(clock, before=(status, 200)))
        record("a follow-up whose read before the send first answers {} returns this turn's words, "
               "never the earlier answer".format(status),
               what == "success" and text == THIS["message"] and sent == 1,
               "{} {!r} sent {} after {:.0f}s".format(what, text, sent, took))

    what, text, sent, took = follow_up(clock, FollowPage(clock, before=(429,)))
    record("a thread that stays unreadable before the send refuses the turn soon, nothing sent",
           what.startswith("refused as provider_error") and sent == 0 and took < 40,
           "{} {!r} sent {} after {:.0f}s".format(what, text, sent, took))

    page = FollowPage(clock, before=(429,))
    what, text, sent, took = follow_up(clock, page, stop=lambda: page.reads >= 1)
    record("a job taken away while its thread is read again before the send stops there, nothing sent",
           what == "cancelled" and sent == 0,
           "{} {!r} sent {} reads {} after {:.0f}s".format(what, text, sent, page.reads, took))

    page = FollowPage(clock, fresh=True)
    what, text, sent, took = follow_up(clock, page)
    record("a new conversation sends without reading a thread",
           what == "success" and text == THIS["message"] and sent == 1 and page.reads == 0,
           "{} {!r} sent {} reads {} after {:.0f}s".format(what, text, sent, page.reads, took))


def main():
    for name, responses, inflight, expected in CASES:
        state, status = state_for(responses, inflight)
        record(name, state == expected, "state {!r}, expected {!r}".format(state, expected))

    # The baseline keeps an earlier turn from being read as this turn's answer.
    provider = GrokProvider.__new__(GrokProvider)
    page = StubPage([HUMAN, WORDS], [])
    _, state, _ = GrokProvider._server_turn(provider, page, "cid", {"a1"})
    record("an answer already there before the send does not count",
           state == "working", "state {!r}, expected 'working'".format(state))

    text, assets = GrokProvider._turn_content(PICTURE)
    record("a picture turn carries no words and one asset",
           text == "" and len(assets) == 1, "text {!r}, {} asset(s)".format(text, len(assets)))

    follow_up_cases()

    passed = sum(1 for ok in results if ok)
    print("{}/{} PASSED".format(passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
