#!/usr/bin/env python3
"""The Gemini driver against a fake page and measured fixtures. No browser, no turn.

    ~/cloakbrowser-env/bin/python tests/test_gemini_driver.py

Measured 2026-09-25 and 2026-09-27 (docs/research/2026-09-27-gemini.md): the composer is a Quill
editor; a generated picture arrives from lh3.googleusercontent.com/rd-gg-dl/ during the turn, while
a user's upload shows from a blob and, reopened, from /rd-gg/ (so a loose "/rd-gg" match would take
it); the personal context switch is read on /personalization-settings, and a signed-out session is
sent to /saved-info, which also shows switches that are not this one.
Prints N/43 PASSED.
"""

import json
import re
import sys
import unicodedata
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


class StillReading(BaseException):
    """A handler whose body() has not returned when the turn is read: the real dispatcher keeps
    that handler suspended in its greenlet while the rest of the page goes on (tier 1 re-review,
    2026-09-27, a picture landing 2s after the stream)."""


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
                 outcome="finished", fleeting=False, slow=False):
        self.url = url
        self.status = status
        self._body = body
        self.headers = {"content-type": ctype}
        self.request = Request(url, method)
        self.outcome = outcome
        # fleeting: the body can be read while the response is being delivered, not afterwards
        # (a picture turn on 2026-09-27 came back empty while one read at arrival never did).
        self.fleeting = fleeting
        self.slow = slow
        self.page = None

    def finished(self):
        if self.outcome != "finished":
            raise BlocksForever()
        return None

    def body(self):
        if self.slow:
            raise StillReading()
        if self.fleeting and not (self.page and self.page.dispatching):
            raise RuntimeError("No resource with given identifier found")
        return self._body


class Bubbles:
    """The page's `message-content, model-response` elements: two per answer, as measured."""

    def __init__(self, page):
        self.page = page

    def all_inner_texts(self):
        out = []
        for kind, text in self.page.items():
            if kind == "answer":
                out += ["Gemini đã nói " + text, text]
        return out


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

    The conversation is kept in document order, as measured on 2026-09-27: each turn is a
    `user-query` followed by a `model-response` holding a `message-content`. A turn sent from the
    page appends the query, paints `answer` after it (None paints nothing), emits `replies` (fake
    responses) to its listeners and moves to `thread`. `late` holds batches of earlier turns that
    paint above everything, each at its own time, the way a reopened thread paints its history.
    `schedule` makes a page walk through urls over time, like a redirect chain.
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
        self.dom = []
        self.late = []
        self.answer = ""
        self.thread = "https://gemini.google.com/app/0123456789abcdef"
        self.file_input = False
        self.process_file = 200
        self.dispatching = False
        self.schedule, self.went_at = [], None
        # How the page shows a sent question (it may normalise text or render a list without its
        # numbers), whether it shows it at all, which question elements were marked before the
        # send, and whether reading the answer finds the page gone.
        self.display = lambda text: text
        self.paint_query = True
        self.marked = []
        self.context_gone = False
        # A page that rebuilds its question elements when a turn is sent: the rebuilt ones are new
        # elements and carry no mark (the case the last re-review left open).
        self.rebuild_on_send = False

    def items(self):
        earlier = []
        for due, batch in sorted(self.late, key=lambda b: -b[0]):
            if self.clock.now >= due:
                earlier = list(batch) + earlier
        return earlier + list(self.dom)

    def on(self, event, handler):
        self.listeners.setdefault(event, []).append(handler)

    def remove_listener(self, event, handler):
        if handler in self.listeners.get(event, []):
            self.listeners[event].remove(handler)

    def emit(self, event, arg):
        if isinstance(arg, Response):
            arg.page = self
        self.dispatching = True
        try:
            for handler in list(self.listeners.get(event, [])):
                try:
                    handler(arg)
                except StillReading:
                    pass
        finally:
            self.dispatching = False

    def on_sent(self):
        self.url = self.thread
        if self.rebuild_on_send:
            # (kind, text) builds a new tuple; tuple(item) would hand back the same object.
            self.late = [(due, [(kind, text) for kind, text in batch]) for due, batch in self.late]
            self.dom = [(kind, text) for kind, text in self.dom]
        if self.paint_query:
            self.dom.append(("query", "Bạn đã nói " + self.display(self.sent[-1])))
        if self.answer is not None:
            self.dom.append(("answer", self.answer))
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
        if self.schedule:
            self.went_at = self.clock.now
            self.url = self.schedule[0][1]

    def wait_for_timeout(self, ms):
        self.clock.now += ms / 1000.0
        if self.schedule and self.went_at is not None:
            for after, url in self.schedule:
                if self.clock.now - self.went_at >= after:
                    self.url = url

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

    def evaluate(self, script, *args, **kwargs):
        # The driver's two page scripts, answered from the document order: marking the questions
        # already on the page, then reading the answer after the newest, unmarked question that
        # holds this turn's words. The scripts themselves run for real in markup_cases below.
        if "user-query" in script and "setAttribute" in script:
            # The marked elements themselves are kept, so a rebuilt one never shares their id.
            queries = [item for item in self.items() if item[0] == "query"]
            self.marked.extend(queries)
            return len(queries)
        if "user-query" in script:
            if self.context_gone:
                raise RuntimeError("Execution context was destroyed")
            # [words, the count at marking]; a bare list of words is how the driver asked before.
            arg = args[0] if args else []
            words, before = arg if len(arg) == 2 and isinstance(arg[1], int) else (arg, 0)
            items = self.items()
            queries = [i for i, item in enumerate(items) if item[0] == "query"]
            if len(queries) < before + 1 or any(items[queries[-1]] is m for m in self.marked):
                return {"query": False, "text": ""}
            shown = unicodedata.normalize("NFC", items[queries[-1]][1]).lower()
            if not all(word in shown for word in words):
                return {"query": False, "text": ""}
            answers = [text for kind, text in items[queries[-1] + 1:] if kind == "answer"]
            return {"query": True, "text": answers[-1].strip() if answers else ""}
        return None

    def close(self, *args, **kwargs):
        return None

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class Fetched:
    def __init__(self, status, body):
        self.status = status
        self.ok = status == 200
        self._body = body

    def body(self):
        return self._body


class Session:
    """context.request: fetches inside the session, from `served` (url -> bytes)."""

    def __init__(self):
        self.served = {}
        self.asked = []

    def get(self, url, *args, **kwargs):
        self.asked.append(url)
        if url in self.served:
            return Fetched(200, self.served[url])
        return Fetched(404, b"")


class Context:
    def __init__(self, settings_page):
        self.settings_page = settings_page
        self.request = Session()

    def new_page(self):
        return self.settings_page


def markup_cases(gemini):
    """ANSWER_AFTER_QUERY itself, run in a real browser on a thread captured from the site
    (tests/fixtures/gemini_thread.html: two turns, 'Remember this word ... teal-99016' answered
    'ok', then 'What word did I ask you to remember? ...' answered 'teal-99016'). The fake page
    above only imitates this script; these cases hold the script to the markup."""
    import cloakbrowser

    mark, words_of = getattr(gemini, "MARK_QUERIES", None), getattr(gemini, "query_words", None)
    if mark is None or words_of is None:
        record("the real markup: the driver marks the questions it did not send", False,
               "no MARK_QUERIES or query_words in the driver")
        return
    add_query = """(html) => {
        const q = document.createElement('user-query');
        q.innerHTML = html;
        document.querySelector('main').appendChild(q);
    }"""
    add_older_query = """(html) => {
        const q = document.createElement('user-query');
        q.innerHTML = html;
        const main = document.querySelector('main');
        main.insertBefore(q, main.firstChild);
    }"""
    rebuild_queries = """() => document.querySelectorAll('user-query').forEach((q) => {
        const fresh = q.cloneNode(true);
        fresh.removeAttribute('data-platform-before');
        q.replaceWith(fresh);
    })"""
    second = "What word did I ask you to remember? Reply with that word only."
    html = (ROOT / "tests" / "fixtures" / "gemini_thread.html").read_text()
    browser = cloakbrowser.launch(headless=True)
    try:
        page = browser.new_context().new_page()
        page.evaluate("(html) => { document.body.innerHTML = html; }", html)
        got = page.evaluate(gemini.ANSWER_AFTER_QUERY, [words_of(second), 1])
        record("the real markup: the answer after this turn's own question",
               got.get("query") is True and got.get("text", "").strip() == "teal-99016", repr(got))

        # The questions on the page before this turn's send are marked; if this turn's own never
        # paints, the newest is an old one with the very same words, and it must not be used.
        before = page.evaluate(mark)
        record("the real markup: marking counts the questions already there", before == 2,
               repr(before))
        got = page.evaluate(gemini.ANSWER_AFTER_QUERY, [words_of(second), before])
        record("the real markup: a question from before the send is never this turn's",
               got.get("query") is False and got.get("text") == "", repr(got))

        # An earlier turn painted above after the marking makes the count enough on its own; the
        # newest question is still a marked one.
        page.evaluate(add_older_query, "Bạn đã nói an even older question")
        got = page.evaluate(gemini.ANSWER_AFTER_QUERY, [words_of(second), before])
        record("the real markup: a marked newest question is refused even when the count is met",
               got.get("query") is False and got.get("text") == "", repr(got))

        # More than one new question since the marking (that older one, then this turn's): at
        # least one more is required, not exactly one.
        page.evaluate(add_query, "Bạn đã nói Tell me something new, please.")
        got = page.evaluate(gemini.ANSWER_AFTER_QUERY,
                            [words_of("Tell me something new, please."), before])
        record("the real markup: a question with no answer yet reads nothing, not the last answer",
               got.get("query") is True and got.get("text") == "", repr(got))

        page.evaluate(add_query, "Bạn đã nói <ol><li>first item</li><li>second item</li></ol>"
                                 "Reply with just: ok")
        got = page.evaluate(gemini.ANSWER_AFTER_QUERY,
                            [words_of("1. first item\n2. second item\nReply with just: ok"), before])
        record("the real markup: a list shown without its numbers is still found",
               got.get("query") is True, repr(got))

        page.evaluate(add_query, "Bạn đã nói " + unicodedata.normalize("NFC", "Viết một câu chào."))
        got = page.evaluate(gemini.ANSWER_AFTER_QUERY,
                            [words_of(unicodedata.normalize("NFD", "Viết một câu chào.")), before])
        record("the real markup: decomposed Vietnamese matches the page's composed text",
               got.get("query") is True, repr(got))

        page.evaluate(add_query, "Bạn đã nói " + unicodedata.normalize("NFD", "Chào buổi sáng nhé."))
        got = page.evaluate(gemini.ANSWER_AFTER_QUERY,
                            [words_of(unicodedata.normalize("NFC", "Chào buổi sáng nhé.")), before])
        record("the real markup: a page that shows decomposed text still matches",
               got.get("query") is True, repr(got))

        page.evaluate(add_query, "Bạn đã nói Something else entirely, from another turn.")
        got = page.evaluate(gemini.ANSWER_AFTER_QUERY,
                            [words_of("Tell me something new, please."), before])
        record("the real markup: an unmarked question without this turn's words is not used",
               got.get("query") is False, repr(got))

        # A page that rebuilds its question elements after the marking loses every mark; with this
        # turn's question missing, only the count still tells.
        page.evaluate("(html) => { document.body.innerHTML = html; }", html)
        before = page.evaluate(mark)
        page.evaluate(rebuild_queries)
        got = page.evaluate(gemini.ANSWER_AFTER_QUERY, [words_of(second), before])
        record("the real markup: rebuilt questions and no new one read nothing",
               got.get("query") is False and got.get("text") == "", repr(got))

        page.evaluate(add_query, "Bạn đã nói " + second)
        got = page.evaluate(gemini.ANSWER_AFTER_QUERY, [words_of(second), before])
        record("the real markup: rebuilt questions do not hide this turn's own",
               got.get("query") is True, repr(got))
    finally:
        browser.close()


def main():
    try:
        from src.providers import gemini
        from src.providers.base import ProviderError
    except ImportError as exc:
        record("the driver exists", False, "no driver to test: {}".format(exc))
        return finish()

    markup_cases(gemini)

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
    page.late = [(clock.now + 3, [("query", "an earlier question"),
                                  ("answer", "an earlier answer from yesterday")])]
    page.answer, page.replies = None, [stream_ok]
    what, result = run_on(page, off(), thread_url=thread)
    record("a turn that paints nothing new never returns an earlier answer",
           what != "returned" or (not result.success and "yesterday" not in (result.text or "")),
           "{} text {!r}".format(what, result and result.text))

    page = Page(clock)
    page.late = [(clock.now, [("query", "an earlier question"), ("answer", "an earlier answer")])]
    page.answer, page.replies = "the new answer", [stream_ok]
    what, result = run_on(page, off(), thread_url=thread)
    record("a reopened thread returns this turn's answer",
           what == "returned" and result.success and result.text == "the new answer",
           "{} text {!r}".format(what, result and result.text))

    # Tier 1 re-review, 2026-09-27: counting bubbles cannot tell old from new when the earlier
    # turns paint in two steps; only the answer after this turn's own question is this turn's.
    page = Page(clock)
    page.late = [(clock.now + 3, [("query", "a later earlier question"), ("answer", "its answer")]),
                 (clock.now + 9, [("query", "the first question"), ("answer", "yesterday's answer")])]
    page.answer, page.replies = None, [stream_ok]
    what, result = run_on(page, off(), thread_url=thread)
    record("earlier turns painting in two steps never pass for this turn's answer",
           what != "returned" or (not result.success and "answer" not in (result.text or "")),
           "{} text {!r}".format(what, result and result.text))

    # Tier 1 re-review: a picture whose body is still arriving when the turn is read must not be
    # dropped with its url, or the second fetch can never find it.
    page = Page(clock)
    page.answer = ""
    slow_url = "https://lh3.googleusercontent.com/rd-gg-dl/still-arriving"
    page.replies = [Response(slow_url, body=b"S" * 7000, ctype="image/jpeg", method="GET", slow=True),
                    stream_ok]
    p = provider_on(page, off())
    p._context.request.served[slow_url] = b"S" * 7000
    result = p._run("Generate an image: a square")
    sizes = [m.metadata.get("size") for m in result.media]
    record("a picture still arriving when the turn is read is fetched again, not lost",
           result.success and sizes == [7000], "success {} sizes {}".format(result.success, sizes))

    # Tier 1 re-review: a pass through Google's sign-in that comes back is not a signed-out session.
    settings = Page(clock, composer=False, checked="false")
    settings.schedule = [(0, "https://accounts.google.com/CheckCookie?continue=x"),
                         (2, "https://gemini.google.com/personalization-settings")]
    page = Page(clock)
    page.answer, page.replies = "a plain reply", [stream_ok]
    what, result = run_on(page, settings)
    record("a redirect through Google that comes back to the settings page is not signed out",
           what == "returned" and result.success, "{} {}".format(what, result and result.text))

    # Tier 1 re-review of 734fcc5: every video script job opens with the same words, so words alone
    # cannot say which question is this turn's. A question that never painted must not borrow the
    # answer of an identical earlier one.
    script_prompt = ("Write a Wan 2.2 video prompt of 5 seconds for the attached image. Describe "
                     "camera movement, character animation and ambient motion. Answer with a single "
                     "paragraph under 150 words and nothing else.")
    page = Page(clock)
    page.late = [(clock.now, [("query", "Bạn đã nói " + script_prompt),
                              ("answer", "an older video script")])]
    page.paint_query, page.answer, page.replies = False, None, [stream_ok]
    what, result = run_on(page, off(), prompt=script_prompt, thread_url=thread)
    record("a question that never painted never borrows an identical earlier one's answer",
           what != "returned" or (not result.success and "older" not in (result.text or "")),
           "{} text {!r}".format(what, result and result.text))

    # The last re-review: if the page rebuilds its question elements (so the marks are gone) and
    # this turn's question never paints, only the count of questions can still tell.
    page = Page(clock)
    page.late = [(clock.now, [("query", "Bạn đã nói " + script_prompt),
                              ("answer", "an older video script")])]
    page.rebuild_on_send = True
    page.paint_query, page.answer, page.replies = False, None, [stream_ok]
    what, result = run_on(page, off(), prompt=script_prompt, thread_url=thread)
    record("rebuilt question elements plus a missing question never borrow an older answer",
           what != "returned" or (not result.success and "older" not in (result.text or "")),
           "{} text {!r}".format(what, result and result.text))

    page = Page(clock)
    page.late = [(clock.now, [("query", "an earlier question"), ("answer", "an earlier answer")])]
    page.rebuild_on_send = True
    page.answer, page.replies = "the new answer", [stream_ok]
    what, result = run_on(page, off(), thread_url=thread)
    record("rebuilt question elements do not stop this turn's own answer",
           what == "returned" and result.success and result.text == "the new answer",
           "{} text {!r}".format(what, result and result.text))

    # Tier 1 re-review: the anchor failed closed on a decomposed Vietnamese prompt and on a list.
    decomposed = unicodedata.normalize("NFD", "Viết cho tôi một câu chào bằng tiếng Việt.")
    page = Page(clock)
    page.display = lambda text: unicodedata.normalize("NFC", text)
    page.answer, page.replies = "Xin chào!", [stream_ok]
    what, result = run_on(page, off(), prompt=decomposed)
    record("a question typed in decomposed Vietnamese is found once the page composes it",
           what == "returned" and result.success and result.text == "Xin chào!",
           "{} text {!r}".format(what, result and result.text))

    page = Page(clock)
    page.display = lambda text: re.sub(r"(?m)^\d+\.\s*", "", text)
    page.answer, page.replies = "ok", [stream_ok]
    what, result = run_on(page, off(), prompt="1. first item\n2. second item\nReply with just: ok")
    record("a numbered list shown without its numbers is still this turn's question",
           what == "returned" and result.success and result.text == "ok",
           "{} text {!r}".format(what, result and result.text))

    page = Page(clock)
    page.context_gone = True
    page.answer, page.replies = "an answer", [stream_ok]
    what, result = run_on(page, off())
    record("a page that goes away while the answer is read is a provider failure",
           what.startswith("refused: provider_error"), what)

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

    picture_url = "https://lh3.googleusercontent.com/rd-gg-dl/generated-now"
    page = Page(clock)
    page.answer = ""
    page.replies = [Response(picture_url, body=b"P" * 11909, ctype="image/jpeg", method="GET",
                             fleeting=True), stream_ok]
    p = provider_on(page, off())
    result = p._run("Generate an image: a hexagon")
    sizes = [m.metadata.get("size") for m in result.media]
    record("a picture whose body is readable only as it arrives is still kept",
           result.success and sizes == [11909], "success {} sizes {} seen {}".format(
               result.success, sizes, getattr(p, "last_pictures", None)))

    page = Page(clock)
    page.answer = ""
    page.replies = [Response(picture_url, body=b"", ctype="image/jpeg", method="GET"), stream_ok]
    p = provider_on(page, off())
    p._context.request.served[picture_url] = b"R" * 9000
    result = p._run("Generate an image: a hexagon")
    sizes = [m.metadata.get("size") for m in result.media]
    record("a picture that arrived without its bytes is fetched again inside the session",
           result.success and sizes == [9000], "success {} sizes {}".format(result.success, sizes))

    upload_url = "https://lh3.googleusercontent.com/rd-gg/users-upload"
    page = Page(clock)
    page.answer = "a reply about the picture"
    page.replies = [Response(upload_url, body=b"", ctype="image/png", method="GET"), stream_ok]
    p = provider_on(page, off())
    p._context.request.served[upload_url] = b"U" * 286
    result = p._run("describe it")
    record("only a generated picture is ever fetched again, never a user's",
           result.success and result.media == [] and upload_url not in p._context.request.asked,
           "media {} asked {}".format(len(result.media), p._context.request.asked))

    for url, expected in (("https://gemini.google.com/app/659ed82f23b56ced", "659ed82f23b56ced"),
                          ("https://gemini.google.com/app", None)):
        got = gemini.GeminiProvider._thread_id(type("AtUrl", (), {"url": url})())
        record("thread id of {}".format(url.rsplit("/", 1)[-1]), got == expected,
               "got {!r}, expected {!r}".format(got, expected))

    return finish()


if __name__ == "__main__":
    sys.exit(main())
