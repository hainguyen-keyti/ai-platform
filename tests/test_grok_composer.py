#!/usr/bin/env python3
"""Grok's composer at the send, against a fake page. No browser, no turn.

    ~/cloakbrowser-env/bin/python tests/test_grok_composer.py

Measured 2026-10-28 (issue #11): on a thread opened again, the page first shows a textarea labelled
"Ask Grok anything", the only composer the driver can find then, and some seconds later mounts the
real one, a ProseMirror inside [data-testid="chat-input"], and the textarea is gone. The driver typed
its three tries into the textarea it had found at the open, and the turn failed as never reaching
the composer, nothing sent. Prints N/N PASSED.
"""

import json
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
# Measured 2026-11-16 (tests/grok_probe.py composer, model, turn, thread): beside the composer, on a
# new chat and on a thread's page alike, one button whose aria-label is "Model: <name>" opens a menu
# of menuitemcheckbox rows (Auto, Fast, Expert, Build, Heavy, Bot); a row pressed closes the menu and
# the label follows, and the choice holds across loads. With Bot chosen a sent turn went to /bot/<id>,
# the account's one bot chat, and no thread was made.
MODEL_BUTTON = 'button[aria-haspopup="menu"][aria-label^="Model"]'
MODEL_ITEM = '[role=menu] [role^=menuitem]'
MODELS = ("Auto", "Fast", "Expert", "Build", "Heavy", "Bot")
# The model every turn goes out on is the driver's to name (DECISIONS 2026-11-16); the cases below
# hold for whichever it names: WANTED, another ordinary model, and a menu that does not offer WANTED.
WANTED = grok.MODEL
OTHER = next(name for name in MODELS if name not in (WANTED, "Bot"))
WITHOUT = tuple(name for name in MODELS if name != WANTED)

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
        if key == "Escape":
            self.page.menu_open = False
            return
        box = self.page.focused
        if not box or not self.page.present(box):
            return
        if key == "Enter":
            self.page.sent.append(self.page.text.get(box, ""))
            self.page.sent_with.append(self.page.model)
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


class ModelButton:
    """The selector beside the composer: its label says the model, a click opens its menu."""

    def __init__(self, page):
        self.page = page

    @property
    def first(self):
        return self

    def count(self):
        return 1 if self.page.model is not None else 0

    def get_attribute(self, name, **kwargs):
        if self.page.model is None:
            raise Gone(MODEL_BUTTON)
        self.page.label_reads += 1
        if self.page.repaints_after is not None and self.page.label_reads > self.page.repaints_after:
            # Once: the page paints its saved choice and then obeys the menu like any other.
            self.page.model, self.page.repaints_after = self.page.repaints_to, None
        return "Model: {}".format(self.page.model) if name == "aria-label" else None

    def click(self, timeout=None):
        if self.page.model is None:
            raise Gone(MODEL_BUTTON)
        self.page.menu_opened += 1
        self.page.menu_open = True


class ModelItems:
    """The open menu's rows, narrowed by the words a row begins with."""

    def __init__(self, page, wanted=None):
        self.page, self.wanted = page, wanted

    def filter(self, has_text=None):
        return ModelItems(self.page, has_text)

    def _rows(self):
        if not self.page.menu_open:
            return []
        return [name for name in self.page.models if self.wanted is None or self.wanted.search(name)]

    @property
    def first(self):
        return self

    def count(self):
        return len(self._rows())

    def click(self, timeout=None):
        rows = self._rows()
        if not rows:
            raise Gone(MODEL_ITEM)
        self.page.menu_open = False
        if not self.page.choice_ignored:
            self.page.model = rows[0]


class ComposerPage:
    """The placeholder textarea is there until `mounts_at` (seconds on the clock from the start), the
    editor from then on; `editor_from_start` has the editor and no placeholder all along, `none` has
    no composer at all. A selector the page does not know is never there. `model` is what the
    selector beside the composer reads (None: no selector on the page), `models` the rows its menu
    offers, and `choice_ignored` a page whose row takes the press and changes nothing. `repaints_after`
    is a page that reads `model` that many times and `repaints_to` from then on: a label painted
    first with a default and then with the account's saved choice (the tier 2 review, 2026-11-16)."""

    def __init__(self, clock, mounts_at=0.0, none=False, model=WANTED, models=MODELS, choice_ignored=False,
                 body="What's on the agenda today?", no_picture=False, repaints_after=None, repaints_to="Bot"):
        self.label_reads, self.repaints_after, self.repaints_to = 0, repaints_after, repaints_to
        self.clock, self.start, self.mounts_at, self.none = clock, clock.now, mounts_at, none
        self.text, self.sent, self.focused = {}, [], None
        self.model, self.models, self.choice_ignored = model, models, choice_ignored
        self.menu_open, self.menu_opened, self.sent_with = False, 0, []
        self.keyboard = Keyboard(self)
        # What a person would see: the address, the tab's title, the page's words, a picture of it.
        self.url, self.body, self.no_picture, self.loads = "https://grok.com/", body, no_picture, 0

    def goto(self, url, **kwargs):
        self.loads += 1

    def title(self):
        return "Grok"

    def inner_text(self, selector, **kwargs):
        return self.body

    def screenshot(self, path=None, **kwargs):
        if self.no_picture:
            raise Gone("screenshot")
        Path(path).write_bytes(b"\x89PNG fake")

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
        if selector == MODEL_BUTTON:
            return ModelButton(self)
        if selector == MODEL_ITEM:
            return ModelItems(self)
        return Box(self, selector)

    def wait_for_timeout(self, ms):
        self.clock.now += ms / 1000.0


def send_on(page, composer):
    """(what happened, the turns the page sent) for one _send with the composer the open found."""
    scratch = Path(tempfile.mkdtemp(prefix="grok-composer-"))
    try:
        driver = grok.GrokProvider(scratch / "media", scratch / "sessions")
        driver.sent = False
        send_on.marked_sent = None
        try:
            driver._send(page, composer, PROMPT)
            return "sent", page.sent
        finally:
            # What the safe-retry rule reads: True only once the turn may have reached the provider.
            send_on.marked_sent = driver.sent
    except ProviderError as exc:
        return "refused: {}".format(str(exc)[:50]), page.sent
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def kept_after(page, act):
    """(what happened, the records kept, the pictures kept) for one call on a driver of its own, whose
    diagnostics folder is read before it is thrown away. `act` takes the driver."""
    scratch = Path(tempfile.mkdtemp(prefix="grok-kept-"))
    try:
        driver = grok.GrokProvider(scratch / "media", scratch / "sessions")
        driver._ensure_page = lambda: page
        try:
            act(driver)
            what = "no error"
        except ProviderError as exc:
            what = "{}: {}".format(exc.kind, str(exc)[:60])
        folder = scratch / "diagnostics"
        records = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("grok-*.json"))] \
            if folder.exists() else []
        pictures = [p.name for p in sorted(folder.glob("grok-*.png"))] if folder.exists() else []
        return what, records, pictures
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

    # 2026-11-16: the model the turn is sent with. Bot sends it into the account's one bot chat.
    page = ComposerPage(clock, model="Bot")
    what, sent = send_on(page, EDITORS[0])
    record("with Bot chosen, the driver chooses Auto and only then sends",
           what == "sent" and sent == [PROMPT] and page.sent_with == [WANTED],
           "{}, sent {} with {}".format(what, len(sent), page.sent_with))

    page = ComposerPage(clock, model=WANTED)
    what, sent = send_on(page, EDITORS[0])
    record("with Auto chosen already, the turn is sent and the menu is never opened",
           what == "sent" and page.sent_with == [WANTED] and page.menu_opened == 0,
           "{}, sent with {}, menu opened {} time(s)".format(what, page.sent_with, page.menu_opened))

    page = ComposerPage(clock, model=None)
    what, sent = send_on(page, EDITORS[0])
    record("a page with no model selector to read refuses the turn, nothing sent, not marked sent",
           what.startswith("refused") and sent == [] and send_on.marked_sent is False,
           "{}, sent {}, marked sent {}".format(what, sent, send_on.marked_sent))

    page = ComposerPage(clock, model="Bot", models=WITHOUT)
    what, sent = send_on(page, EDITORS[0])
    record("Bot chosen and no Auto in the menu: refused, nothing sent, the menu closed again",
           what.startswith("refused") and sent == [] and not page.menu_open,
           "{}, sent {}, menu open {}".format(what, sent, page.menu_open))

    page = ComposerPage(clock, model="Bot", choice_ignored=True)
    what, sent = send_on(page, EDITORS[0])
    record("a choice of Auto the page does not take refuses the turn, nothing sent, not marked sent",
           what.startswith("refused") and sent == [] and page.model == "Bot" and send_on.marked_sent is False,
           "{}, sent {}, the selector reads {}, marked sent {}".format(what, sent, page.model, send_on.marked_sent))

    # The review's doubt: a label that reads Auto when the guard looks and Bot by the time of Enter.
    page = ComposerPage(clock, model=WANTED, repaints_after=1)
    what, sent = send_on(page, EDITORS[0])
    record("a selector that turns to Bot after the guard's look refuses at the send: nothing sent, the box emptied",
           what.startswith("refused") and sent == [] and send_on.marked_sent is False
           and not page.text.get(EDITORS[0], ""),
           "{}, sent {}, marked sent {}, the box holds {!r}".format(
               what, sent, send_on.marked_sent, page.text.get(EDITORS[0], "")[:20]))

    page = ComposerPage(clock, model=WANTED)
    what, sent = send_on(page, EDITORS[0])
    record("a turn that goes out is marked sent",
           what == "sent" and send_on.marked_sent is True, "{}, marked sent {}".format(what, send_on.marked_sent))

    page = ComposerPage(clock, model=OTHER)
    what, sent = send_on(page, EDITORS[0])
    record("any model but Auto is changed to Auto before the send",
           what == "sent" and page.sent_with == [WANTED], "{}, sent with {}".format(what, page.sent_with))

    # 2026-11-16: jobs of 11-05, 11-08 and 11-10 failed as "grok did not open" and left nothing of
    # what the page showed; the cause (Cloudflare's check) was only seen by opening the page by hand.
    check = "grok.com\nPerforming security verification\nThis page is displayed while the website verifies you are not a bot."
    page = ComposerPage(clock, none=True, body=check)
    what, records, pictures = kept_after(page, lambda driver: driver._open())
    record("an open stuck behind the check fails as blocked and keeps the page's words and a picture",
           what.startswith("provider_blocked") and len(records) == 1 and len(pictures) == 1
           and "security verification" in (records[0].get("body_head") or "")
           and records[0].get("url") == "https://grok.com/" and "did not open" in (records[0].get("error") or ""),
           "{}, {} record(s) {}, {} picture(s)".format(what, len(records), sorted(records[0]) if records else [], len(pictures)))

    page = ComposerPage(clock, model=None)
    what, records, pictures = kept_after(page, lambda driver: driver._send(page, EDITORS[0], PROMPT))
    record("a send refused for the model keeps a record that says why, and a picture",
           what.startswith("provider_error") and page.sent == [] and len(records) == 1 and len(pictures) == 1
           and "model selector" in (records[0].get("error") or ""),
           "{}, sent {}, {} record(s), {} picture(s)".format(what, page.sent, len(records), len(pictures)))

    page = ComposerPage(clock, model=None, no_picture=True)
    what, records, pictures = kept_after(page, lambda driver: driver._send(page, EDITORS[0], PROMPT))
    record("a picture that cannot be taken changes nothing: the same refusal, the record still kept",
           what.startswith("provider_error: grok's model selector") and len(records) == 1 and pictures == [],
           "{}, {} record(s), {} picture(s)".format(what, len(records), len(pictures)))

    page = ComposerPage(clock)
    what, records, pictures = kept_after(page, lambda driver: driver._send(page, EDITORS[0], PROMPT))
    record("a turn that is sent keeps nothing",
           what == "no error" and page.sent == [PROMPT] and records == [] and pictures == [],
           "{}, {} record(s), {} picture(s)".format(what, len(records), len(pictures)))

    passed = sum(1 for ok in results if ok)
    print("{}/{} PASSED".format(passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
