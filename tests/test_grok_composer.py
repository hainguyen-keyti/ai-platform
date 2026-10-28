#!/usr/bin/env python3
"""Grok's composer at the send, against a fake page. No browser, no turn.

    ~/cloakbrowser-env/bin/python tests/test_grok_composer.py

Measured 2026-10-28 (issue #11): on a thread opened again, the page first shows a textarea labelled
"Ask Grok anything", the only composer the driver can find then, and some seconds later mounts the
real one, a ProseMirror inside [data-testid="chat-input"], and the textarea is gone. The driver typed
its three tries into the textarea it had found at the open, and the turn failed as never reaching
the composer, nothing sent. Prints N/N PASSED.
"""

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from src.providers import grok  # noqa: E402
from src.providers.base import ProviderError  # noqa: E402

PLACEHOLDER = 'textarea[aria-label="Ask Grok anything"]'
EDITORS = ('[data-testid="chat-input"] .ProseMirror[contenteditable="true"]',
           '.ProseMirror[contenteditable="true"]')
PROMPT = "tạo ảnh cô gái genz việt nam, làm kol thời trang đi"

results = []


def record(name, ok, detail):
    results.append(ok)
    print("[{}] {}  {}".format("PASS" if ok else "FAIL", name, detail), flush=True)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Gone(Exception):
    """What a click or a focus on an element no longer on the page ends in: a timeout."""


class Keyboard:
    def __init__(self, page):
        self.page = page

    def insert_text(self, text):
        box = self.page.focused
        if box and self.page.present(box):
            self.page.text[box] = self.page.text.get(box, "") + text

    def press(self, key):
        box = self.page.focused
        if not box or not self.page.present(box):
            return
        if key == "Enter":
            self.page.sent.append(self.page.text.get(box, ""))
            self.page.text[box] = ""
        elif key == "Backspace":
            self.page.text[box] = ""


class Box:
    def __init__(self, page, selector):
        self.page, self.selector = page, selector

    @property
    def first(self):
        return self

    def count(self):
        return 1 if self.page.present(self.selector) else 0

    def is_visible(self):
        return self.page.present(self.selector)

    def scroll_into_view_if_needed(self, timeout=None):
        if not self.page.present(self.selector):
            self.page.clock.now += (timeout or 30000) / 1000.0
            raise Gone(self.selector)

    def click(self, timeout=None):
        if not self.page.present(self.selector):
            self.page.clock.now += (timeout or 30000) / 1000.0
            raise Gone(self.selector)
        self.page.focused = self.selector

    def evaluate(self, script, *args):
        self.click(30000)

    def inner_text(self, *args, **kwargs):
        if not self.page.present(self.selector):
            raise Gone(self.selector)
        return self.page.text.get(self.selector, "")


class ComposerPage:
    """The placeholder textarea is there until `mounts_at` (seconds on the clock from the start), the
    editor from then on; `editor_from_start` has the editor and no placeholder all along, `none` has
    no composer at all. A selector the page does not know is never there."""

    def __init__(self, clock, mounts_at=0.0, none=False):
        self.clock, self.start, self.mounts_at, self.none = clock, clock.now, mounts_at, none
        self.text, self.sent, self.focused = {}, [], None
        self.keyboard = Keyboard(self)

    def mounted(self):
        return self.clock.now - self.start >= self.mounts_at

    def present(self, selector):
        if self.none:
            return False
        if selector == PLACEHOLDER:
            return not self.mounted()
        if selector in EDITORS:
            return self.mounted()
        return False

    def locator(self, selector):
        return Box(self, selector)

    def wait_for_timeout(self, ms):
        self.clock.now += ms / 1000.0


def send_on(page, composer):
    """(what happened, the turns the page sent) for one _send with the composer the open found."""
    scratch = Path(tempfile.mkdtemp(prefix="grok-composer-"))
    try:
        driver = grok.GrokProvider(scratch, scratch)
        driver._send(page, composer, PROMPT)
        return "sent", page.sent
    except ProviderError as exc:
        return "refused: {}".format(str(exc)[:50]), page.sent
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def main():
    clock = Clock()
    grok.time = clock

    # As measured: the open found the placeholder; by the send the editor has replaced it.
    page = ComposerPage(clock, mounts_at=10)
    clock.now += 20
    what, sent = send_on(page, PLACEHOLDER)
    record("a placeholder found at the open and gone by the send: the turn goes into the editor",
           what == "sent" and sent == [PROMPT], "{}, sent {}".format(what, sent))

    page = ComposerPage(clock)
    what, sent = send_on(page, EDITORS[0])
    record("an editor there from the start gets the turn, sent once",
           what == "sent" and sent == [PROMPT], "{}, sent {}".format(what, sent))

    page = ComposerPage(clock, none=True)
    what, sent = send_on(page, EDITORS[0])
    record("a page with no composer at all refuses the turn, nothing sent",
           what.startswith("refused") and sent == [], "{}, sent {}".format(what, sent))

    passed = sum(1 for ok in results if ok)
    print("{}/{} PASSED".format(passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
