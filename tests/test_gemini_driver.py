#!/usr/bin/env python3
"""The Gemini driver against a fake page and measured fixtures. No browser, no turn.

    ~/cloakbrowser-env/bin/python tests/test_gemini_driver.py

Measured 2026-09-25 and 2026-09-27 (docs/research/2026-09-27-gemini.md): the composer is a Quill
editor; a generated picture arrives from lh3.googleusercontent.com/rd-gg-dl/ during the turn, while
a user's upload shows from a blob and, reopened, from /rd-gg/ (so a loose "/rd-gg" match would take
it); the personal context switch is read on /personalization-settings, and a signed-out session is
sent to /saved-info, which also shows switches that are not this one. Measured 2026-10-01: for an
account /saved-info stays put and shows one switch, saved info, the account's other memory switch.
Prints N/83 PASSED.
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


class Switches:
    """The role=switch buttons a settings page shows: how many, and what the first one says."""

    def __init__(self, shown, checked):
        self.shown = shown
        self.checked = checked

    def count(self):
        return self.shown

    @property
    def first(self):
        return self

    def get_attribute(self, name):
        return self.checked if name == "aria-checked" else None


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
    `schedule` makes a page walk through urls over time, like a redirect chain, on its first load.

    An account, whose settings page stays put, has a saved-info page of its own (measured
    2026-10-01): `saved` is what its switch says (None paints none), `saved_shown` how many switches
    it shows, `saved_landed` where a load of it ends up. `asked` keeps every address a load asked
    for, `fails` makes the loads of an address raise, `closed` counts how often the tab was closed.
    """

    def __init__(self, clock, composer=True, landed=None, checked=None, saved="false", saved_shown=1,
                 saved_landed=None):
        self.clock = clock
        self.composer = composer
        self.landed = landed
        self.checked = checked
        self.saved, self.saved_shown, self.saved_landed = saved, saved_shown, saved_landed
        self.asked, self.fails, self.closed = [], (), 0
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
        # Seconds after the send before the address becomes the thread's; 0 is at once.
        self.thread_after = 0
        self.sent_at = None

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
        self.sent_at = self.clock.now
        if not self.thread_after:
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
        self.asked.append(url)
        if any(part in url for part in self.fails):
            raise RuntimeError("Timeout 60000ms exceeded")
        self.url = self.landed or url
        if url.endswith("/saved-info") and (self.landed or "").endswith("/personalization-settings"):
            self.url = self.saved_landed or url
        self.went_at = None
        if self.schedule and len(self.asked) == 1:
            self.went_at = self.clock.now
            self.url = self.schedule[0][1]

    def at_saved_info(self):
        return self.url.split("?")[0].rstrip("/").endswith("/saved-info")

    def wait_for_timeout(self, ms):
        self.clock.now += ms / 1000.0
        if self.thread_after and self.sent_at is not None \
                and self.clock.now - self.sent_at >= self.thread_after:
            self.url = self.thread
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
            if self.at_saved_info():
                return Switches(self.saved_shown if self.saved is not None else 0, self.saved)
            return Switches(1 if self.checked is not None else 0, self.checked)
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
        self.closed += 1

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class Fetched:
    def __init__(self, status, body):
        self.status = status
        self.ok = status == 200
        self._body = body

    def body(self):
        return self._body


class Node:
    """One element of the conversation list: its text, its aria-label, whether it shows, and what
    a click on it does. A hidden element cannot be clicked (Playwright waits for it to show, then
    times out), but an event sent to it still reaches its handler."""

    def __init__(self, text="", label=None, visible=True, on_click=None, inside=None):
        self.text, self.label, self.visible = text, label, visible
        self.on_click = on_click or (lambda: None)
        self.inside = inside or {}

    def count(self):
        return 1

    @property
    def first(self):
        return self

    def nth(self, i):
        return self

    def is_visible(self):
        return self.visible

    def inner_text(self, *args, **kwargs):
        return self.text

    def get_attribute(self, name):
        return self.label if name == "aria-label" else None

    def hover(self, *args, **kwargs):
        return None

    def click(self, *args, **kwargs):
        if not self.visible:
            raise RuntimeError("Timeout 10000ms exceeded: element is not visible")
        self.on_click()

    def dispatch_event(self, kind, *args, **kwargs):
        if kind == "click":
            self.on_click()

    def locator(self, selector):
        for key, found in self.inside.items():
            if key in selector:
                return found
        return Nodes()


class Nodes:
    """What one selector matches, in document order; nothing by default."""

    def __init__(self, *nodes):
        self.nodes = list(nodes)

    def count(self):
        return len(self.nodes)

    def nth(self, i):
        return self.nodes[i]

    @property
    def first(self):
        return self.nodes[0] if self.nodes else self


class Lazy:
    """A Playwright locator: it looks again every time it is asked, as the real one does."""

    def __init__(self, find):
        self.find = find

    @property
    def first(self):
        return Lazy(lambda: self.find().first)

    def nth(self, i):
        return Lazy(lambda: self.find().nth(i))

    def __getattr__(self, name):
        return getattr(self.find(), name)


class ListPage:
    """A thread's page with the conversation list, for delete_thread, as measured on 2026-09-27:
    the rows paint `rows_after` seconds after the page opens (0.3 to 2.4s after the composer); a
    row's only button is its menu, labelled "Lựa chọn khác cho <title>" and hidden unless the
    pointer rests on the row, which the list moving after it paints defeated in three loads of
    four; a click sent to the button itself opened the menu in three of three. The menu's delete
    item opens a dialog whose confirm button repeats the item's word. A thread that is there
    paints its turns `turns_after` seconds after the page opens (1.0 to 1.7s after the composer);
    one that is not keeps its address until `gone_after`, then the page sends it back to /app
    (0.5 to 0.9s after the composer). `redirect` sends every page elsewhere, as a signed-out
    session is sent to Google's sign-in."""

    def __init__(self, clock, cid, title="Secret Word Storage", label=None, rows_after=0.0,
                 hidden=True, exists=True, turns_after=1.5, gone_after=1.2, redirect=None):
        self.clock, self.cid, self.title = clock, cid, title
        self.label = "Lựa chọn khác cho " + title if label is None else label
        self.rows_after, self.hidden = rows_after, hidden
        self.exists, self.turns_after, self.gone_after = exists, turns_after, gone_after
        self.redirect = redirect
        self.url = "https://gemini.google.com/app"
        self.loaded = clock.now
        self.menu = self.dialog = self.deleted = False

    def there(self):
        return self.exists and not self.deleted

    def goto(self, url, *args, **kwargs):
        self.loaded, self.menu, self.dialog = self.clock.now, False, False
        self.url = url
        self.settle()

    def settle(self):
        if self.clock.now - self.loaded < self.gone_after:
            return
        if self.redirect:
            self.url = self.redirect
        elif self.url.endswith("/" + self.cid) and not self.there():
            self.url = "https://gemini.google.com/app"

    def wait_for_timeout(self, ms):
        self.clock.now += ms / 1000.0
        self.settle()

    def open_menu(self):
        self.menu = True

    def open_dialog(self):
        self.menu, self.dialog = False, True

    def confirm(self):
        self.dialog, self.deleted = False, True

    def cancel(self):
        self.dialog = False

    def locator(self, selector):
        return Lazy(lambda: self.match(selector))

    def match(self, selector):
        if "ql-editor" in selector:
            return Node()
        if selector == "user-query":
            shown = (self.there() and self.url.endswith("/" + self.cid)
                     and self.clock.now - self.loaded >= self.turns_after)
            return Nodes(Node(text="Bạn đã nói hello")) if shown else Nodes()
        if selector == 'a[href="/app/{}"]'.format(self.cid):
            if not self.there() or self.clock.now - self.loaded < self.rows_after:
                return Nodes()
            menu = Node(label=self.label, visible=not self.hidden, on_click=self.open_menu)
            row = Node(inside={"button": Nodes(menu)})
            return Nodes(Node(text=self.title, inside={"ancestor": row}))
        if "menuitem" in selector and "delete" in selector:
            return Nodes(Node(text="Xoá", on_click=self.open_dialog)) if self.menu else Nodes()
        if "mat-dialog-container" in selector:
            if not self.dialog:
                return Nodes()
            buttons = Nodes(Node(text="Huỷ", on_click=self.cancel),
                            Node(text="Xoá", on_click=self.confirm))
            return Nodes(Node(inside={"button": buttons}))
        return Nodes()


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
        self.opened = 0

    def new_page(self):
        self.opened += 1
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
    p._guard()
    record("personal context off reads off", p.memory == "off", "health memory {!r}".format(p.memory))

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
    try:
        p._guard()
        outcome = "sent"
    except ProviderError as exc:
        outcome = exc.kind
    record("a switch that never renders reads unknown and does not block",
           p.memory == "unknown" and outcome == "sent",
           "health memory {!r}, outcome {!r}".format(p.memory, outcome))

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

    # Google's unusual-traffic check, measured 2026-09-27: every Gemini page went to
    # www.google.com/sorry/, whose q token starts with the network's own address. This token holds
    # 10.0.0.1, never a real one.
    sorry = "https://www.google.com/sorry/index?continue=/app&q=EgQKAAABbm90LXJlYWw"

    def refusal(page, settings):
        started, p = clock.now, provider_on(page, settings)
        try:
            p._run("hello")
            return "returned", "", clock.now - started, p
        except ProviderError as exc:
            return exc.kind, str(exc), clock.now - started, p
        except Exception as exc:
            return "crashed", "{}: {}".format(type(exc).__name__, exc), clock.now - started, p

    page = Page(clock, composer=False, landed=sorry)
    page.replies = [stream_ok]
    kind, message, took, p = refusal(page, off())
    record("a turn that lands on Google's unusual-traffic check fails at once, naming it",
           kind == "provider_error" and "unusual-traffic" in message and took < 5
           and page.sent == [], "{} after {:.0f}s: {!r}".format(kind, took, message[:120]))
    record("the unusual-traffic check's url never reaches the error a user sees",
           "q=" not in message and "EgQ" not in message and "sorry/index" not in message,
           repr(message[:160]))

    settings = Page(clock, composer=False, checked=None, landed=sorry)
    page = Page(clock)
    page.replies = [stream_ok]
    kind, message, took, p = refusal(page, settings)
    record("the guard reads Google's unusual-traffic check as blocked, never as signed out",
           kind == "provider_error" and "unusual-traffic" in message and p.memory == "blocked"
           and page.sent == [], "{} memory {} sent {}: {!r}".format(kind, p.memory, len(page.sent),
                                                                   message[:120]))

    page = ListPage(clock, "239f0ba819d9963c", hidden=False, gone_after=0, redirect=sorry)
    started = clock.now
    try:
        provider_on(page).delete_thread(gemini.HOME + "/239f0ba819d9963c")
        what = "returned"
    except ProviderError as exc:
        what = "refused: {}".format(exc)
    record("a deletion that meets Google's unusual-traffic check is refused at once, nothing deleted",
           what.startswith("refused") and "unusual-traffic" in what and not page.deleted
           and clock.now - started < 5, "{} after {:.0f}s deleted {}".format(
               what[:120], clock.now - started, page.deleted))

    # The account's other memory switch, measured 2026-10-01: saved info has /saved-info to itself,
    # with one switch; /personalization-settings says nothing about it. Its label follows the
    # interface's language and its id is the personal context switch's own, so it is told by its
    # page and by being the only switch there.
    home, saved_url = "https://gemini.google.com/personalization-settings", "https://gemini.google.com/saved-info"
    signin = "https://accounts.google.com/v3/signin/identifier?continue=x"

    def account(personal="false", **saved):
        return Page(clock, composer=False, landed=home, checked=personal, **saved)

    def look(settings, p=None):
        """(outcome, its words, the provider, seconds) of one look before speaking."""
        p, started = p or provider_on(Page(clock), settings), clock.now
        try:
            p._guard()
            return "sent", "", p, clock.now - started
        except ProviderError as exc:
            return exc.kind, str(exc), p, clock.now - started
        except Exception as exc:
            return "crashed", "{}: {}".format(type(exc).__name__, exc), p, clock.now - started

    def pages(settings):
        return [url.rsplit("/", 1)[-1] for url in settings.asked]

    settings = account(saved="true")
    outcome, said, p, took = look(settings)
    record("saved info on refuses the turn, naming the switch and its page",
           outcome == "provider_misconfigured" and "saved info" in said
           and "gemini.google.com/saved-info" in said and "personal context" not in said
           and p.memory == "on", "outcome {!r} memory {!r} {!r}".format(outcome, p.memory, said[:120]))

    page = Page(clock)
    page.replies, page.answer = [stream_ok], "should never be asked"
    what, result = run_on(page, account(saved="true"))
    record("a turn with saved info on is refused before anything is sent",
           what.startswith("refused: provider_misconfigured") and page.sent == [],
           "{} sent {}".format(what, len(page.sent)))

    settings = account()
    outcome, said, p, took = look(settings)
    record("both switches off read off, each from its own page, in one tab",
           outcome == "sent" and p.memory == "off" and settings.asked == [home, saved_url]
           and p._context.opened == 1, "outcome {!r} memory {!r} loaded {} tabs {}".format(
               outcome, p.memory, pages(settings), p._context.opened))

    for label, saved in (("a saved-info switch that never renders", {"saved": None}),
                         ("two switches on the saved-info page, the first off", {"saved_shown": 2}),
                         ("two switches on the saved-info page, the first on",
                          {"saved_shown": 2, "saved": "true"}),
                         ("a saved-info switch that says neither true nor false", {"saved": "mixed"}),
                         ("a saved-info page sent elsewhere on the site",
                          {"saved_landed": "https://gemini.google.com/app"})):
        outcome, said, p, took = look(account(**saved))
        record("{} reads unknown and does not block".format(label),
               outcome == "sent" and p.memory == "unknown" and took < 20,
               "outcome {!r} memory {!r} after {:.0f}s".format(outcome, p.memory, took))

    outcome, said, p, took = look(account(personal=None, saved="true"))
    record("saved info on refuses even when personal context could not be read",
           outcome == "provider_misconfigured" and "saved info" in said and p.memory == "on",
           "outcome {!r} memory {!r} {!r}".format(outcome, p.memory, said[:60]))

    settings = account(personal=None)
    outcome, said, p, took = look(settings)
    record("personal context unread and saved info off reads unknown, never off",
           outcome == "sent" and p.memory == "unknown" and settings.asked == [home, saved_url],
           "outcome {!r} memory {!r} loaded {}".format(outcome, p.memory, pages(settings)))

    page = Page(clock)
    page.replies = [stream_ok]
    kind, message, took, p = refusal(page, account(saved_landed=sorry))
    record("Google's unusual-traffic check on the saved-info page is blocked, a provider error",
           kind == "provider_error" and "unusual-traffic" in message and p.memory == "blocked"
           and page.sent == [] and "q=" not in message and "EgQ" not in message,
           "{} memory {} sent {}: {!r}".format(kind, p.memory, len(page.sent), message[:80]))

    outcome, said, p, took = look(account(saved_landed=signin))
    record("a saved-info page that ends at Google's sign-in is a signed-out session, refused",
           outcome == "provider_misconfigured" and "signed out" in said and p.memory == "signed-out",
           "outcome {!r} memory {!r} {!r}".format(outcome, p.memory, said[:60]))

    for label, settings, kind, memory, words in (
            ("personal context on", account(personal="true", saved="true"), "provider_misconfigured",
             "on", "personal context"),
            ("a signed-out session", Page(clock, composer=False, landed=saved_url, checked="false"),
             "provider_misconfigured", "signed-out", "signed out"),
            ("Google's unusual-traffic check", Page(clock, composer=False, landed=sorry),
             "provider_error", "blocked", "unusual-traffic")):
        outcome, said, p, took = look(settings)
        record("{}: the look ends at the settings page, saved info is not loaded".format(label),
               outcome == kind and p.memory == memory and words in said and "saved info" not in said
               and settings.asked == [home], "outcome {!r} memory {!r} loaded {} {!r}".format(
                   outcome, p.memory, pages(settings), said[:50]))

    settings = account()
    page = Page(clock)
    page.answer, page.replies = "a plain reply", [stream_ok]
    p = provider_on(page, settings)
    first = p._run("hello")
    settings.saved = "true"
    try:
        p._run("hello again")
        second = "sent"
    except ProviderError as exc:
        second = exc.kind
    record("every turn reads both switches again: saved info turned on between two turns refuses the second",
           first.success and second == "provider_misconfigured" and len(page.sent) == 1
           and settings.asked == [home, saved_url] * 2 and p.memory == "on",
           "first {} second {!r} sent {} loaded {} memory {!r}".format(
               first.success, second, len(page.sent), pages(settings), p.memory))

    for label, after, expected in (("unreadable", None, "unknown"), ("off", "false", "off")):
        settings = account(saved="true")
        outcome, said, p, took = look(settings)
        settings.saved = after
        again, said, p, took = look(settings, p)
        record("memory keeps no earlier reading: on, then {}, reads {}".format(label, expected),
               outcome == "provider_misconfigured" and again == "sent" and p.memory == expected,
               "first {!r} then {!r} memory {!r}".format(outcome, again, p.memory))

    failing = account(saved="true")
    failing.fails = ("personalization-settings",)
    outcome, said, p, took = look(failing)
    record("a settings page that fails to load does not stop saved info from being read",
           outcome == "provider_misconfigured" and "saved info" in said and p.memory == "on",
           "outcome {!r} memory {!r} loaded {}".format(outcome, p.memory, pages(failing)))

    failing = account()
    failing.fails = ("saved-info",)
    outcome, said, p, took = look(failing)
    record("a saved-info page that fails to load reads unknown and does not block",
           outcome == "sent" and p.memory == "unknown" and failing.asked == [home, saved_url],
           "outcome {!r} memory {!r} loaded {}".format(outcome, p.memory, pages(failing)))

    tabs = []
    for label, settings in (("off", account()), ("saved info on", account(saved="true")),
                            ("unreadable", account(saved=None)), ("blocked", account(saved_landed=sorry)),
                            ("personal context on", account(personal="true")),
                            ("signed out", Page(clock, composer=False, landed=saved_url, checked="false")),
                            ("a failed load", failing)):
        before = settings.closed
        outcome, said, p, took = look(settings)
        tabs.append((label, p._context.opened, settings.closed - before))
    record("the settings tab is closed whatever the look found",
           all(opened == 1 and closed == 1 for label, opened, closed in tabs), repr(tabs))

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

    # The real gemini gate, 2026-09-27: no thread was ever deleted. Measured without deleting: the
    # conversation list paints its rows after the composer, and a row's menu button shows only
    # while the pointer rests on the row.
    cid = "239f0ba819d9963c"

    def delete_on(page):
        try:
            return "returned {}".format(provider_on(page).delete_thread(gemini.HOME + "/" + cid))
        except ProviderError as exc:
            return "refused: {}".format(str(exc)[:60])
        except Exception as exc:
            return "crashed: {}: {}".format(type(exc).__name__, str(exc)[:60])

    page = ListPage(clock, cid, rows_after=3.0, hidden=False)
    what = delete_on(page)
    record("a thread whose row paints after the composer is still deleted",
           what == "returned True" and page.deleted, "{} deleted {}".format(what, page.deleted))

    # The second real gate kept its database: one thread was deleted yet reported "still opens
    # after delete", and a cancelled turn's thread, which Gemini never kept, "has no row". The
    # address of a thread that is not there only goes back to /app a moment after the composer.
    page = ListPage(clock, cid, hidden=False)
    what = delete_on(page)
    record("a deleted thread whose address lingers a moment is not reported as still there",
           what == "returned True" and page.deleted, "{} deleted {}".format(what, page.deleted))

    page = ListPage(clock, cid, exists=False)
    what = delete_on(page)
    record("a thread that is not there counts as removed once the page sends it back to /app",
           what == "returned True" and not page.menu, "{} menu opened {}".format(what, page.menu))

    page = ListPage(clock, cid, hidden=False, gone_after=0,
                    redirect="https://accounts.google.com/v3/signin/identifier?continue=x")
    what = delete_on(page)
    record("a thread page sent to Google's sign-in is never counted as removed",
           what.startswith("refused") and not page.deleted, "{} deleted {}".format(what, page.deleted))

    page = ListPage(clock, cid)
    what = delete_on(page)
    record("a row whose menu button shows only under the pointer is still deleted",
           what == "returned True" and page.deleted, "{} deleted {}".format(what, page.deleted))

    page = ListPage(clock, cid, label="Lựa chọn khác cho Another conversation", hidden=False)
    what = delete_on(page)
    record("a row menu that names another conversation is refused, nothing deleted",
           what.startswith("refused") and not page.deleted, "{} deleted {}".format(what, page.deleted))

    page = ListPage(clock, cid, rows_after=3600, hidden=False)
    what = delete_on(page)
    record("a row that never paints is refused within a bounded wait",
           what.startswith("refused") and not page.deleted, "{} deleted {}".format(what, page.deleted))

    # The same gate: a turn cancelled a moment after it was sent (the lease there is 2s, so the
    # cancel arrives within a second) named no thread, since the address becomes the thread's only
    # a little later; the thread was left in the account with nothing to remove it.
    def cancel_on(page):
        p = provider_on(page, off())
        p.bind(stop_hook=lambda: True)
        try:
            p._run("draw a picture, then delete me while running")
            return "returned", p.last_cancelled_thread
        except gemini.JobCancelled:
            return "cancelled", p.last_cancelled_thread
        except Exception as exc:
            return "crashed: {}: {}".format(type(exc).__name__, str(exc)[:50]), None

    page = Page(clock)
    page.thread_after, page.replies = 3, []
    what, named = cancel_on(page)
    record("a turn cancelled before its address shows still names its thread",
           what == "cancelled" and named == page.thread, "{} named {}".format(what, named))

    page = Page(clock)
    page.thread_after, page.replies = 3600, []
    what, named = cancel_on(page)
    record("a cancelled turn whose address never shows gives up within a bounded wait",
           what == "cancelled" and named is None, "{} named {}".format(what, named))

    for url, expected in (("https://gemini.google.com/app/659ed82f23b56ced", "659ed82f23b56ced"),
                          ("https://gemini.google.com/app", None)):
        got = gemini.GeminiProvider._thread_id(type("AtUrl", (), {"url": url})())
        record("thread id of {}".format(url.rsplit("/", 1)[-1]), got == expected,
               "got {!r}, expected {!r}".format(got, expected))

    return finish()


if __name__ == "__main__":
    sys.exit(main())
