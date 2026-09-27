#!/usr/bin/env python3
"""The Gemini driver against a fake page and measured fixtures. No browser, no turn.

    ~/cloakbrowser-env/bin/python tests/test_gemini_driver.py

Measured 2026-09-25 and 2026-09-27 (docs/research/2026-09-27-gemini.md): the composer is a Quill
editor; a generated picture arrives from lh3.googleusercontent.com/rd-gg-dl/ during the turn, while
a user's upload shows from a blob and, reopened, from /rd-gg/ (so a loose "/rd-gg" match would take
it); the personal context switch is read on /personalization-settings, and a signed-out session is
sent to /saved-info, which also shows switches that are not this one.
Prints N/26 PASSED.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

results = []


def record(name, ok, detail):
    results.append(ok)
    print("[{}] {}  {}".format("PASS" if ok else "FAIL", name, detail), flush=True)


def finish():
    passed = sum(1 for ok in results if ok)
    print("{}/{} PASSED".format(passed, len(results)))
    return 0 if passed == len(results) else 1


class Clock:
    def __init__(self):
        self.now = 1000.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Box:
    def __init__(self, page, present):
        self.page = page
        self.present = present

    def count(self):
        return 1 if self.present else 0

    @property
    def first(self):
        return self

    def is_visible(self):
        return self.present

    def click(self, *args, **kwargs):
        if not self.present:
            raise RuntimeError("no such element")

    def focus(self, *args, **kwargs):
        self.click()

    def inner_text(self, *args, **kwargs):
        return self.page.text if self.present else ""

    def get_attribute(self, name):
        return self.page.checked if name == "aria-checked" else None

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class Keyboard:
    def __init__(self, page):
        self.page = page

    def insert_text(self, text):
        # truncate: a composer that loses the end of a long paste.
        self.page.text += text[:self.page.truncate] if self.page.truncate else text

    def type(self, text, *args, **kwargs):
        for ch in text:
            if ch == "\n":
                self.press("Enter")
            else:
                self.page.text += ch

    def press(self, key, *args, **kwargs):
        if key == "Enter":
            if self.page.text.strip():
                self.page.sent.append(self.page.text)
                self.page.on_sent()
            self.page.text = ""
        elif key == "Backspace":
            self.page.text = ""


class BlocksForever(BaseException):
    """What Playwright's Response.finished() does on a stream that failed after its headers: it
    never returns (shown by the tier 1 review, 2026-09-27, against localhost). A BaseException,
    so a driver that catches Exception cannot swallow it and carry on as if nothing happened."""


class Request:
    def __init__(self, url, method="POST"):
        self.url = url
        self.method = method
        self.failure = None


class Response:
    """outcome: "finished" (the request completes), "failed" (it breaks after its headers), or
    None (it never ends)."""

    def __init__(self, url, status=200, body=b"", ctype="application/json", method="POST",
                 outcome="finished"):
        self.url = url
        self.status = status
        self._body = body
        self.headers = {"content-type": ctype}
        self.request = Request(url, method)
        self.outcome = outcome

    def finished(self):
        if self.outcome != "finished":
            raise BlocksForever()
        return None

    def body(self):
        return self._body


class Bubbles:
    def __init__(self, page):
        self.page = page

    def all_inner_texts(self):
        # A reopened thread paints its earlier turns a moment after the composer shows.
        late = self.page.late if (self.page.late_at is not None
                                  and self.page.clock.now >= self.page.late_at) else []
        return list(late) + list(self.page.bubbles)


class Expected:
    """page.expect_response(...) as a context manager: the wait happens when the block exits."""

    def __init__(self, page):
        self.page = page
        self.value = None

    def __enter__(self):
        return self

    def __exit__(self, kind, error, trace):
        if kind:
            return False
        if self.page.process_file is None:
            raise RuntimeError("Timeout 30000ms exceeded while waiting for event \"response\"")
        self.value = Response("https://gemini.google.com/_/BardChatUi/data/assistant.lamda."
                              "BardFrontendService/ProcessFile", status=self.page.process_file)
        return False


class Page:
    """A composer page, or a settings page that lands on `landed` with one switch.

    A turn sent from it makes the page emit `replies` (fake responses) to its listeners, move to
    `thread`, and paint `answer` as a new bubble.
    """

    def __init__(self, clock, composer=True, landed=None, checked=None):
        self.clock = clock
        self.composer = composer
        self.landed = landed
        self.checked = checked
        self.url = "https://gemini.google.com/app"
        self.text = ""
        self.sent = []
        self.truncate = None
        self.keyboard = Keyboard(self)
        self.listeners = {}
        self.replies = []
        self.bubbles = []
        self.late, self.late_at = [], None
        self.answer = ""
        self.thread = "https://gemini.google.com/app/0123456789abcdef"
        self.file_input = False
        self.process_file = 200

    def on(self, event, handler):
        self.listeners.setdefault(event, []).append(handler)

    def remove_listener(self, event, handler):
        if handler in self.listeners.get(event, []):
            self.listeners[event].remove(handler)

    def emit(self, event, arg):
        for handler in list(self.listeners.get(event, [])):
            handler(arg)

    def on_sent(self):
        self.url = self.thread
        if self.answer is not None:
            self.bubbles.append(self.answer)
        for response in self.replies:
            self.emit("response", response)
            if response.request.method == "POST" and "StreamGenerate" in response.url:
                if response.outcome == "finished":
                    self.emit("requestfinished", response.request)
                elif response.outcome == "failed":
                    response.request.failure = "net::ERR_CONTENT_LENGTH_MISMATCH"
                    self.emit("requestfailed", response.request)

    def expect_response(self, predicate, timeout=None):
        return Expected(self)

    def goto(self, url, *args, **kwargs):
        self.url = self.landed or url

    def wait_for_timeout(self, ms):
        self.clock.now += ms / 1000.0

    def locator(self, selector):
        if "message-content" in selector:
            return Bubbles(self)
        if 'input[type="file"]' in selector:
            return Box(self, self.file_input)
        if "switch" in selector:
            return Box(self, self.checked is not None)
        parts = [p.strip() for p in selector.split(",")]
        return Box(self, self.composer and any("ql-editor" in p or "contenteditable" in p
                                                for p in parts))

    def evaluate(self, *args, **kwargs):
        return None

    def close(self, *args, **kwargs):
        return None

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class Context:
    def __init__(self, settings_page):
        self.settings_page = settings_page

    def new_page(self):
        return self.settings_page


def main():
    try:
        from src.providers import gemini
        from src.providers.base import ProviderError
    except ImportError as exc:
        record("the driver exists", False, "no driver to test: {}".format(exc))
        return finish()

    clock = Clock()
    gemini.time = clock

    def provider_on(page, settings=None):
        p = gemini.GeminiProvider(Path("/tmp/gemini-driver-test"), ROOT / "storage" / "sessions")
        p._page = page
        p._ensure_page = lambda: page
        p._context = Context(settings)
        return p

    page = Page(clock)
    record("the Quill composer counts as ready", provider_on(page)._composer_ready(page, 5) is True, "")
    page = Page(clock, composer=False)
    record("no composer is not ready", provider_on(page)._composer_ready(page, 5) is False, "")

    prompt = "user: first line\n\nassistant: second line\n\nReply to this next message only:\nthird"

    def send_on(page):
        try:
            provider_on(page)._send(page, prompt)
            return ""
        except Exception as exc:
            return "{}: {}".format(type(exc).__name__, str(exc)[:60])

    page = Page(clock)
    err = send_on(page)
    record("a multi-line prompt leaves as exactly one turn", page.sent == [prompt],
           "sent {} {}".format([len(s) for s in page.sent], err))

    page = Page(clock)
    page.text = prompt
    err = send_on(page)
    record("a prompt already in the composer is sent once, not twice", page.sent == [prompt],
           "sent {} {}".format([len(s) for s in page.sent], err))

    page = Page(clock)
    page.truncate = 60
    err = send_on(page)
    record("a prompt that lands cut short is not sent", page.sent == [] and bool(err),
           "sent {} {}".format(len(page.sent), err))

    cases = json.loads((ROOT / "tests" / "fixtures" / "gemini_image_responses.json").read_text())["cases"]
    wrong = []
    for case in cases:
        url = "{}://{}{}picture".format(case["scheme"], case["host"], case["prefix"]) \
            if case["scheme"] != "blob" else "blob:https://{}{}".format(case["host"], case["prefix"])
        got = gemini.is_generated_picture(url, case["type"], case["bytes"])
        if got != case["generated"]:
            wrong.append((case["situation"], got))
    record("only a picture generated in this turn is kept, never a user's", not wrong,
           "{} measured responses, wrong on {}".format(len(cases), wrong))
    record("a user's reopened upload under /rd-gg/ is not a generated picture",
           gemini.is_generated_picture("https://lh3.googleusercontent.com/rd-gg/abc", "image/png", 286) is False, "")

    settings = Page(clock, composer=False, landed="https://gemini.google.com/personalization-settings",
                    checked="false")
    p = provider_on(Page(clock), settings)
    got = p._read_personal_context()
    record("personal context off reads off", got == "off" and p.memory == "off",
           "read {!r}, health memory {!r}".format(got, p.memory))

    settings = Page(clock, composer=False, landed="https://gemini.google.com/personalization-settings",
                    checked="true")
    p = provider_on(Page(clock), settings)
    try:
        p._guard()
        outcome = "sent"
    except ProviderError as exc:
        outcome = exc.kind
    record("personal context on refuses the turn", outcome == "provider_misconfigured" and p.memory == "on",
           "outcome {!r}, health memory {!r}".format(outcome, p.memory))

    # Measured 2026-09-27: a signed-out session is sent to /saved-info, which shows switches of its
    # own. Reading one of those as the leak switch would be wrong, and sending would talk into an
    # anonymous Gemini: that is a signed-out session, refused.
    settings = Page(clock, composer=False, landed="https://gemini.google.com/saved-info", checked="false")
    p = provider_on(Page(clock), settings)
    try:
        p._guard()
        outcome, said = "sent", ""
    except ProviderError as exc:
        outcome, said = exc.kind, str(exc)
    record("a settings page bounced to /saved-info is a signed-out session, refused",
           outcome == "provider_misconfigured" and "signed out" in said,
           "outcome {!r} {!r}".format(outcome, said[:60]))

    # Anything else that stops the reading is unknown, and unknown does not block (DECISIONS).
    settings = Page(clock, composer=False, landed="https://gemini.google.com/personalization-settings",
                    checked=None)
    p = provider_on(Page(clock), settings)
    got = p._read_personal_context()
    try:
        p._guard()
        outcome = "sent"
    except ProviderError as exc:
        outcome = exc.kind
    record("a switch that never renders reads unknown and does not block",
           got == "unknown" and outcome == "sent", "read {!r}, outcome {!r}".format(got, outcome))

    # Whole turns, through _run, on the fake page.
    stream_ok = Response("https://gemini.google.com/_/BardChatUi/data/assistant.lamda."
                         "BardFrontendService/StreamGenerate?bl=x", status=200, body=b"streamed")
    off = lambda: Page(clock, composer=False,  # noqa: E731
                       landed="https://gemini.google.com/personalization-settings", checked="false")

    settings = Page(clock, composer=False, landed="https://gemini.google.com/personalization-settings",
                    checked="true")
    page = Page(clock)
    page.replies, page.answer = [stream_ok], "should never be asked"
    try:
        provider_on(page, settings)._run("hello")
        outcome = "ran"
    except ProviderError as exc:
        outcome = exc.kind
    record("a turn with personal context on is refused before anything is sent",
           outcome == "provider_misconfigured" and page.sent == [],
           "outcome {!r}, sent {}".format(outcome, len(page.sent)))

    page = Page(clock)
    page.replies = [Response(stream_ok.url, status=500)]
    try:
        result = provider_on(page, off())._run("hello")
        outcome = "returned success={}".format(result.success)
    except ProviderError as exc:
        outcome = "raised"
    record("a stream that answers 500 is a provider failure, never a reply", outcome == "raised",
           outcome)

    page = Page(clock)
    page.answer = ""
    page.replies = [
        Response("https://lh3.googleusercontent.com/rd-gg-dl/generated", body=b"G" * 12623,
                 ctype="image/jpeg", method="GET"),
        Response("https://lh3.googleusercontent.com/rd-gg/users-upload", body=b"U" * 286,
                 ctype="image/png", method="GET"),
        Response("https://lh3.googleusercontent.com/a/avatar", body=b"A" * 2120,
                 ctype="image/jpeg", method="GET"),
        stream_ok,
    ]
    result = provider_on(page, off())._run("Generate an image: a star")
    sizes = [m.metadata.get("size") for m in result.media]
    record("a picture turn keeps the generated picture and nothing else",
           result.success and sizes == [12623], "success {} sizes {}".format(result.success, sizes))

    page = Page(clock)
    page.answer, page.replies = "a plain reply", [stream_ok]
    result = provider_on(page, off())._run("hello")
    record("a text turn returns the new bubble and its thread",
           result.success and result.text == "a plain reply"
           and (result.thread_url or "").endswith("/app/0123456789abcdef"),
           "success {} text {!r} thread {}".format(result.success, result.text, result.thread_url))

    def run_on(page, settings, prompt="hello", **kwargs):
        """(what happened, result): 'blocked forever', 'refused: kind', 'crashed: ...', or 'returned'."""
        try:
            return "returned", provider_on(page, settings)._run(prompt, **kwargs)
        except BlocksForever:
            return "blocked forever", None
        except ProviderError as exc:
            return "refused: {} {}".format(exc.kind, str(exc)[:50]), None
        except Exception as exc:
            return "crashed: {}: {}".format(type(exc).__name__, str(exc)[:50]), None

    # The tier 1 review, 2026-09-27: a stream cut off after its 200 headers never finishes.
    page = Page(clock)
    page.answer = "half an answer"
    page.replies = [Response(stream_ok.url, status=200, outcome="failed")]
    what, result = run_on(page, off())
    record("a stream cut off after its headers is a failure, and nothing hangs",
           what.startswith("refused"), what)

    page = Page(clock)
    page.answer = "an answer that never finished"
    page.replies = [Response(stream_ok.url, status=200, outcome=None)]
    what, result = run_on(page, off())
    record("a stream that never ends times out instead of hanging",
           what == "returned" and not result.success and result.error_kind == "provider_timeout",
           "{} {}".format(what, result and result.error_kind))

    # The tier 1 review, 2026-09-27: a reopened thread paints its earlier turns late, so counting
    # them at once let an earlier answer pass for this turn's when the turn painted nothing.
    thread = "https://gemini.google.com/app/0123456789abcdef"
    page = Page(clock)
    page.late, page.late_at = ["an earlier question", "an earlier answer from yesterday"], clock.now + 3
    page.answer, page.replies = None, [stream_ok]
    what, result = run_on(page, off(), thread_url=thread)
    record("a turn that paints nothing new never returns an earlier answer",
           what != "returned" or (not result.success and "yesterday" not in (result.text or "")),
           "{} text {!r}".format(what, result and result.text))

    page = Page(clock)
    page.late, page.late_at = ["an earlier question", "an earlier answer"], clock.now
    page.answer, page.replies = "the new answer", [stream_ok]
    what, result = run_on(page, off(), thread_url=thread)
    record("a reopened thread returns this turn's answer",
           what == "returned" and result.success and result.text == "the new answer",
           "{} text {!r}".format(what, result and result.text))

    page = Page(clock)
    page.answer, page.replies = "should never be asked", [stream_ok]
    what, result = run_on(page, off(), thread_url=thread)
    record("a reopened thread whose earlier turns never paint is refused, not guessed",
           what.startswith("refused") and page.sent == [], "{} sent {}".format(what, len(page.sent)))

    # DECISIONS 2026-09-24: a stored thread that fails to open is a provider error, never a silent
    # fresh chat. Landing back on /app is what a deleted thread does, and a slow one too.
    page = Page(clock, landed="https://gemini.google.com/app")
    page.answer, page.replies = "an answer with no context", [stream_ok]
    what, result = run_on(page, off(), thread_url=thread)
    record("a thread that lands back on /app is refused, never a fresh chat",
           what.startswith("refused") and page.sent == [], "{} sent {}".format(what, len(page.sent)))

    # Signed out and sent to Google's sign-in page rather than /saved-info: still signed out.
    settings = Page(clock, composer=False, checked=None,
                    landed="https://accounts.google.com/v3/signin/identifier?continue=x")
    page = Page(clock)
    page.replies = [stream_ok]
    what, result = run_on(page, settings)
    record("a settings page bounced to Google sign-in is a signed-out session, refused",
           what.startswith("refused: provider_misconfigured") and page.sent == [],
           "{} sent {}".format(what, len(page.sent)))

    reference = Path("/tmp/gemini-driver-test/reference.png")
    reference.parent.mkdir(parents=True, exist_ok=True)
    reference.write_bytes(b"\x89PNG not really")
    for status, label in ((500, "an upload the server refused"), (None, "an upload that never answered")):
        page = Page(clock)
        page.file_input, page.process_file = True, status
        page.answer, page.replies = "please attach an image", [stream_ok]
        what, result = run_on(page, off(), prompt="describe it", upload=reference.name)
        record("{} stops the turn as a provider failure".format(label),
               what.startswith("refused") and page.sent == [], "{} sent {}".format(what, len(page.sent)))

    for url, expected in (("https://gemini.google.com/app/659ed82f23b56ced", "659ed82f23b56ced"),
                          ("https://gemini.google.com/app", None)):
        got = gemini.GeminiProvider._thread_id(type("AtUrl", (), {"url": url})())
        record("thread id of {}".format(url.rsplit("/", 1)[-1]), got == expected,
               "got {!r}, expected {!r}".format(got, expected))

    return finish()


if __name__ == "__main__":
    sys.exit(main())
