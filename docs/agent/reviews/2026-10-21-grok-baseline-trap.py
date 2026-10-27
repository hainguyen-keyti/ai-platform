"""A Grok follow-up turn whose read of the thread before the send answers 429 once:
does the driver return the EARLIER turn's answer as this turn's? Stub page, no site."""
import json, sys, time
from pathlib import Path
sys.path.insert(0, "/Users/keyti/Sources/RE/chatgpt/worker")
from src.providers import grok
from src.providers.grok import GrokProvider

class Clock:
    now = 1000.0
    def time(self): return self.now
    def sleep(self, s): self.now += s
clock = Clock()
grok.time = clock

EARLIER = {"responseId": "a0", "sender": "assistant", "message": "The capital of France is Paris.", "partial": False}
HUMAN0 = {"responseId": "h0", "sender": "human", "message": "capital of France?", "partial": False}

class Page:
    url = "https://grok.com/c/0f3a9c1e-1b2d-4c3e-8f4a-5b6c7d8e9f00"
    def __init__(self, first_status):
        self.reads, self.first_status, self.sent = 0, first_status, []
    def wait_for_timeout(self, ms): clock.now += ms / 1000.0
    def evaluate(self, script, arg=None):
        path = arg[0] if isinstance(arg, (list, tuple)) else arg
        if path == "/rest/user-settings":
            return {"status": 200, "body": json.dumps({"enableMemory": False})}
        if "/responses" in path:
            self.reads += 1
            if self.reads == 1 and self.first_status != 200:
                return {"status": self.first_status, "body": ""}
            # The thread as it is: the earlier turn only; this turn's row has not been created yet.
            return {"status": 200, "body": json.dumps({"responses": [HUMAN0, EARLIER]})}
        if "/response-node" in path:
            return {"status": 200, "body": json.dumps({"inflightResponses": []})}
        return {"status": 404, "body": ""}

for status in (200, 429, 500):
    page = Page(status)
    p = GrokProvider(Path("/tmp/rv_worker/media"), Path("/tmp/rv_worker/sessions"))
    p._open = lambda thread_url=None, page=page: (page, "composer")
    p._send = lambda _p, _c, prompt, page=page: page.sent.append(prompt)
    started = clock.now
    try:
        got = p._run("What is the capital of Germany?", thread_url=page.url)
        said = "success={} text={!r} kind={}".format(got.success, got.text, got.error_kind)
    except Exception as exc:
        said = "{}: {}".format(type(exc).__name__, str(exc)[:80])
    print("baseline read answers {}: {} after {:.0f}s, sent {}".format(status, said, clock.now - started, len(page.sent)))
