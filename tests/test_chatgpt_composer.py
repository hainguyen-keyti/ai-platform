#!/usr/bin/env python3
"""ChatGPT's composer, opening and sending, against a fake page. No browser, no turn.

    ~/cloakbrowser-env/bin/python tests/test_chatgpt_composer.py

Measured 2026-09-27 (docs/research/2026-09-27-chatgpt-composer.md): the page first
paints textarea#pending-home-input and mounts the real composer, a ProseMirror
div with no id, about ten seconds later; #prompt-textarea is gone; a failed first
turn leaves /c/local-chatgpt:<uuid> in the address. The driver used to call a
signed-in session "probably logged out" whenever the composer did not appear.
Prints N/17 PASSED.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from src.providers import chatgpt  # noqa: E402
from src.providers.base import ProviderError  # noqa: E402

PROSEMIRROR = "ProseMirror"
PLACEHOLDER = "pending-home-input"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Missing(Exception):
    pass


class Box:
    """One element. Pressing Enter in it sends: the page then empties it."""

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

    def _need(self):
        if not self.present:
            raise Missing("no such element")

    def click(self, *args, **kwargs):
        self._need()

    def focus(self, *args, **kwargs):
        self._need()

    def fill(self, text, *args, **kwargs):
        self._need()
        self.page.text = text

    def inner_text(self, *args, **kwargs):
        return self.page.text if self.present else ""

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class Keyboard:
    def __init__(self, page):
        self.page = page

    def insert_text(self, text):
        # truncate: a composer that loses the end of a long paste.
        self.page.text += text[:self.page.truncate] if self.page.truncate else text

    def type(self, text, *args, **kwargs):
        # What Playwright does: one key per character, and a newline is Enter.
        for ch in text:
            if ch == "\n":
                self.press("Enter")
            else:
                self.page.text += ch

    def press(self, key, *args, **kwargs):
        if key == "Enter":
            self.page.enters += 1
            if self.page.text.strip():
                self.page.sent.append(self.page.text)
            self.page.text = ""
        elif key in ("ControlOrMeta+a", "Backspace"):
            # stuck: a composer that refuses to be cleared.
            if key == "Backspace" and not self.page.stuck:
                self.page.text = ""


class Page:
    # composer_on_load: the composer mounts only from that load on (a slow first load).
    def __init__(self, clock, has=(), token="token", url="https://chatgpt.com/", composer_on_load=None,
                 thread_status=None, screenshot_fails=False):
        self.clock = clock
        self.has = set(has)
        self.token = token
        self.url = url
        self.text = ""
        self.enters = 0
        self.sent = []
        self.truncate = None
        self.stuck = False
        self.keyboard = Keyboard(self)
        self.loads = 0
        self.composer_on_load = composer_on_load
        self.thread_status = thread_status
        self.screenshot_fails = screenshot_fails
        self.pictures = []

    def goto(self, url, *args, **kwargs):
        self.url = url
        self.loads += 1

    def reload(self, *args, **kwargs):
        self.loads += 1

    def screenshot(self, path=None, *args, **kwargs):
        if self.screenshot_fails:
            raise RuntimeError("the page could not be captured")
        self.pictures.append(path)

    def wait_for_timeout(self, ms):
        self.clock.now += ms / 1000.0

    def locator(self, selector):
        # A comma is a list of alternatives, as in the browser: any part may match.
        parts = [p.strip() for p in selector.split(",")]
        mounted = PROSEMIRROR in self.has or (
            self.composer_on_load is not None and self.loads >= self.composer_on_load)
        composer = mounted and any(
            "ProseMirror" in p or 'contenteditable="true"' in p for p in parts)
        placeholder = PLACEHOLDER in self.has and any(
            PLACEHOLDER in p or p.startswith("textarea") for p in parts)
        return Box(self, composer or placeholder)

    def evaluate(self, script, *args):
        if script == chatgpt.SESSION_TOKEN:
            return self.token
        if script == chatgpt.FETCH_THREAD and self.thread_status is not None:
            return {"status": self.thread_status}
        return None

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


results = []


def record(name, ok, detail):
    results.append(ok)
    print("[{}] {}  {}".format("PASS" if ok else "FAIL", name, detail), flush=True)


def provider_on(page):
    p = chatgpt.ChatGPTProvider(Path("/tmp/chatgpt-composer-test"), ROOT / "storage" / "sessions")
    p._page = page
    p._ensure_page = lambda: page
    return p


def main():
    clock = Clock()
    chatgpt.time = clock

    page = Page(clock, has={PROSEMIRROR})
    ready = provider_on(page)._composer_ready(page, 5)
    record("the new composer counts as ready", ready is True, "ready {}".format(ready))

    page = Page(clock, has={PLACEHOLDER})
    ready = provider_on(page)._composer_ready(page, 5)
    record("the placeholder textarea does not", ready is False, "ready {}".format(ready))

    page = Page(clock, has=(), token="token")
    try:
        provider_on(page)._open()
        said = "opened"
    except ProviderError as exc:
        said = str(exc)
    except Exception as exc:
        said = "{}: {}".format(type(exc).__name__, exc)
    record("a signed-in session with no composer is not called logged out",
           said != "opened" and "logged out" not in said, repr(said[:120]))

    page = Page(clock, has=(), token=None)
    try:
        provider_on(page)._open()
        said = "opened"
    except ProviderError as exc:
        said = str(exc)
    except Exception as exc:
        said = "{}: {}".format(type(exc).__name__, exc)
    record("a session with no token is still called logged out", "logged out" in said,
           repr(said[:120]))

    # Measured 2026-09-29: a freshly launched browser mounted the composer at 7.8 to 34.9s, and once
    # not within the 45s wait, failing a real gate's first turn; a second load is the cheap retry.
    def open_on(page, thread_url=None):
        try:
            return page is provider_on(page)._open(thread_url), ""
        except ProviderError as exc:
            return False, str(exc)
        except Exception as exc:
            return False, "{}: {}".format(type(exc).__name__, exc)

    page = Page(clock, has=(), token="token", composer_on_load=2)
    opened, said = open_on(page)
    record("a composer that shows only on the second load of the home page is waited for",
           opened, "loads {} said {!r}".format(page.loads, said[:80]))

    # Still on the thread after two loads: falling back to a new chat would lose the conversation.
    thread = "https://chatgpt.com/c/6ab805cb-f334-83ec-9df4-aa8e1fc863a8"
    page = Page(clock, has=(), token="token", composer_on_load=2, thread_status=200)
    opened, said = open_on(page, thread)
    record("a composer that shows only on the second load of a stored thread is waited for",
           opened and page.url == thread and page.loads == 2,
           "loads {} on {} said {!r}".format(page.loads, page.url[-20:], said[:80]))

    page = Page(clock, has=(), token="token")
    provider = provider_on(page)
    opened, said = open_on(page)
    kept = [Path(p) for p in page.pictures if p]
    record("a composer that never shows leaves one picture in the diagnostics and the same error",
           not opened and "although the session is signed in" in said and page.loads == 2
           and len(page.pictures) == 1 and len(kept) == 1
           and kept[0].parent == provider.media_path.parent / "diagnostics",
           "loads {} pictures {} said {!r}".format(page.loads, [str(p) for p in page.pictures], said[:60]))

    page = Page(clock, has=(), token="token", thread_status=200)
    opened, said = open_on(page, thread)
    record("a stored thread whose composer never shows is loaded twice and leaves one picture",
           not opened and "did not open" in said and page.loads == 2 and len(page.pictures) == 1,
           "loads {} pictures {} said {!r}".format(page.loads, len(page.pictures), said[:60]))

    # A picture that cannot be taken must not turn a provider error into a worker error.
    page = Page(clock, has=(), token="token", screenshot_fails=True)
    opened, said = open_on(page)
    record("a picture that cannot be taken leaves the same error",
           not opened and said.startswith("composer never appeared although the session is signed in"),
           "said {!r}".format(said[:80]))

    prompt = "user: first line\n\nassistant: second line\n\nReply to this next message only:\nthird"
    page = Page(clock, has={PROSEMIRROR})
    try:
        provider_on(page)._send(page, prompt)
        err = ""
    except Exception as exc:
        err = "{}: {}".format(type(exc).__name__, exc)
    record("a multi-line prompt leaves as exactly one turn",
           page.enters == 1 and len(page.sent) == 1 and page.sent[0] == prompt,
           "enters {} sent {} {}".format(page.enters, len(page.sent), err))

    def send_on(page):
        try:
            provider_on(page)._send(page, prompt)
            return ""
        except ProviderError as exc:
            return str(exc)
        except Exception as exc:
            return "{}: {}".format(type(exc).__name__, exc)

    page = Page(clock, has={PROSEMIRROR})
    page.text = "an old draft left in the box"
    err = send_on(page)
    record("a draft left in the composer is not sent along",
           page.sent == [prompt], "sent {!r} {}".format([s[:40] for s in page.sent], err))

    # The draft that matters most is the prompt itself, typed by an attempt that
    # never sent: typed again on top, both ends still match and it goes out twice.
    page = Page(clock, has={PROSEMIRROR})
    page.text = prompt
    err = send_on(page)
    record("a prompt already in the composer is sent once, not twice",
           page.sent == [prompt], "sent {} chars {}".format([len(s) for s in page.sent], err))

    page = Page(clock, has={PROSEMIRROR})
    page.truncate = 60
    err = send_on(page)
    record("a prompt that lands cut short is not sent", page.sent == [] and bool(err),
           "sent {} error {!r}".format(len(page.sent), err[:60]))

    page = Page(clock, has={PROSEMIRROR})
    page.text = "an old draft left in the box"
    page.stuck = True
    err = send_on(page)
    record("a composer that cannot be cleared is not typed into twice",
           page.sent == [] and bool(err), "sent {!r} error {!r}".format(
               [s[:40] for s in page.sent], err[:60]))

    for url, expected in (("https://chatgpt.com/c/local-chatgpt%3A79ca01df-bb1f", None),
                          ("https://chatgpt.com/c/WEB:79ca01df-bb1f", None),
                          ("https://chatgpt.com/c/6ab805cb-f334-83ec-9df4-aa8e1fc863a8",
                           "6ab805cb-f334-83ec-9df4-aa8e1fc863a8")):
        got = chatgpt.ChatGPTProvider._thread_id(Page(clock, url=url))
        record("thread id of {}".format(url.rsplit("/", 1)[-1][:22]), got == expected,
               "got {!r}, expected {!r}".format(got, expected))

    passed = sum(1 for ok in results if ok)
    print("{}/{} PASSED".format(passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
