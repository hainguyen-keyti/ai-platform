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
import sys
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

    passed = sum(1 for ok in results if ok)
    print("{}/{} PASSED".format(passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
