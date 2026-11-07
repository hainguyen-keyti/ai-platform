#!/usr/bin/env python3
"""ChatGPT's composer, opening and sending, against a fake page. No browser, no turn.

    ~/cloakbrowser-env/bin/python tests/test_chatgpt_composer.py

Measured 2026-09-27: the page first
paints textarea#pending-home-input and mounts the real composer, a ProseMirror
div with no id, about ten seconds later; #prompt-textarea is gone; a failed first
turn leaves /c/local-chatgpt:<uuid> in the address. The driver used to call a
signed-in session "probably logged out" whenever the composer did not appear.
Measured 2026-10-01 in the owner's acceptance walk: a turn stopped 2.5s after Send ran on at
ChatGPT; the driver typed a turn its job had already lost and left a running reply unstopped.
Measured 2026-10-02: a real picture is on the page 22 seconds after the send, and the server never
closes that turn with an assistant node, so the driver waited out its whole ceiling for every one.
Measured 2026-10-28 (issue #10): ChatGPT now closes a picture turn with an empty answer, sometimes
at the picture's own second and before the page paints it, sometimes followed by a reasoning_recap
node, and names the picture's sandbox copy, which is the same file.
Prints N/N PASSED.
"""

import base64
import json
import re
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from src.providers import chatgpt  # noqa: E402
from src.providers.base import JobCancelled, ProviderError  # noqa: E402

REFERENCE_BYTES = b"\x89PNG not really"
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


class StopButton:
    """The site's stop button: there while a reply is being written, pressing it ends the reply.

    Measured 2026-11-07 on a new account: after a turn from the home page, the page keeps the home
    view as a second, zero-sized <main> holding a Stop button that never goes (`stale_stop`); only
    the visible one says a reply is being written."""

    def __init__(self, page, visible_only=False):
        self.page, self.visible_only = page, visible_only

    def filter(self, visible=None, **kwargs):
        return StopButton(self.page, visible_only=bool(visible))

    def count(self):
        if self.page.writing:
            return 1
        return 1 if self.page.stale_stop and not self.visible_only else 0

    @property
    def first(self):
        return self

    def is_visible(self):
        return self.page.writing

    def click(self, *args, **kwargs):
        if not self.page.writing:
            raise Missing("no stop button")
        self.page.stop_presses += 1
        self.page.writing = False


class Attachments:
    """The composer's file input: a picture set here rides along with the next turn sent."""

    def __init__(self, page):
        self.page = page

    @property
    def first(self):
        return self

    def set_input_files(self, path, *args, **kwargs):
        # Measured 2026-10-30 (issue #22): the first image input is `multiple: false`, which
        # Playwright refuses more than one file for.
        if isinstance(path, (list, tuple)):
            if len(path) > 1:
                raise Exception("Error: Non-multiple file input can only accept single file")
            path = path[0]
        self.page.attached.append(Path(path).name)


class ManyAttachments:
    """The image input that takes several files (`multiple: true`, measured 2026-10-30)."""

    def __init__(self, page):
        self.page = page

    @property
    def first(self):
        return self

    def set_input_files(self, paths, *args, **kwargs):
        paths = paths if isinstance(paths, (list, tuple)) else [paths]
        self.page.attached.extend(Path(p).name for p in paths)


class Removes:
    """The remove control beside each chip in the composer (measured 2026-10-22: a button labelled
    "Remove <file name>" inside the form). Measured the same day on the real page: a plain click
    takes nothing; hovered first (the preview or the control), the click takes its chip, unless the
    page refuses. On a page whose labels cannot be told apart (another interface language), none is
    found."""

    def __init__(self, page):
        self.page = page

    @property
    def first(self):
        return self

    def count(self):
        return len(self.page.attached) if self.page.labelled else 0

    def hover(self, *args, **kwargs):
        self.page.hovered = True

    def click(self, *args, **kwargs):
        if self.page.removable and self.page.hovered and self.page.attached:
            self.page.attached.pop(0)
            self.page.removed += 1
        self.page.hovered = False


class Previews:
    """Each chip's preview, an img with a data: source inside the form (measured 2026-10-22)."""

    def __init__(self, page):
        self.page = page

    @property
    def first(self):
        return self

    def count(self):
        return len(self.page.attached)

    def hover(self, *args, **kwargs):
        self.page.hovered = True


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
                self.page.sent_with.append(list(self.page.attached))
                # The site starts writing its reply the moment a turn is sent.
                self.page.writing = True
            self.page.text = ""
        elif key in ("ControlOrMeta+a", "Backspace"):
            # stuck: a composer that refuses to be cleared.
            if key == "Backspace" and not self.page.stuck:
                self.page.text = ""


class Page:
    stale_stop = False

    # composer_on_load: the composer mounts only from that load on (a slow first load).
    # token_after: how many session reads answer empty before the token (a fresh browser's first reads).
    def __init__(self, clock, has=(), token="token", url="https://chatgpt.com/", composer_on_load=None,
                 thread_status=None, screenshot_fails=False, token_after=0):
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
        self.token_after = token_after
        self.token_reads = 0
        self.deletions = []
        self.writing = False
        self.stop_presses = 0
        self.attached = []
        # Measured 2026-10-22 (tests/provider_probe.py attachment): a chip left in the composer is
        # gone at the next page load, and select-all plus Backspace does not take it. keeps_draft
        # plays a site that keeps the chip across a load; removable, whether its remove control works.
        self.keeps_draft = False
        self.removable = True
        self.labelled = True
        self.hovered = False
        self.removed = 0
        # What each sent turn carried along.
        self.sent_with = []

    goto_fails = ()

    def goto(self, url, *args, **kwargs):
        if self.goto_fails:
            raise self.goto_fails.pop(0)
        # Measured 2026-10-22 (the probe's second run): a chip attached on a thread's own page is
        # there again when that thread is loaded again (a per-conversation draft), and gone at any
        # other load (the home page, another thread, a home draft at a reload).
        same_thread = "/c/" in url and url == self.url
        self.url = url
        self.loads += 1
        if not self.keeps_draft and not same_thread:
            self.attached = []

    def reload(self, *args, **kwargs):
        self.loads += 1

    def screenshot(self, path=None, *args, **kwargs):
        if self.screenshot_fails:
            raise RuntimeError("the page could not be captured")
        self.pictures.append(path)

    def wait_for_timeout(self, ms):
        self.clock.now += ms / 1000.0

    def locator(self, selector):
        if selector == chatgpt.STOP_BUTTON:
            return StopButton(self)
        if selector == chatgpt.UPLOAD_INPUT:
            return Attachments(self)
        if selector == getattr(chatgpt, "UPLOAD_MANY", None):
            return ManyAttachments(self)
        if 'aria-label^="Remove' in selector:
            return Removes(self)
        if 'img[src^="data:"]' in selector:
            return Previews(self)
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
            self.token_reads += 1
            return self.token if self.token_reads > self.token_after else None
        if script == chatgpt.FETCH_THREAD and self.thread_status is not None:
            return {"status": self.thread_status}
        if script == chatgpt.DELETE_THREAD:
            self.deletions.append(args[0][0])
            return {"status": 200}
        # What a whole turn reads around its send: memory off, nothing on the page yet.
        if script == chatgpt.FETCH_USER_SETTINGS:
            return {"status": 200, "values": {key: False for key in chatgpt.MEMORY_KEYS}}
        if script in (chatgpt.SNAPSHOT_IMAGES, chatgpt.SNAPSHOT_DOWNLOADS,
                      chatgpt.COLLECT_CANDIDATE_IMAGES, chatgpt.ERROR_BANNER_PRESENT):
            return []
        return None

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class Words:
    """The page's assistant turns: one once the reply's words are painted, none before."""

    def __init__(self, text):
        self.text = text

    def count(self):
        return 1 if self.text else 0

    @property
    def last(self):
        return self

    def inner_text(self, *args, **kwargs):
        return self.text


class DrawingPage(Page):
    """A whole turn as the real page and server showed one on 2026-10-02
    (/tmp/picture_settle_probe.py): a picture is on the page and the stop button gone 22 seconds
    after the send, and the server's nodes for the turn are an assistant code node without end_turn
    and a finished tool node of multimodal_text, for good: no assistant node with end_turn comes.

    `tool_after`: seconds after the send when the tool's node lands and the stop button goes (None:
    the turn never gets there); `tool_kind`: what that node holds, a picture only when it is
    multimodal_text; `writes`: (from, to) when the stop button shows again; `words_after`: when
    an assistant text node with end_turn lands (None: never). With `threaded` the address is the
    thread's once the turn is sent; without, it never changes and only the page can be watched."""

    THREAD = "https://chatgpt.com/c/6abf0000-1111-83ec-9df4-aa8e1fc863a8"
    PICTURE = "blob:https://chatgpt.com/picture-1"
    PICTURE_DATA = "data:image/png;base64,iVBORw0KGgo="
    COPY = "/mnt/data/a_small_blue_square_1.png"
    # Measured 2026-10-30 (issue #24): the earlier turn's tool names its picture's sandbox copy, and a
    # turn that changes that picture names the same path again in its edit call, as the edit's input.
    EARLIER_COPY = "/mnt/data/ghostwriter_images/generated/an_earlier_picture_1.png"
    EARLIER_DATA = "data:image/png;base64,ZWFybGllcg=="
    WORDS = "Here it is."

    def __init__(self, clock, tool_after=None, tool_kind="multimodal_text", writes=None,
                 words_after=None, threaded=True, **more):
        self.tool_after, self.tool_kind, self.writes = tool_after, tool_kind, writes
        self.words_after, self.threaded, self.sent_at = words_after, threaded, None
        # finished_after: the tool's node is in progress until then (at tool_after unless said);
        # paints_after: the page shows the picture then (when its node is finished unless said);
        # second_after: a second picture's node lands then; words_from: the closing words' node is
        # there from then, in progress and half written, until words_after; idle_until: the stop
        # button does not show before then; earlier: the thread already holds a turn that drew (or
        # "words" that answered, or "late picture": one whose picture lands only after the first
        # read), and the address is the thread's from the start; first_read: what the first
        # `unreadable` reads of the thread answer (one unless said; "empty" is a 200 with no node);
        # `early_reads` counts the reads before the send and `read_at` keeps when each read came;
        # token_gone: once the thread has been read, the session gives no token; bounced: once the
        # thread has been read, the page is sent back to a new chat.
        self.finished_after = more.get("finished_after", tool_after)
        self.paints_after = more.get("paints_after", self.finished_after)
        self.second_after, self.words_from = more.get("second_after"), more.get("words_from")
        self.idle_until, self.earlier = more.get("idle_until", 0), more.get("earlier", False)
        self.first_read, self.reads, self.made_at = more.get("first_read", 200), 0, clock.now
        self.unreadable, self.early_reads, self.read_at = more.get("unreadable", 1), 0, []
        self.token_gone, self.bounced = more.get("token_gone", False), more.get("bounced", False)
        # Measured 2026-10-28: words_text, what the closing words' node says ("" for a picture turn
        # ChatGPT closes with an empty answer); recap_after, when an assistant reasoning_recap node
        # without end_turn lands, after the closing words; saved_copy, a tool node naming the
        # picture's sandbox copy at /mnt/data, which the server hands back byte for byte.
        self.words_text = more.get("words_text", self.WORDS)
        self.recap_after, self.saved_copy = more.get("recap_after"), more.get("saved_copy", False)
        self.memory_at, self.sandbox_reads = None, []
        # The account's file store, as measured 2026-10-30: 1.43 GB of 20 GB on Plus.
        self.usage = more.get("usage", {"status": 200, "used_bytes": 1428788369, "allowed_bytes": 21474836480,
                                        "remaining_bytes": 20046048111, "is_over_limit": False})
        self.usage_reads = 0
        super().__init__(clock, has={PROSEMIRROR})

    def since(self):
        return None if self.sent_at is None else self.clock.now - self.sent_at

    def reached(self, moment):
        return moment is not None and self.sent_at is not None and self.since() >= moment

    @property
    def writing(self):
        if self.sent_at is None or self.since() < self.idle_until:
            return False
        first = self.tool_after if self.tool_after is not None else self.words_after
        if first is None or self.since() < first:
            return True
        return bool(self.writes) and self.writes[0] <= self.since() < self.writes[1]

    @writing.setter
    def writing(self, value):
        if value and self.sent_at is None:
            self.sent_at = self.clock.now

    @property
    def url(self):
        if self.bounced and self.reads >= 1:
            return "https://chatgpt.com/"
        return self.THREAD if (self.threaded and self.sent_at is not None) or self.earlier else self._url

    @url.setter
    def url(self, value):
        self._url = value

    def locator(self, selector):
        if selector == chatgpt.ASSISTANT_TURN:
            return Words(self.words_text if self.reached(self.words_after) else "")
        return super().locator(selector)

    def nodes(self):
        done = "finished_successfully"

        def node(ident, role, kind, at, status=done, end_turn=None, text=""):
            return {"id": ident, "role": role, "status": status, "end_turn": end_turn,
                    "create_time": at, "content_type": kind, "text": text}

        nodes = []
        if self.earlier == "words":
            nodes += [node("u0", "user", "text", self.made_at - 100, text="an earlier prompt"),
                      node("a0", "assistant", "text", self.made_at - 99, end_turn=True,
                           text="An earlier answer.")]
        elif self.earlier == "late picture":
            nodes.append(node("u0", "user", "text", self.made_at - 100, text="an earlier prompt"))
            if self.reads >= 2:
                nodes += [node("a0", "assistant", "code", self.made_at - 99, end_turn=False, text="{}"),
                          node("t0", "tool", "multimodal_text", self.made_at - 98)]
        elif self.earlier == "edited picture":
            nodes += [node("u0", "user", "text", self.made_at - 100, text="an earlier prompt"),
                      node("a0", "assistant", "code", self.made_at - 99, end_turn=False, text="{}"),
                      node("t0", "tool", "multimodal_text", self.made_at - 98),
                      node("w0", "assistant", "text", self.made_at - 97, end_turn=True, text=""),
                      node("c0", "tool", "text", self.made_at - 97,
                           text="Generated images were saved at:\n- " + self.EARLIER_COPY)]
        elif self.earlier:
            nodes += [node("u0", "user", "text", self.made_at - 100, text="an earlier prompt"),
                      node("a0", "assistant", "code", self.made_at - 99, end_turn=False, text="{}"),
                      node("t0", "tool", "multimodal_text", self.made_at - 98)]
        if self.sent_at is None:
            return nodes
        nodes.append(node("u1", "user", "text", self.sent_at, text="a prompt"))
        if self.reached(self.tool_after):
            edit = ('{"image_paths": ["' + self.EARLIER_COPY + '"]}') if self.earlier == "edited picture" else "{}"
            if self.saved_copy == "inputs":
                edit = '{"referenced_image_ids": ["/mnt/data/one-reference.webp", "/mnt/data/another-reference.webp"]}'
            nodes += [node("a1", "assistant", "code", self.sent_at + self.tool_after - 1, end_turn=False, text=edit),
                      node("t1", "tool", self.tool_kind, self.sent_at + self.tool_after,
                           status=done if self.reached(self.finished_after) else "in_progress")]
        if self.reached(self.second_after):
            nodes.append(node("t2", "tool", self.tool_kind, self.sent_at + self.second_after))
        if self.reached(self.words_after):
            nodes.append(node("a2", "assistant", "text", self.sent_at + (self.words_from or self.words_after),
                              end_turn=True, text=self.words_text))
            if self.saved_copy:
                named = self.COPY + ("\n- " + self.COPY + ".again" if self.saved_copy == "twice" else "")
                nodes.append(node("t3", "tool", "text", self.sent_at + self.words_after,
                                  text="Generated images were saved at:\n- " + named))
        elif self.reached(self.words_from):
            nodes.append(node("a2", "assistant", "text", self.sent_at + self.words_from,
                              status="in_progress", text=self.WORDS[:4]))
        if self.reached(self.recap_after):
            nodes.append(node("a3", "assistant", "reasoning_recap", self.sent_at + self.recap_after,
                              end_turn=False))
        return nodes

    def evaluate(self, script, *args):
        if script == chatgpt.COLLECT_CANDIDATE_IMAGES:
            if self.tool_kind != "multimodal_text":
                return []
            return ([self.PICTURE] if self.reached(self.paints_after) else []) + (
                [self.PICTURE + "-2"] if self.reached(self.second_after) else [])
        if script == chatgpt.FETCH_AS_DATA_URL:
            return self.PICTURE_DATA
        if script == chatgpt.FETCH_INTERPRETER_FILE:
            self.sandbox_reads.append(args[0][2])
            if args[0][2] == self.EARLIER_COPY:
                return {"status": 200, "data": self.EARLIER_DATA, "name": self.EARLIER_COPY.rsplit("/", 1)[-1],
                        "mime": "image/png"}
            data = {"another": "data:image/png;base64,aW5mbw==", "twice": "data:image/png;base64,aW5mbw==",
                    "reference": "data:image/webp;base64," + base64.b64encode(REFERENCE_BYTES).decode()
                    }.get(self.saved_copy, self.PICTURE_DATA)
            return {"status": 200, "data": data, "name": self.COPY.rsplit("/", 1)[-1], "mime": "image/png"}
        if script == chatgpt.FETCH_THREAD:
            self.reads += 1
            self.read_at.append(self.clock.now)
            if self.sent_at is None:
                self.early_reads += 1
            if self.reads <= self.unreadable and self.first_read == "empty":
                return {"status": 200, "nodes": []}
            if self.reads <= self.unreadable and self.first_read != 200:
                return {"status": self.first_read, "nodes": []}
            return {"status": 200, "nodes": self.nodes()}
        if script == getattr(chatgpt, "FETCH_STORAGE_USAGE", None):
            # Measured 2026-10-30 (issue #23): GET /backend-api/files/library/storage/usage.
            self.usage_reads += 1
            if self.usage == "raise":
                raise Exception("Target page, context or browser has been closed")
            return self.usage if self.usage is not None else {"status": 500}
        if script == chatgpt.SESSION_TOKEN and self.token_gone and self.reads >= 1:
            return None
        if script == chatgpt.FETCH_USER_SETTINGS:
            self.memory_at = self.clock.now
        return super().evaluate(script, *args)


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

    # Measured 2026-10-30 and 31: after a long idle turns failed on the load itself, and the next were done.
    timed_out = TimeoutError("Page.goto: Timeout 90000ms exceeded.")
    no_name = RuntimeError("Page.goto: net::ERR_NAME_NOT_RESOLVED at https://chatgpt.com/")

    page = Page(clock, has={PROSEMIRROR})
    page.goto_fails = [timed_out]
    started = clock.now
    opened, said = open_on(page)
    record("a load that times out is tried once more", opened and page.loads == 1 and clock.now - started >= 20,
           "opened {} loads {} after {:.0f}s said {!r}".format(opened, page.loads, clock.now - started, said[:60]))

    page = Page(clock, has={PROSEMIRROR})
    page.goto_fails = [no_name]
    opened, said = open_on(page)
    record("a load that cannot resolve the name is tried once more", opened and page.loads == 1,
           "opened {} loads {} said {!r}".format(opened, page.loads, said[:60]))

    page = Page(clock, has={PROSEMIRROR})
    page.goto_fails = [timed_out, timed_out, timed_out]
    opened, said = open_on(page)
    record("a load that fails twice fails the turn, with no third try",
           not opened and "TimeoutError" in said and len(page.goto_fails) == 1,
           "said {!r}, {} left".format(said[:60], len(page.goto_fails)))

    page = Page(clock, has={PROSEMIRROR})
    page.goto_fails = [RuntimeError("Target page, context or browser has been closed"), timed_out]
    opened, said = open_on(page)
    record("a browser that is gone is not loaded again", not opened and "has been closed" in said
           and len(page.goto_fails) == 1, "said {!r}, {} left".format(said[:60], len(page.goto_fails)))

    page = Page(clock, has={PROSEMIRROR})
    page.goto_fails = [timed_out]
    driver = provider_on(page)
    driver.bind(None, lambda: True)
    try:
        driver._open()
        said = "opened"
    except JobCancelled:
        said = "cancelled"
    record("a job taken away while it waits to load again is not loaded", said == "cancelled" and page.loads == 0,
           "{} loads {}".format(said, page.loads))

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

    # Measured 2026-09-30: a fresh browser's first session read answered empty and the deletion said
    # logged out; the same session read a token 1.1s later.
    def delete_on(page):
        try:
            return provider_on(page).delete_thread(thread), ""
        except ProviderError as exc:
            return False, str(exc)
        except Exception as exc:
            return False, "{}: {}".format(type(exc).__name__, exc)

    wanted = thread.rsplit("/c/", 1)[-1]
    page = Page(clock, has=(), token="token", token_after=2)
    gone, said = delete_on(page)
    record("a thread deletion waits for a session read that answers late",
           gone is True and page.deletions == [wanted],
           "gone {} after {} reads, deletions {} said {!r}".format(gone, page.token_reads, len(page.deletions), said[:60]))

    page = Page(clock, has=(), token=None)
    gone, said = delete_on(page)
    record("a thread deletion with no session is still called logged out and sends nothing",
           not gone and "logged out" in said and page.deletions == [],
           "deletions {} said {!r}".format(len(page.deletions), said[:60]))

    # Measured 2026-10-31: four Cloudflare checks, and only the banner's words were kept of them.
    class Refused:
        def __init__(self, status, url, headers=None):
            self.status, self.url, self.headers = status, url, headers or {}
            self.request = type("Request", (), {"method": "POST"})

    class Checked(Page):
        banner, title_raises = "cloudflare_challengeRetry", False
        frames = [type("Frame", (), {"url": "https://challenges.cloudflare.com/x"}), type("Frame", (), {"url": "https://chatgpt.com/"})]

        def title(self):
            if self.title_raises:
                raise RuntimeError("the page went away")
            return "ChatGPT"

        def evaluate(self, script, *args):
            return [self.banner] if script == chatgpt.ERROR_BANNER_PRESENT else super().evaluate(script, *args)

    def banner_on(page):
        driver = provider_on(page)
        driver.media_path = driver.media_path / uuid.uuid4().hex / "media"
        driver._opened_at = clock.now - 90
        driver._note_response(Refused(200, "https://chatgpt.com/fine?secret=1"))
        driver._note_response(Refused(403, "https://chatgpt.com/backend-api/conversation?secret=1", {"cf-mitigated": "challenge"}))
        try:
            driver._fail_on_banner(page, [])
            said = "no error"
        except ProviderError as exc:
            said = str(exc)
        folder = driver.media_path.parent / "diagnostics"
        records = [json.loads(path.read_text()) for path in folder.glob("*.json")] if folder.exists() else []
        return said, records, page

    said, records, page = banner_on(Checked(clock, has={PROSEMIRROR}, url="https://chatgpt.com/c/1?x=1"))
    kept = records[0] if records else {}
    record("a Cloudflare check keeps a record and a picture, and still fails the turn with the banner's words",
           "cloudflare_challenge" in said and len(records) == 1 and len(page.pictures) == 1 and kept.get("account") == "chatgpt"
           and kept.get("browser_open_seconds") == 90 and kept.get("challenge_frames") == 1 and kept.get("url") == "https://chatgpt.com/c/1"
           and kept.get("title") == "ChatGPT", "{!r} {}".format(said[:50], kept))
    refused = kept.get("refused_responses") or []
    record("the record holds the site's refusals, with no query string", len(refused) == 1 and refused[0]["status"] == 403
           and refused[0]["cf_mitigated"] == "challenge" and "secret" not in json.dumps(kept), str(refused))

    other = Checked(clock, has={PROSEMIRROR})
    other.banner = "Something went wrong"
    said, records, page = banner_on(other)
    record("another banner keeps no such record", "Something went wrong" in said and records == [] and page.pictures == [], str(records))

    broken = Checked(clock, has={PROSEMIRROR}, screenshot_fails=True)
    broken.title_raises = True
    said, records, page = banner_on(broken)
    record("a page that cannot be read still fails the turn with the banner, and says what it could",
           "cloudflare_challenge" in said and len(records) == 1 and records[0].get("unread") == "RuntimeError", "{!r} {}".format(said[:50], records))

    # Measured 2026-11-01, job d6e42ca5: the api behind a check, the settings read among it, and the turn went out.
    class BehindCheck(DrawingPage):
        check_reads = 0

        def evaluate(self, script, *args):
            if script == chatgpt.FETCH_USER_SETTINGS and self.check_reads > 0:
                self.check_reads -= 1
                return {"status": 403, "values": {}}
            return super().evaluate(script, *args)

    def check_on(page):
        driver = provider_on(page)
        driver.media_path = driver.media_path / uuid.uuid4().hex / "media"
        driver.media_path.mkdir(parents=True)
        started = clock.now
        try:
            got = driver._run("vẽ một hình vuông")
            return "success" if got.success else "failed", clock.now - started, driver
        except ProviderError as exc:
            return str(exc), clock.now - started, driver

    page = BehindCheck(clock, tool_after=22, words_after=27, words_text="")
    page.check_reads = 3
    said, took, driver = check_on(page)
    record("a turn waits for the api to come out from behind a check before it sends",
           said == "success" and len(page.sent) == 1 and took >= 15, "{} sent {} after {:.0f}s".format(said, len(page.sent), took))

    page = BehindCheck(clock, tool_after=22, words_after=27, words_text="")
    page.check_reads = 8
    said, took, driver = check_on(page)
    record("a check that lasts has the page loaded again while it waits", said == "success" and page.loads >= 2 and len(page.sent) == 1,
           "{} loads {}".format(said, page.loads))

    page = BehindCheck(clock, tool_after=22, words_after=27, words_text="")
    page.check_reads = 10000
    said, took, driver = check_on(page)
    kept = list((driver.media_path.parent / "diagnostics").glob("*.json"))
    record("a check that stays fails the turn unsent, as a provider error, and leaves its record",
           "Cloudflare" in said and "nothing was sent" in said and page.sent == [] and len(kept) == 1 and took < 300,
           "{!r} sent {} records {} after {:.0f}s".format(said[:70], len(page.sent), len(kept), took))

    page = BehindCheck(clock, tool_after=22, words_after=27, words_text="")
    page.check_reads = 10000
    driver = provider_on(page)
    calls = []
    driver.bind(None, lambda: calls.append(1) or len(calls) > 1)
    try:
        driver._past_check(page, None)
        said = "returned"
    except JobCancelled:
        said = "cancelled"
    record("a job taken away during the wait is not sent", said == "cancelled" and page.sent == [], said)

    # Measured 2026-11-01, job 0e2d7cc4: the send itself refused, and the next turn went through.
    class RefusedSend(DrawingPage):
        driver, refuse, says_refused, shown = None, 1, True, False

        def goto(self, url, *args, **kwargs):
            self.shown = False
            return super().goto(url, *args, **kwargs)

        def evaluate(self, script, *args):
            sends = len(self.sent)
            if script == chatgpt.ERROR_BANNER_PRESENT and sends > self.seen_sends and self.refuse > 0:
                self.seen_sends, self.shown = sends, True
                self.refuse -= 1
                if self.says_refused:
                    self.driver._note_response(Refused(403, "https://chatgpt.com" + self.refused_path, {"cf-mitigated": "challenge"}))
            if script == chatgpt.ERROR_BANNER_PRESENT and self.shown:
                return ["cloudflare_challengeRetry"]
            return super().evaluate(script, *args)

        seen_sends, refused_path = 0, chatgpt.SEND_PATH

    def refused_on(earlier_refusal=False, **settings):
        page = RefusedSend(clock, tool_after=22, words_after=27, words_text="")
        for name, value in settings.items():
            setattr(page, name, value)
        driver = provider_on(page)
        page.driver = driver
        if earlier_refusal:
            driver._note_response(Refused(403, "https://chatgpt.com" + chatgpt.SEND_PATH, {"cf-mitigated": "challenge"}))
            clock.now += 1
        driver.media_path = driver.media_path / uuid.uuid4().hex / "media"
        driver.media_path.mkdir(parents=True)
        started = clock.now
        try:
            got = driver._run("vẽ một hình vuông")
            said = "success" if got.success else "failed"
        except ProviderError as exc:
            said = str(exc)
        return said, page, clock.now - started

    said, page, took = refused_on()
    record("a send Cloudflare refused is tried once more after a wait", said == "success" and len(page.sent) == 2 and took >= 60,
           "{} sent {} after {:.0f}s".format(said, len(page.sent), took))
    said, page, took = refused_on(refuse=5)
    record("a second refusal fails the turn, with no third send", "cloudflare_challenge" in said and len(page.sent) == 2,
           "{!r} sent {}".format(said[:60], len(page.sent)))
    said, page, took = refused_on(says_refused=False)
    record("a Cloudflare banner with no refused send on record is not sent again: the site may have taken it",
           "cloudflare_challenge" in said and len(page.sent) == 1, "{!r} sent {}".format(said[:60], len(page.sent)))
    said, page, took = refused_on(refused_path="/backend-api/f/conversation/prepare")
    record("a refused call other than the send itself does not send again",
           "cloudflare_challenge" in said and len(page.sent) == 1, "{!r} sent {}".format(said[:60], len(page.sent)))
    said, page, took = refused_on(earlier_refusal=True, says_refused=False)
    record("a send refused before this turn's own does not send it again",
           "cloudflare_challenge" in said and len(page.sent) == 1, "{!r} sent {}".format(said[:60], len(page.sent)))

    page = RefusedSend(clock, tool_after=22, words_after=27, words_text="")
    driver = provider_on(page)
    page.driver = driver
    driver.media_path = driver.media_path / uuid.uuid4().hex / "media"
    driver.media_path.mkdir(parents=True)
    driver.bind(None, lambda: len(page.sent) >= 1 and page.shown)
    try:
        driver._run("vẽ một hình vuông")
        said = "returned"
    except JobCancelled:
        said = "cancelled"
    except ProviderError as exc:
        said = str(exc)
    record("a job taken away during the wait is not sent again", said == "cancelled" and len(page.sent) == 1,
           "{!r} sent {}".format(said[:60], len(page.sent)))

    # Measured 2026-11-07, chatgpt-a3: a hidden Stop button left in the page's second <main> held every
    # reply wait to its 300s deadline although the answer was there at 19s.
    for threaded, way in ((True, "read from the server"), (False, "watched on the page")):
        page = DrawingPage(clock, words_after=27, words_text="pong", threaded=threaded)
        page.stale_stop = True
        started = clock.now
        got = provider_on(page).chat("Reply with exactly: pong", None, None)
        took = clock.now - started
        record("a hidden Stop button left on the page does not hold a reply {}".format(way),
               got.success and "pong" in (got.text or "") and took < 120,
               "success {} text {!r} after {:.0f}s: {!r}".format(got.success, (got.text or "")[:20], took, got.error))

    # Measured 2026-11-01: a Free account's answer once its pictures are spent.
    def limit_on(words):
        page = DrawingPage(clock, words_after=27, words_text=words)
        driver = provider_on(page)
        driver.media_path = driver.media_path / uuid.uuid4().hex / "media"
        driver.media_path.mkdir(parents=True)
        return driver.generate_image("a square")

    spent = ("You've hit the Free plan limit for image generations requests. You can create more images "
             "when the limit resets in 11 hours. I was not able to make it.")
    got = limit_on(spent)
    record("an account at its limit fails the turn as provider_limit, for as long as the site says",
           not got.success and got.error_kind == "provider_limit" and got.hold_seconds == 39600 and "Free plan limit" in got.error
           and got.thread_url, "{} {} {} {!r}".format(got.success, got.error_kind, got.hold_seconds, got.error))
    got = limit_on("You’ve hit your plan limit for images. Try later.")
    record("a limit that says no time holds for an hour", got.error_kind == "provider_limit" and got.hold_seconds == 3600,
           "{} {}".format(got.error_kind, got.hold_seconds))
    got = limit_on("I could not draw that: the speed limit sign is not clear.")
    record("other words without a picture are left to the api", got.success and got.error_kind is None and got.hold_seconds is None,
           "{} {}".format(got.success, got.error_kind))

    # Measured 2026-10-30: a fresh worker's first picture failed with "logged out" at the memory read
    # that opens the turn (job f9cb16ab); the next job, on the same session, was done.
    def memory_on(page):
        try:
            return provider_on(page)._read_memory(page), ""
        except chatgpt.ProviderError as exc:
            return None, str(exc)

    page = Page(clock, has=(), token="token", token_after=2)
    memory, said = memory_on(page)
    record("a turn's memory read waits for a session read that answers late",
           memory is not None and not said, "memory {} after {} reads said {!r}".format(memory, page.token_reads, said[:60]))

    page = Page(clock, has=(), token=None)
    memory, said = memory_on(page)
    record("a turn's memory read with no session is still called logged out",
           memory is None and "logged out" in said, "memory {} said {!r}".format(memory, said[:60]))

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

    # A whole turn whose job the api takes away. stop says when the driver hears of it.
    def run_on(page, stop, upload=None):
        driver = provider_on(page)
        driver.bind(None, stop)
        if upload:
            (driver.media_path / upload).write_bytes(b"a picture")
        try:
            driver._run("write a long essay about autumn in Hanoi", upload=upload)
            outcome = "returned"
        except JobCancelled:
            outcome = "cancelled"
        except Exception as exc:
            outcome = "{}: {}".format(type(exc).__name__, str(exc)[:60])
        return outcome, getattr(driver, "last_stop", None)

    page = Page(clock, has={PROSEMIRROR})
    outcome, stopped = run_on(page, lambda: True)
    record("a job stopped before its send types nothing and sends nothing",
           outcome == "cancelled" and page.sent == [] and page.enters == 0 and page.text == ""
           and (stopped or {}).get("sent") is False,
           "{}, sent {}, enters {}, typed {!r}, last_stop {}".format(
               outcome, len(page.sent), page.enters, page.text[:30], stopped))

    # A picture attached by a job already gone would sit in the shared composer for the next turn.
    page = Page(clock, has={PROSEMIRROR})
    outcome, stopped = run_on(page, lambda: True, upload="someone-elses-picture.png")
    record("a job stopped before its send attaches no picture either",
           outcome == "cancelled" and page.attached == [] and page.sent == []
           and (stopped or {}).get("sent") is False,
           "{}, attached {}, sent {}, last_stop {}".format(outcome, page.attached, len(page.sent), stopped))

    page = Page(clock, has={PROSEMIRROR})
    outcome, stopped = run_on(page, lambda: bool(page.sent))
    record("a job stopped while its reply runs presses the site's stop button",
           outcome == "cancelled" and len(page.sent) == 1 and page.stop_presses == 1 and not page.writing
           and (stopped or {}).get("pressed") is True,
           "{}, sent {}, stop pressed {} times, still writing {}, last_stop {}".format(
               outcome, len(page.sent), page.stop_presses, page.writing, stopped))

    # The real gate of 2026-10-02 lost a picture to the clock ("returned nothing after 302s"), and
    # every real picture took the ceiling and a little. Measured the same day: the picture is on the
    # page 22 seconds after the send and the server never closes the turn with an assistant node.
    def draw_on(page, thread_url=None, upload=None, stored=None):
        driver = provider_on(page)
        # A media store of its own: what a turn's files are compared with is what the store already holds.
        driver.media_path = driver.media_path / uuid.uuid4().hex
        driver.media_path.mkdir(parents=True, exist_ok=True)
        if upload:
            (driver.media_path / upload).write_bytes(REFERENCE_BYTES)
        if stored:
            (driver.media_path / "an-earlier-turns-reference.webp").write_bytes(stored)
        started = clock.now
        try:
            got = driver._run("vẽ cho tôi một hình vuông màu xanh", thread_url=thread_url, upload=upload)
            said = "success" if got.success else "failed as {}".format(got.error_kind)
            return said, len(got.media), got.text, clock.now - started
        except Exception as exc:
            return "{}: {}".format(type(exc).__name__, str(exc)[:60]), 0, "", clock.now - started

    said, pictures, text, took = draw_on(DrawingPage(clock, tool_after=22))
    record("a picture turn the server never closes is collected soon after the picture shows",
           said == "success" and pictures == 1 and took < 60,
           "{} with {} picture(s) after {:.0f}s".format(said, pictures, took))

    # The image API sends a person's own picture with their prompt (2026-10-09): it must ride along with
    # the turn, and the words must be theirs, not a guess that the picture shows a character.
    def draw_with(reference):
        page = DrawingPage(clock, tool_after=22)
        driver = provider_on(page)
        driver.media_path.mkdir(parents=True, exist_ok=True)
        for name in ([reference] if isinstance(reference, str) else reference or []):
            if "missing" not in name:
                (driver.media_path / name).write_bytes(b"\x89PNG not really")
        got = driver.generate_image("đổi nền thành bãi biển lúc hoàng hôn", reference_filename=reference)
        return got, page

    # Issue #23: after a picture turn the driver reads the account's file store, at most every ten minutes,
    # and warns from 80% or over the limit; a failed read never fails the turn.
    def usage_after(**usage):
        page = DrawingPage(clock, tool_after=22, usage=usage or None)
        driver = provider_on(page)
        driver.media_path.mkdir(parents=True, exist_ok=True)
        got = driver.generate_image("a blue square")
        return got, driver, page

    got, driver, page = usage_after(status=200, used_bytes=1428788369, allowed_bytes=21474836480,
                                    remaining_bytes=20046048111, is_over_limit=False)
    stored = getattr(driver, "storage", None) or {}
    record("after a picture turn the account's file store is read: 1.43 of 20 GB, no warning",
           got.success and page.usage_reads == 1 and stored.get("used_bytes") == 1428788369
           and stored.get("allowed_bytes") == 21474836480 and stored.get("used_share") == 0.067
           and stored.get("warning") is False,
           "success {}, reads {}, storage {}".format(got.success, page.usage_reads, stored))
    first_read = page.usage_reads
    got_again = driver.generate_image("a red square")
    clock.now += 601
    driver.generate_image("a green square")
    record("the store is read at most every ten minutes",
           got_again.success and first_read == 1 and page.usage_reads == 2,
           "reads after the first turn {}, after a second at once and a third ten minutes on: {}".format(
               first_read, page.usage_reads))
    got, driver, page = usage_after(status=200, used_bytes=17 * 2 ** 30, allowed_bytes=20 * 2 ** 30,
                                    remaining_bytes=3 * 2 ** 30, is_over_limit=False)
    record("a store 85% full warns", (getattr(driver, "storage", None) or {}).get("warning") is True,
           repr(getattr(driver, "storage", None)))
    got, driver, page = usage_after(status=200, used_bytes=10, allowed_bytes=20 * 2 ** 30,
                                    remaining_bytes=20 * 2 ** 30, is_over_limit=True)
    record("a store over its limit warns, whatever its share", (getattr(driver, "storage", None) or {}).get("warning") is True,
           repr(getattr(driver, "storage", None)))
    page = DrawingPage(clock, tool_after=22)
    page.usage = {"status": 401}
    driver = provider_on(page)
    got = driver.generate_image("a blue square")
    record("a store that cannot be read leaves the turn as it was and says why",
           got.success and len(got.media) == 1 and (getattr(driver, "storage", None) or {}).get("error") == 401,
           "success {}, storage {}".format(got.success, getattr(driver, "storage", None)))
    page = DrawingPage(clock, tool_after=22)
    page.usage = "raise"
    driver = provider_on(page)
    try:
        got = driver.generate_image("a blue square")
        outcome = "success {} with {} picture(s)".format(got.success, len(got.media))
    except Exception as exc:
        got, outcome = None, "raised {}".format(exc)
    record("a page that dies while the store is read still returns the picture made",
           got is not None and got.success and len(got.media) == 1
           and "closed" in str((getattr(driver, "storage", None) or {}).get("error")),
           "{}, storage {}".format(outcome, getattr(driver, "storage", None)))

    # Issue #22: several reference pictures go out together through the input that takes several.
    many = ["upload-1111aaaa.png", "upload-2222bbbb.png", "upload-3333cccc.png"]
    got, page = draw_with(many)
    record("a picture turn with several pictures attaches every one, in order, and names them as references",
           got.success and page.attached == many and len(page.sent) == 1 and page.sent_with == [many]
           and "đổi nền thành bãi biển lúc hoàng hôn" in page.sent[0] and "images" in page.sent[0].lower(),
           "success {} ({}), attached {}, sent {}".format(got.success, got.error, page.attached, page.sent))
    got, page = draw_with(["upload-1111aaaa.png", "upload-missing.png"])
    record("a picture turn whose second picture is missing fails before anything is attached or sent",
           not got.success and "upload-missing.png" in (got.error or "") and page.attached == [] and page.sent == [],
           "success {} error {!r}, attached {}, sent {}".format(got.success, got.error, page.attached, page.sent))

    got, page = draw_with("upload-0123abcd.png")
    record("a picture turn with a person's picture attaches it and sends their prompt, not a character guess",
           got.success and len(got.media) == 1 and page.attached == ["upload-0123abcd.png"]
           and len(page.sent) == 1 and "đổi nền thành bãi biển lúc hoàng hôn" in page.sent[0]
           and "character" not in page.sent[0].lower(),
           "success {}, pictures {}, attached {}, sent {}".format(
               got.success, len(got.media), page.attached, page.sent))
    got, page = draw_with(None)
    record("a picture turn without one attaches nothing and asks for the picture in the prompt's words",
           got.success and page.attached == []
           and page.sent == ["Generate an image: đổi nền thành bãi biển lúc hoàng hôn"],
           "success {}, attached {}, sent {}".format(got.success, page.attached, page.sent))

    # The safety plan, 2026-10-21. On the real page (2026-10-22) a chip never survives the load
    # _open makes, so a turn taken away after its attach leaves nothing for the next turn; the
    # driver still looks before it sends, for a site that keeps a draft, and refuses one it cannot
    # clear: a chip of another turn must never ride along.
    page = DrawingPage(clock, tool_after=22)
    page.keeps_draft, page.attached = True, ["another-persons-picture.png"]
    said, pictures, _, _ = draw_on(page)
    record("a chip a site keeps across the open is removed before the turn is sent",
           said == "success" and page.sent_with == [[]] and page.attached == [],
           "{}, sent with {}, left {}".format(said, page.sent_with, page.attached))

    page = DrawingPage(clock, tool_after=22)
    page.keeps_draft, page.removable, page.attached = True, False, ["another-persons-picture.png"]
    said, pictures, _, _ = draw_on(page)
    record("a chip that cannot be removed refuses the turn unsent",
           said.startswith("ProviderError") and page.sent == [] and page.text == "",
           "{}, sent {}, typed {!r}".format(said, len(page.sent), page.text[:30]))

    # The tier 1 review (2026-10-22): the remove control is known by its English label; a preview
    # with no control the driver can tell apart must refuse the turn, never send it along.
    page = DrawingPage(clock, tool_after=22)
    page.keeps_draft, page.labelled, page.attached = True, False, ["another-persons-picture.png"]
    said, pictures, _, _ = draw_on(page)
    record("a chip whose remove control cannot be told apart refuses the turn unsent",
           said.startswith("ProviderError") and page.sent == [] and page.text == "",
           "{}, sent {}, typed {!r}".format(said, len(page.sent), page.text[:30]))

    page = DrawingPage(clock, tool_after=22)
    outcome, stopped = run_on(page, lambda: bool(page.attached), upload="someone-elses-picture.png")
    left = list(page.attached)
    said, pictures, _, _ = draw_on(page)
    record("as the site is, a chip left by a turn taken away after its attach is gone at the next open",
           outcome == "cancelled" and left == ["someone-elses-picture.png"]
           and (stopped or {}).get("sent") is False and said == "success" and page.sent_with == [[]],
           "{} with {} left, then {} sent with {}".format(outcome, left, said, page.sent_with))

    said, pictures, text, took = draw_on(DrawingPage(clock, tool_after=22, threaded=False))
    record("so is one that can only be watched on the page",
           said == "success" and pictures == 1 and took < 90,
           "{} with {} picture(s) after {:.0f}s".format(said, pictures, took))

    said, pictures, text, took = draw_on(DrawingPage(clock, tool_after=22, writes=(26, 40), words_after=40))
    record("a turn that draws and then writes is not cut at its picture",
           said == "success" and pictures == 1 and text == DrawingPage.WORDS and took >= 40,
           "{} with {} picture(s), words {!r}, after {:.0f}s".format(said, pictures, text, took))

    said, pictures, text, took = draw_on(DrawingPage(clock, tool_after=22, tool_kind="execution_output",
                                                     words_after=60))
    record("a finished tool node that is not a picture ends nothing",
           said == "success" and pictures == 0 and text == DrawingPage.WORDS and took >= 60,
           "{} with {} picture(s), words {!r}, after {:.0f}s".format(said, pictures, text, took))

    said, pictures, text, took = draw_on(DrawingPage(clock, tool_after=22, writes=(26, 40), second_after=45))
    record("work that resumes restarts the quiet time: a second picture landing after it is collected too",
           said == "success" and pictures == 2 and took >= 55,
           "{} with {} picture(s) after {:.0f}s".format(said, pictures, took))

    said, pictures, text, took = draw_on(DrawingPage(clock, tool_after=22, finished_after=50))
    record("a tool node still in progress is not a finished picture",
           said == "success" and pictures == 1 and took >= 60,
           "{} with {} picture(s) after {:.0f}s".format(said, pictures, took))

    # The tier 2 review, 2026-10-02. The picture's node can be there before the page has painted it.
    said, pictures, text, took = draw_on(DrawingPage(clock, tool_after=22, paints_after=45))
    record("a picture whose node is there before the page paints it is waited for",
           said == "success" and pictures == 1 and took >= 45,
           "{} with {} picture(s) after {:.0f}s".format(said, pictures, took))

    # The newest node is what counts: words that start after the picture, with no stop button shown.
    said, pictures, text, took = draw_on(DrawingPage(clock, tool_after=22, words_from=30, words_after=50))
    record("words that start after the picture, with no stop button, are not cut",
           said == "success" and pictures == 1 and text == DrawingPage.WORDS and took >= 50,
           "{} with {} picture(s), words {!r}, after {:.0f}s".format(said, pictures, text, took))

    # Measured 2026-10-28 (issue #10): the picture at +48s, an empty closing answer at +53s and a
    # reasoning_recap without end_turn at +55s; the driver ran to its ceiling (5m24s). The page
    # works until the recap is written, so the server is read only once the recap is the newest.
    said, pictures, text, took = draw_on(DrawingPage(clock, tool_after=48, writes=(48, 57), words_after=53,
                                                     words_text="", recap_after=55))
    record("a reasoning recap after the closing answer does not hide that the turn is over",
           said == "success" and pictures == 1 and took < 90,
           "{} with {} picture(s) after {:.0f}s".format(said, pictures, took))

    # The same day, a second turn: the picture's node and an empty closing answer at +35s, the page
    # still painting; the driver collected nothing and failed the turn as returning nothing.
    said, pictures, text, took = draw_on(DrawingPage(clock, tool_after=35, words_after=35, words_text="",
                                                     paints_after=45))
    record("a turn closed by its answer at the picture's second waits for the picture to paint",
           said == "success" and pictures == 1 and took >= 45,
           "{} with {} picture(s) after {:.0f}s".format(said, pictures, took))

    # The first turn's two pictures were one file, the page's and its sandbox copy.
    page = DrawingPage(clock, tool_after=22, words_after=27, words_text="", saved_copy=True)
    said, pictures, text, took = draw_on(page)
    record("a picture's sandbox copy, byte for byte the page's, is stored once",
           said == "success" and pictures == 1 and page.sandbox_reads == [DrawingPage.COPY],
           "{} with {} picture(s), sandbox reads {}".format(said, pictures, page.sandbox_reads))

    page = DrawingPage(clock, tool_after=22, words_after=27, words_text="", saved_copy="another")
    said, pictures, text, took = draw_on(page)
    record("a sandbox file that is not the page's picture is still stored",
           said == "success" and pictures == 2,
           "{} with {} file(s)".format(said, pictures))

    # Measured 2026-10-30: in a thread of one key, a turn named the reference pictures of its thread by
    # sandbox names of their own; 30 came back as pictures, and a turn that drew nothing was called done.
    page = DrawingPage(clock, words_after=27, words_text="", saved_copy="reference")
    said, pictures, text, took = draw_on(page, upload="reference.webp")
    record("a turn that only names its own reference picture made nothing and fails",
           said == "failed as provider_timeout" and pictures == 0,
           "{} with {} file(s)".format(said, pictures))

    page = DrawingPage(clock, tool_after=22, words_after=27, words_text="", saved_copy="another")
    said, pictures, text, took = draw_on(page, stored=b"info")
    record("a reference picture of an earlier turn, already in the store, is not this turn's picture",
           said == "success" and pictures == 1, "{} with {} file(s)".format(said, pictures))

    page = DrawingPage(clock, tool_after=22, words_after=27, words_text="", saved_copy="inputs")
    said, pictures, text, took = draw_on(page)
    record("a drawing turn does not fetch the reference pictures its image call names as input",
           said == "success" and pictures == 1 and page.sandbox_reads == [DrawingPage.COPY],
           "{} with {} picture(s), sandbox reads {}".format(said, pictures, page.sandbox_reads))

    page = DrawingPage(clock, tool_after=22, words_after=27, words_text="", saved_copy="twice")
    said, pictures, text, took = draw_on(page)
    record("one new file named by two sandbox paths is stored once",
           said == "success" and pictures == 2 and len(page.sandbox_reads) == 2,
           "{} with {} file(s), {} reads".format(said, pictures, len(page.sandbox_reads)))

    # Measured 2026-10-30 (issue #24): a turn changing the earlier picture named that picture's sandbox
    # file as its edit's input, and the driver fetched it as this turn's: two pictures, one the earlier.
    page = DrawingPage(clock, tool_after=22, words_after=27, words_text="", saved_copy=True,
                       earlier="edited picture")
    said, pictures, text, took = draw_on(page, thread_url=DrawingPage.THREAD)
    record("a turn that changes an earlier picture does not return that picture again",
           said == "success" and pictures == 1 and DrawingPage.EARLIER_COPY not in page.sandbox_reads,
           "{} with {} picture(s), sandbox reads {}".format(said, pictures, page.sandbox_reads))

    page = DrawingPage(clock, tool_after=22, words_after=27, words_text="", saved_copy="another",
                       earlier="edited picture")
    said, pictures, text, took = draw_on(page, thread_url=DrawingPage.THREAD)
    record("a file only this follow-up names is still stored",
           said == "success" and pictures == 2 and page.sandbox_reads == [DrawingPage.COPY],
           "{} with {} file(s), sandbox reads {}".format(said, pictures, page.sandbox_reads))

    # A picture from an earlier turn of the thread never ends this one, whether or not the read
    # of the thread before the send went through.
    for label, first_read in (("", 200), (" even when the thread could not be read before the send", 429)):
        page = DrawingPage(clock, words_after=40, earlier=True, idle_until=25, first_read=first_read)
        said, pictures, text, took = draw_on(page, thread_url=DrawingPage.THREAD)
        record("an earlier turn's picture does not end this turn" + label,
               said == "success" and text.endswith(DrawingPage.WORDS) and took >= 40,
               "{} with words {!r} after {:.0f}s".format(said, text[-30:], took))

    page = DrawingPage(clock, words_after=40, earlier="words", idle_until=25)
    said, pictures, text, took = draw_on(page, thread_url=DrawingPage.THREAD)
    record("an earlier turn's answer is not this turn's",
           said == "success" and text == DrawingPage.WORDS and took >= 40,
           "{} with words {!r} after {:.0f}s".format(said, text, took))

    # The picture plan's review, 2026-10-02, reproduced 2026-10-06: when the read of the thread before
    # the send failed, every earlier node counted as this turn's, and an earlier answer, finished with
    # end_turn, came back at once as this turn's (after 9s, charged).
    for status in (429, 500):
        page = DrawingPage(clock, words_after=40, earlier="words", idle_until=25, first_read=status)
        said, pictures, text, took = draw_on(page, thread_url=DrawingPage.THREAD)
        record("an earlier answer is never this turn's when the read before the send first answers {}".format(
                   status),
               said == "success" and text == DrawingPage.WORDS and took >= 40,
               "{} with words {!r} after {:.0f}s".format(said, text, took))

    page = DrawingPage(clock, words_after=40, earlier="words", idle_until=25, first_read=500, unreadable=100)
    said, pictures, text, took = draw_on(page, thread_url=DrawingPage.THREAD, upload="unread-reference.png")
    record("a thread that stays unreadable before the send fails the turn soon, nothing typed or attached",
           said.startswith("ProviderError") and page.sent == [] and page.attached == [] and took < 30,
           "{} after {:.0f}s, sent {} attached {}".format(said, took, len(page.sent), page.attached))

    # A job taken away while its thread is read again before the send stops there: nothing goes out,
    # and the driver's stop record says the turn was never sent (what the gate accounts it by).
    page = DrawingPage(clock, words_after=40, earlier="words", idle_until=25, first_read=500, unreadable=100)
    driver = provider_on(page)
    driver.bind(None, lambda: page.reads >= 1)
    started = clock.now
    try:
        driver._run("hỏi tiếp một câu", thread_url=DrawingPage.THREAD)
        outcome = "returned"
    except JobCancelled:
        outcome = "cancelled"
    except Exception as exc:
        outcome = "{}: {}".format(type(exc).__name__, str(exc)[:60])
    took, stopped = clock.now - started, getattr(driver, "last_stop", None)
    record("a job taken away while its thread is read again before the send stops after one pause, unsent, and says so",
           outcome == "cancelled" and page.sent == [] and (stopped or {}).get("sent") is False and took < 10,
           "{} after {:.0f}s, sent {}, last_stop {}".format(outcome, took, len(page.sent), stopped))

    # The tier 2 review of the read before the send, 2026-10-07: its mutants of the pauses, of a read
    # with no token, of a 200 with no node, of the clock guard and of a page that left its thread
    # went through every check above.
    def follow_up(page, stop=None, upload=None):
        """(outcome, result, driver, seconds) of a follow-up turn in the fake thread."""
        driver = provider_on(page)
        driver.media_path.mkdir(parents=True, exist_ok=True)
        driver.bind(None, stop)
        started = clock.now
        try:
            got = driver._run("hỏi tiếp một câu", thread_url=DrawingPage.THREAD, upload=upload)
            return "returned", got, driver, clock.now - started
        except JobCancelled:
            return "cancelled", None, driver, clock.now - started
        except Exception as exc:
            return "{}: {}".format(type(exc).__name__, str(exc)[:70]), None, driver, clock.now - started

    page = DrawingPage(clock, words_after=40, earlier="words", idle_until=25, first_read=500, unreadable=2)
    outcome, result, driver, took = follow_up(page)
    gaps = [round(b - a, 1) for a, b in zip(page.read_at[:2], page.read_at[1:3])]
    first_wait = None if page.memory_at is None or not page.read_at else round(page.read_at[0] - page.memory_at, 1)
    record("the read before the send is tried at once, then again after 6s and after 12s",
           outcome == "returned" and result.success and result.text == DrawingPage.WORDS
           and first_wait is not None and first_wait < 1 and gaps[:1] and gaps[0] >= 6
           and len(gaps) == 2 and gaps[1] >= 12,
           "{} first read {}s after the memory read, then gaps {}".format(outcome, first_wait, gaps))

    page = DrawingPage(clock, words_after=40, earlier="words", idle_until=25, first_read=401, token_gone=True)
    outcome, result, driver, took = follow_up(page)
    record("a follow-up whose session token is lost before the send is refused, nothing sent",
           outcome.startswith("ProviderError") and page.sent == [],
           "{} after {:.0f}s, sent {}".format(outcome, took, len(page.sent)))

    page = DrawingPage(clock, words_after=40, earlier="words", idle_until=25, first_read="empty")
    outcome, result, driver, took = follow_up(page)
    record("a read before the send that answers 200 with no node is tried again",
           outcome == "returned" and result.success and result.text == DrawingPage.WORDS,
           "{} with words {!r}".format(outcome, result and result.text))

    page = DrawingPage(clock, words_after=40, earlier="words", idle_until=25, first_read=500, unreadable=100)
    outcome, result, driver, took = follow_up(page, stop=lambda: page.reads >= 3)
    stopped = getattr(driver, "last_stop", None)
    record("a job taken away during the last read before the send stops unsent, and says so",
           outcome == "cancelled" and page.sent == [] and (stopped or {}).get("sent") is False,
           "{}, sent {}, last_stop {}".format(outcome, len(page.sent), stopped))

    # Measured 2026-10-22: a chip attached on the thread's own page is there again at that thread's
    # next open. A follow-up with a picture taken away after its attach leaves it; the next turn in
    # the same conversation finds it and removes it before it sends.
    page = DrawingPage(clock, words_after=40, earlier="words", idle_until=25)
    media = provider_on(page).media_path
    media.mkdir(parents=True, exist_ok=True)
    (media / "left-behind.png").write_bytes(b"a picture")
    outcome, result, driver, took = follow_up(page, stop=lambda: bool(page.attached), upload="left-behind.png")
    left, stopped = list(page.attached), getattr(driver, "last_stop", None)
    outcome2, result2, driver, took = follow_up(page)
    record("a chip left on a thread's page by a turn taken away after its attach is removed at the next turn",
           outcome == "cancelled" and left == ["left-behind.png"] and (stopped or {}).get("sent") is False
           and outcome2 == "returned" and result2.success and page.removed == 1 and page.sent_with == [[]],
           "{} with {} left, then {} removed {} sent with {}".format(outcome, left, outcome2, page.removed,
                                                                      page.sent_with))

    page = DrawingPage(clock, words_after=40, earlier="words", idle_until=25, first_read=500, unreadable=100)
    outcome, result, driver, took = follow_up(page, upload="never-written.png")
    record("a missing reference picture is said as such, before the thread is read",
           outcome == "returned" and not result.success and "not found" in (result.error or "")
           and page.reads == 0, "{} {!r}, reads {}".format(outcome, result and result.error, page.reads))

    page = DrawingPage(clock, words_after=40, earlier="late picture", idle_until=25)
    said, pictures, text, took = draw_on(page, thread_url=DrawingPage.THREAD)
    record("an earlier turn's picture that lands after the read before the send does not end this turn",
           said == "success" and text == DrawingPage.WORDS and took >= 40,
           "{} with words {!r} after {:.0f}s".format(said, text, took))

    page = DrawingPage(clock, words_after=40, earlier="words", idle_until=25, bounced=True)
    outcome, result, driver, took = follow_up(page)
    record("a follow-up whose page leaves its thread before the send is refused, nothing sent",
           outcome.startswith("ProviderError") and page.sent == [],
           "{}, sent {}".format(outcome, len(page.sent)))

    page = DrawingPage(clock, words_after=8)
    said, pictures, text, took = draw_on(page)
    record("a first turn, which has no thread yet, is sent without reading one",
           said == "success" and text == DrawingPage.WORDS and page.early_reads == 0,
           "{} with words {!r}, reads before the send {}".format(said, text, page.early_reads))

    said, pictures, text, took = draw_on(DrawingPage(clock))
    record("a turn that never ends gives up at the ceiling, as a timeout",
           said == "failed as provider_timeout" and pictures == 0 and 300 <= took <= 320,
           "{} after {:.0f}s".format(said, took))

    said, pictures, text, took = draw_on(DrawingPage(clock, threaded=False))
    record("so does one that can only be watched on the page",
           said == "failed as provider_timeout" and pictures == 0 and 330 <= took <= 350,
           "{} after {:.0f}s".format(said, took))

    said, pictures, text, took = draw_on(DrawingPage(clock, words_after=8))
    record("a short answer still returns as soon as it settles",
           said == "success" and text == DrawingPage.WORDS and took < 30,
           "{} with words {!r} after {:.0f}s".format(said, text, took))

    # Whoever waits for a real turn must outwait the driver, or reports a timeout of its own making.
    gate = int(re.search(r"job_timeout = (\d+) if real", (ROOT / "acceptance.py").read_text()).group(1))
    journey = int(re.search(r"^TURN_TIMEOUT_MS = (\d+)", (ROOT / "tests" / "ui_journey.py").read_text(),
                            re.M).group(1)) / 1000
    record("the gate and the journey wait longer than the driver's ceiling and a browser's first open",
           min(gate, journey) >= chatgpt.REPLY_TIMEOUT + 90,
           "the driver {}s, the gate {}s, the journey {:.0f}s".format(chatgpt.REPLY_TIMEOUT, gate, journey))

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
