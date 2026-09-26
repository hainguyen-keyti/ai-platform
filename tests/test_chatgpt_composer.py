#!/usr/bin/env python3
"""ChatGPT's composer, opening and sending, against a fake page. No browser, no turn.

    ~/cloakbrowser-env/bin/python tests/test_chatgpt_composer.py

Measured 2026-09-27 (docs/research/2026-09-27-chatgpt-composer.md): the page first
paints textarea#pending-home-input and mounts the real composer, a ProseMirror
div with no id, about ten seconds later; #prompt-textarea is gone; a failed first
turn leaves /c/local-chatgpt:<uuid> in the address. The driver used to call a
signed-in session "probably logged out" whenever the composer did not appear.
Prints N/8 PASSED.
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
        self.page.text += text

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
            if key == "Backspace":
                self.page.text = ""


class Page:
    def __init__(self, clock, has=(), token="token", url="https://chatgpt.com/"):
        self.clock = clock
        self.has = set(has)
        self.token = token
        self.url = url
        self.text = ""
        self.enters = 0
        self.sent = []
        self.keyboard = Keyboard(self)

    def goto(self, url, *args, **kwargs):
        self.url = url

    def wait_for_timeout(self, ms):
        self.clock.now += ms / 1000.0

    def locator(self, selector):
        composer = (PROSEMIRROR in self.has and ("ProseMirror" in selector
                                                 or 'contenteditable="true"' in selector))
        placeholder = (PLACEHOLDER in self.has and (PLACEHOLDER in selector
                                                    or selector.strip() == "textarea"))
        return Box(self, composer or placeholder)

    def evaluate(self, script, *args):
        if script == chatgpt.SESSION_TOKEN:
            return self.token
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
