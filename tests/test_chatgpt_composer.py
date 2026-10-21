#!/usr/bin/env python3
"""ChatGPT's composer, opening and sending, against a fake page. No browser, no turn.

    ~/cloakbrowser-env/bin/python tests/test_chatgpt_composer.py

Measured 2026-09-27 (docs/research/2026-09-27-chatgpt-composer.md): the page first
paints textarea#pending-home-input and mounts the real composer, a ProseMirror
div with no id, about ten seconds later; #prompt-textarea is gone; a failed first
turn leaves /c/local-chatgpt:<uuid> in the address. The driver used to call a
signed-in session "probably logged out" whenever the composer did not appear.
Measured 2026-10-01 in the owner's acceptance walk: a turn stopped 2.5s after Send ran on at
ChatGPT; the driver typed a turn its job had already lost and left a running reply unstopped.
Measured 2026-10-02: a real picture is on the page 22 seconds after the send, and the server never
closes that turn with an assistant node, so the driver waited out its whole ceiling for every one.
Prints N/37 PASSED.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from src.providers import chatgpt  # noqa: E402
from src.providers.base import JobCancelled, ProviderError  # noqa: E402

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
    """The site's stop button: there while a reply is being written, pressing it ends the reply."""

    def __init__(self, page):
        self.page = page

    def count(self):
        return 1 if self.page.writing else 0

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
        self.page.attached.append(Path(path).name)


class Removes:
    """The remove control beside each chip in the composer (measured 2026-10-22: a button labelled
    "Remove <file name>" inside the form): pressed, it takes its chip away, unless the page refuses.
    On a page whose labels cannot be told apart (another interface language), none is found."""

    def __init__(self, page):
        self.page = page

    @property
    def first(self):
        return self

    def count(self):
        return len(self.page.attached) if self.page.labelled else 0

    def click(self, *args, **kwargs):
        if self.page.removable and self.page.attached:
            self.page.attached.pop(0)


class Previews:
    """Each chip's preview, an img with a data: source inside the form (measured 2026-10-22)."""

    def __init__(self, page):
        self.page = page

    def count(self):
        return len(self.page.attached)


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
        # What each sent turn carried along.
        self.sent_with = []

    def goto(self, url, *args, **kwargs):
        self.url = url
        self.loads += 1
        if not self.keeps_draft:
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
        self.memory_at = None
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
            return Words(self.WORDS if self.reached(self.words_after) else "")
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
        elif self.earlier:
            nodes += [node("u0", "user", "text", self.made_at - 100, text="an earlier prompt"),
                      node("a0", "assistant", "code", self.made_at - 99, end_turn=False, text="{}"),
                      node("t0", "tool", "multimodal_text", self.made_at - 98)]
        if self.sent_at is None:
            return nodes
        nodes.append(node("u1", "user", "text", self.sent_at, text="a prompt"))
        if self.reached(self.tool_after):
            nodes += [node("a1", "assistant", "code", self.sent_at + self.tool_after - 1, end_turn=False, text="{}"),
                      node("t1", "tool", self.tool_kind, self.sent_at + self.tool_after,
                           status=done if self.reached(self.finished_after) else "in_progress")]
        if self.reached(self.second_after):
            nodes.append(node("t2", "tool", self.tool_kind, self.sent_at + self.second_after))
        if self.reached(self.words_after):
            nodes.append(node("a2", "assistant", "text", self.sent_at + (self.words_from or self.words_after),
                              end_turn=True, text=self.WORDS))
        elif self.reached(self.words_from):
            nodes.append(node("a2", "assistant", "text", self.sent_at + self.words_from,
                              status="in_progress", text=self.WORDS[:4]))
        return nodes

    def evaluate(self, script, *args):
        if script == chatgpt.COLLECT_CANDIDATE_IMAGES:
            if self.tool_kind != "multimodal_text":
                return []
            return ([self.PICTURE] if self.reached(self.paints_after) else []) + (
                [self.PICTURE + "-2"] if self.reached(self.second_after) else [])
        if script == chatgpt.FETCH_AS_DATA_URL:
            return "data:image/png;base64,iVBORw0KGgo="
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
    def draw_on(page, thread_url=None, upload=None):
        driver = provider_on(page)
        driver.media_path.mkdir(parents=True, exist_ok=True)
        if upload:
            (driver.media_path / upload).write_bytes(b"\x89PNG not really")
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
        if reference:
            (driver.media_path / reference).write_bytes(b"\x89PNG not really")
        got = driver.generate_image("đổi nền thành bãi biển lúc hoàng hôn", reference_filename=reference)
        return got, page

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
