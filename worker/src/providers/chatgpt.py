import base64
import hashlib
import json
import re
import time
import uuid
from collections import Counter, deque
from pathlib import PurePosixPath
from typing import Optional
from urllib.parse import unquote

from src.providers.base import (MEMORY_ON_ERROR, BaseProvider, FeatureType, GenerationResult,
                                JobCancelled, MediaArtifact, ProviderError)
from src.providers.session import NO_SESSION, open_session, profile_of, saved

HOME = "https://chatgpt.com/"
# Measured 2026-09-27: the page
# changed overnight. Each selector lists the new page first and keeps the old one
# in case both are still served. The page first paints textarea#pending-home-input
# and mounts the real composer about ten seconds later: that placeholder is not ready.
COMPOSER = 'div.ProseMirror[contenteditable="true"], #prompt-textarea'
SEND_BUTTON = 'button[data-testid="send-button"], button[aria-label="Send"]'
# While it shows, the server is not asked, and a picture turn is not called over.
# A relabelled button costs reads, and leaves a picture's end to the server's
# record and its quiet time alone.
STOP_BUTTON = '[data-testid="stop-button"], button[aria-label="Stop"]'
ASSISTANT_TURN = '[data-message-author-role="assistant"], [data-chatgpt-selection-message-id]'
UPLOAD_INPUT = '#upload-files, input[type="file"][accept="image/*"]'
# Measured 2026-10-30 on a new chat: UPLOAD_INPUT's first match is `multiple: false`; a second image
# input takes several files at once (issue #22).
UPLOAD_MANY = 'input[type="file"][accept="image/*"][multiple]'
# Measured 2026-10-22: a picture attached to the composer shows as a chip, an img with a data:
# source beside a button labelled "Remove <file name>", inside the form; the chip is gone at the
# next page load, which _open makes. The label is the English interface's; the preview is not.
ATTACHMENT_REMOVE = 'form button[aria-label^="Remove "]'
ATTACHMENT_PREVIEW = 'form img[src^="data:"]'

# One ceiling for every request. A short answer still returns as soon as it
# settles, so the generous bound only costs anything when a picture is actually
# being drawn.
REPLY_TIMEOUT = 300
# An assistant turn that is still empty a second after sending is not a finished
# reply, it is one that has not started.
START_FLOOR = 6
# How long to wait for a thread url before deciding the server view will never
# be available for this page and falling back to watching the DOM.
NO_THREAD_GRACE = 30
# Least time between two reads of the conversation endpoint. Measured
# 2026-09-24: reading it every 1.5s through a whole gate earned a 429 that then
# broke thread loading. The page's stop button is the cheap signal; the server
# is asked only when the page looks finished, and backs off on 429.
SERVER_POLL_SECONDS = 3
SERVER_POLL_MAX = 30
# Opening a stored thread: how many tries and how long to wait between them
# when the site bounces the thread because the backend is throttling.
OPEN_ATTEMPTS = 3
OPEN_RETRY_SECONDS = 15
GOTO_RETRY_SECONDS = 20
LIMIT_REACHED = re.compile(r"you(?:['’]ve| have) hit (?:the|your) [^.]{0,60}limit", re.IGNORECASE)
LIMIT_RESETS = re.compile(r"\bin (\d+) (hour|minute)s?\b", re.IGNORECASE)
CHECK_POLL_SECONDS, CHECK_RELOAD_SECONDS, CHECK_WAIT_SECONDS = 5, 30, 120
CHECK_RETRY_SECONDS = 60
# The request that carries a turn: measured 2026-11-01 as POST /backend-api/f/conversation.
SEND_PATH = "/backend-api/f/conversation"
# How long the page must stay quiet and unchanged before the answer counts as
# over. Two seconds was thin: a reply that runs several tools puts the stop
# button away between them, and a pause there reads as an ending.
SETTLE_SECONDS = 6
# A picture turn gets no closing assistant node: measured 2026-10-02, its newest
# node stays the image tool's result for good. It is over once that result has
# been the turn's newest node this long with the stop button gone.
PICTURE_NODE = "multimodal_text"
PICTURE_QUIET_SECONDS = 10
# The node must be this turn's own by the server's clock too: an earlier turn's
# picture can land after the read of the thread before the send, and look new.
PICTURE_CLOCK_SLACK = 5
# The node can be there before the page has painted the picture.
PICTURE_PAINT_SECONDS = 30
# Assistant nodes that are the model's bookkeeping, not its reply. Measured 2026-10-28: a picture
# turn's empty closing answer was followed two seconds later by a reasoning_recap without end_turn,
# which, taken for the newest node, hid that the turn was over until the ceiling.
NOT_THE_REPLY = ("reasoning_recap", "model_editable_context")
# After a cancel, how long to wait for a freshly sent turn's thread address so
# the thread can be reported; the address normally shows within seconds.
CANCEL_THREAD_WAIT = 15
# A follow-up turn reads its thread before the send: every node there then is an
# earlier turn's. A failed read is tried again after a pause that doubles, from the
# 6s the polling after the send waits on a 429; a thread that stays unreadable is
# not written to (2026-10-06: an earlier answer came back).
BASELINE_TRIES = 3
BASELINE_PAUSE_SECONDS = 6

FETCH_AS_DATA_URL = """
async (url) => {
    const response = await fetch(url);
    const blob = await response.blob();
    return await new Promise((resolve) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.readAsDataURL(blob);
    });
}
"""

# Measured, because guessing here was wrong twice. A generated picture has no
# [data-message-author-role] ancestor at all, which is why scoping the search to
# the assistant turn once returned nothing. An attachment does sit in the user
# turn, and it comes back with a fresh url and re-encoded bytes, so neither a
# url snapshot nor a content hash recognises it. Position is what tells them
# apart: skip the user turn, keep everything else.
# Since 2026-09-27 both a generated picture and an upload are blob: images with
# no role ancestor; only the generated one sits in the generated-image gallery.
# A blob url is not a stable identity, so an earlier turn's picture is ruled out
# by position: only a gallery after the last reply's start marker belongs to it.
COLLECT_CANDIDATE_IMAGES = """
() => {
    const out = [];
    const starts = document.querySelectorAll("[data-chatgpt-agent-turn-start]");
    const lastStart = starts.length ? starts[starts.length - 1] : null;
    for (const img of document.querySelectorAll("img")) {
        const src = img.src || "";
        if (img.naturalWidth < 256 || img.naturalHeight < 256) continue;
        if (img.closest('[data-testid="generated-image-gallery"]')) {
            if (lastStart && !(lastStart.compareDocumentPosition(img) & Node.DOCUMENT_POSITION_FOLLOWING)) continue;
        } else {
            if (!src.includes("estuary") && !src.includes("oaiusercontent")) continue;
            const turn = img.closest("[data-message-author-role]");
            if (turn && turn.getAttribute("data-message-author-role") === "user") continue;
        }
        if (!out.includes(src)) out.push(src);
    }
    return out;
}
"""

SNAPSHOT_IMAGES = """
() => Array.from(document.querySelectorAll("img"), (img) => img.src || "")
"""

# Server truth. The page holds a session token and the conversation endpoint
# reports each message's status; "finished_successfully" with end_turn is the
# provider saying the turn is over. Measured 2026-09-23: cookie-only fetch is
# 404, with the token it is 200. Everything below is a fallback for when this
# is unavailable, never the other way round.
SESSION_TOKEN = """
async () => {
    try {
        const r = await fetch("/api/auth/session");
        const j = await r.json();
        return j.accessToken || null;
    } catch (e) { return null; }
}
"""

FETCH_THREAD = """
async ([id, token]) => {
    const r = await fetch("/backend-api/conversation/" + id,
                          {headers: {Authorization: "Bearer " + token}, credentials: "include"});
    if (!r.ok) return {status: r.status, nodes: []};
    const j = await r.json();
    const nodes = [];
    for (const n of Object.values(j.mapping || {})) {
        const m = n.message;
        if (!m) continue;
        const parts = (m.content && Array.isArray(m.content.parts)) ? m.content.parts : [];
        // Text turns carry strings in parts; code and tool-output turns carry
        // their text in content.text. Both are wanted: the tool output is where
        // a produced file's sandbox path is named.
        const text = parts.length
            ? parts.filter((p) => typeof p === "string").join("\\n")
            : ((m.content && typeof m.content.text === "string") ? m.content.text : "");
        nodes.push({
            id: n.id,
            role: m.author && m.author.role,
            status: m.status,
            end_turn: m.end_turn,
            create_time: m.create_time || 0,
            content_type: m.content && m.content.content_type,
            text: text,
        });
    }
    return {status: 200, nodes: nodes, temporary: !!j.is_temporary_chat};
}
"""

# Measured 2026-09-24: the file button calls this endpoint and the body is
# {status, download_url, file_name, mime_type, ...}; the url is the same
# session-bound estuary the pictures come from, so the bytes are fetched here,
# inside the page, and never stored as a link.
FETCH_INTERPRETER_FILE = """
async ([id, messageId, sandboxPath, token]) => {
    const url = "/backend-api/conversation/" + id + "/interpreter/download?message_id="
        + encodeURIComponent(messageId) + "&sandbox_path=" + encodeURIComponent(sandboxPath);
    const r = await fetch(url, {headers: {Authorization: "Bearer " + token}, credentials: "include"});
    if (!r.ok) return {status: r.status};
    const j = await r.json();
    if (!j.download_url) return {status: 200, missing: true};
    const f = await fetch(j.download_url, {credentials: "include"});
    if (!f.ok) return {status: f.status, stage: "content"};
    const blob = await f.blob();
    const data = await new Promise((resolve) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.readAsDataURL(blob);
    });
    return {status: 200, data: data, name: j.file_name || null,
            mime: j.mime_type || blob.type || null};
}
"""

# Measured 2026-10-30 (issue #23): the Library page reads the account's file store here, as
# {plan_type, limit_tier, used_bytes, allowed_bytes, remaining_bytes, is_over_limit, breakdown_*}.
# Every reference picture and every picture made stays in that store, a deleted thread or not.
FETCH_STORAGE_USAGE = """
async (token) => {
    const r = await fetch("/backend-api/files/library/storage/usage",
                          {headers: {Authorization: "Bearer " + token}, credentials: "include"});
    if (!r.ok) return {status: r.status};
    const j = await r.json();
    return {status: 200, used_bytes: j.used_bytes, allowed_bytes: j.allowed_bytes,
            remaining_bytes: j.remaining_bytes, is_over_limit: j.is_over_limit};
}
"""
# The store is read after a picture turn at most this often, and warns from this share or over its limit.
STORAGE_READ_SECONDS, STORAGE_WARN_SHARE = 600, 0.8

# Measured 2026-10-30 (issue #27). The Library lists {items, cursor}, 50 a page. The page's own scripts
# remove a file with DELETE .../files/{libfile id}, soft_delete saying trash or for good. Trashed, a
# file answered {success: true}, left the list, could be restored, and its bytes left used_bytes at once
# (179 of 179), so the cleanup never deletes for good.
FETCH_LIBRARY_PAGE = """
async ([token, cursor]) => {
    const r = await fetch("/backend-api/files/library", {method: "POST", credentials: "include",
        headers: {Authorization: "Bearer " + token, "Content-Type": "application/json"},
        body: JSON.stringify({cursor: cursor, limit: 50, trashed_only: false, include_hidden_files: true})});
    if (!r.ok) return {status: r.status};
    const j = await r.json();
    return {status: 200, cursor: j.cursor || null, items: j.items || []};
}
"""
TRASH_LIBRARY_FILE = """
async ([token, id]) => {
    const r = await fetch("/backend-api/files/library/files/" + encodeURIComponent(id) + "?soft_delete=true",
        {method: "DELETE", credentials: "include", headers: {Authorization: "Bearer " + token}});
    return {status: r.status};
}
"""

# Measured 2026-09-24 by flipping the switch in Settings, Personalization and
# watching the wire: "Enable memory" is PATCH settings/account_user_setting
# ?feature=m3m, and GET settings/user reports it as settings.m3m, with
# settings.sunshine and settings.moonshine following it. A conversation's own
# memory_scope read "global_enabled" with the switch off, so it says nothing.
MEMORY_KEYS = ("m3m", "sunshine", "moonshine")
FETCH_USER_SETTINGS = """
async ([token, keys]) => {
    const r = await fetch("/backend-api/settings/user",
                          {headers: {Authorization: "Bearer " + token}, credentials: "include"});
    if (!r.ok) return {status: r.status, values: {}};
    const j = await r.json();
    const s = (j && j.settings) || {};
    const values = {};
    for (const k of keys) if (k in s) values[k] = s[k];
    return {status: 200, values: values};
}
"""

# Measured 2026-09-24 by failing the turn request with a 500 from inside the
# page: the site paints one div carrying the text-token-text-error token, the
# server's own message and a Retry button, and no ordinary reply uses that
# token. Shape, not words: the message comes from the server in whatever
# language and wording the failure had.
#
# Measured 2026-09-27 the same way: the banner is now an aside with role alert,
# text-danger classes, the server's message and a Retry button.
ERROR_BANNER_PRESENT = """
() => {
    const found = [];
    for (const el of document.querySelectorAll('main .text-token-text-error, main aside[role="alert"]')) {
        const text = (el.textContent || '').trim();
        if (el.querySelector('button') && text) found.push(text.slice(0, 160));
    }
    return found;
}
"""

# Measured 2026-09-24: this is the call the site's own delete makes; it answers
# 200 {"success": true} and the thread reads 404 afterwards.
DELETE_THREAD = """
async ([id, token]) => {
    const r = await fetch("/backend-api/conversation/" + id, {
        method: "PATCH", credentials: "include",
        headers: {Authorization: "Bearer " + token, "Content-Type": "application/json"},
        body: JSON.stringify({is_visible: false}),
    });
    return {status: r.status};
}
"""

SANDBOX_PATH = re.compile(r"/mnt/data/[^\s\"'`)\]}>,]+")

# A file ChatGPT builds is offered by a button, not a link: there is no href to
# read, and the bytes live behind the same session-bound endpoint as pictures.
# Clicking it and catching the browser download is the only way in.
#
# Matched by shape, not by wording. The label is written in whatever language
# the question was asked in, and it is not always the file name: measured cases
# include "Download two_text_files.zip", "Tải file a_b.zip" and plain
# "Tải file ZIP tại đây". What stayed constant across every measurement is the
# behavior-btn class inside an assistant turn.
SNAPSHOT_DOWNLOADS = """
() => Array.from(document.querySelectorAll("button.behavior-btn"))
        .filter((b) => b.closest('[data-message-author-role="assistant"], [data-chatgpt-selection-message-id]'))
        .map((b) => (b.textContent || "").trim())
        .filter((t) => t.length > 0 && t.length < 200)
"""


class SendRefused(ProviderError):
    """Cloudflare answered this turn's send with its check, so the turn never reached ChatGPT."""


class ChatGPTProvider(BaseProvider):
    """Drives a logged-in chatgpt.com session through cloakbrowser.

    Each platform conversation keeps one ChatGPT thread: a turn with no stored
    thread yet opens a new chat, and a turn with one goes back to the thread the
    api stored, opening a new chat instead only when the server says it is gone.
    Our own history is replayed only into a chat turn that has no thread yet.
    The browser session is shared by all platform users; what keeps them
    apart is that a conversation belongs to exactly one user and that the
    account's memory is off, so a turn is refused while memory reads on.
    """

    name = "chatgpt"
    supported_features = (FeatureType.CHAT, FeatureType.IMAGE, FeatureType.VIDEO_SCRIPT, FeatureType.SCRIPT)

    def __init__(self, media_path, sessions_path, account=None):
        super().__init__(media_path, sessions_path, account)
        self._context = None
        self._page = None
        self._access_token = None
        # The sandbox files the thread named before this turn's send (#24), never this turn's.
        self._named_before = set()
        # The account's file store as last read, shown in health (#23); None until a picture turn.
        self.storage = None
        self._storage_read_at = None
        self.last_settle = None
        self.last_open = None
        # What the account's memory switch read before the last turn: on, off
        # or unknown. Shown in health; None until the first turn looks.
        self.memory = None
        # Where a cancelled turn had already landed, so the api can still keep
        # or remove that thread even though the result itself is refused.
        self.last_cancelled_thread = None
        # The last stop: whether its turn had been sent and the site's stop pressed. Shown in health.
        self.last_stop = None
        # The site's refusals since the browser opened, and when it opened: the record of a Cloudflare check.
        self._refused = deque(maxlen=40)
        self._opened_at = None
        self._sent_at = float("inf")

    def start(self) -> None:
        # The browser itself is created on first use: the sync driver is bound to
        # the thread that creates it, and that must be the runner thread.
        if not saved(self.sessions_path, self.account):
            raise RuntimeError(NO_SESSION.format(profile_of(self.sessions_path, self.account), self.account))

    def stop(self) -> None:
        if self._context is not None:
            try:
                self._context.close()
            except Exception:
                pass
        self._context = self._page = None

    def _ensure_page(self):
        if self._page is not None:
            return self._page
        self._context = open_session(self.sessions_path, self.account)
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        self._opened_at = time.time()
        self._refused.clear()
        self._page.on("response", self._note_response)
        return self._page

    def _note_response(self, response):
        """Keep the site's refusals, for the record of a Cloudflare check: never a query string or a body."""
        try:
            mitigated = response.headers.get("cf-mitigated")
            if response.status >= 400 or mitigated:
                self._refused.append({"at": round(time.time(), 1), "status": response.status, "method": response.request.method,
                                      "url": response.url.split("?")[0].split("#")[0][:200], "cf_mitigated": mitigated})
        except Exception:
            pass

    def _settings_status(self, page):
        """What the account's own settings answer now, or None when that cannot be asked."""
        try:
            self._access_token = self._access_token or self._session_token(page, 20)
            if not self._access_token:
                return None
            return page.evaluate(FETCH_USER_SETTINGS, [self._access_token, list(MEMORY_KEYS)]).get("status")
        except Exception:
            return None

    def _past_check(self, page, thread_url: Optional[str]):
        """Send nothing while Cloudflare has the site's api behind a check: wait for it to clear, and load
        the page again now and then, as a person would. Nothing here answers a check.

        Measured 2026-11-01, job d6e42ca5, a browser opened after 3 hours idle: the page loaded, then every
        /backend-api call answered 403 cf-mitigated for at least 23s, the settings read among them, and the
        turn went out into that and failed. The same account's next turn on 10-31 and 11-01 went through.
        """
        waited = 0
        while self._settings_status(page) == 403:
            if waited >= CHECK_WAIT_SECONDS:
                self._keep_check(page, "cloudflare check before sending")
                raise ProviderError("chatgpt stayed behind a Cloudflare check for {}s, so nothing was sent".format(waited))
            self._phase("waiting for the provider")
            page.wait_for_timeout(CHECK_POLL_SECONDS * 1000)
            waited += CHECK_POLL_SECONDS
            self._check_stop()
            if waited % CHECK_RELOAD_SECONDS == 0:
                page = self._open(thread_url)
        return page

    def _keep_check(self, page, banner: str):
        """What can be seen when the site shows a Cloudflare check (2026-10-31: four, and only their words were
        kept): a picture of the page and a record beside it. The turn has already failed; this cannot fail it worse."""
        folder = self.media_path.parent / "diagnostics"
        stem = "chatgpt-check-{}-{}-{}".format(self.account, int(time.time()), uuid.uuid4().hex[:6])
        record = {"account": self.account, "at": round(time.time(), 1), "banner": banner,
                  "browser_open_seconds": round(time.time() - self._opened_at, 1) if self._opened_at else None,
                  "refused_responses": list(self._refused)}
        try:
            folder.mkdir(parents=True, exist_ok=True)
            record["url"] = page.url.split("?")[0]
            record["title"] = page.title()
            record["challenge_frames"] = sum("challenges.cloudflare.com" in frame.url for frame in page.frames)
        except Exception as exc:
            record["unread"] = type(exc).__name__
        try:
            (folder / (stem + ".json")).write_text(json.dumps(record, indent=1), encoding="utf-8")
            page.screenshot(path=str(folder / (stem + ".png")))
        except Exception:
            pass

    def _goto(self, page, url: str):
        """Load a page, once more if the load itself failed.

        Measured 2026-10-30 and 31: after a long idle, turns failed on the load (90s timeouts,
        ERR_NAME_NOT_RESOLVED) and the next ones on the same session were done. A page or browser
        that is gone is not a failed load and goes up as it is.
        """
        try:
            page.goto(url, timeout=90000, wait_until="domcontentloaded")
        except Exception as exc:
            if type(exc).__name__ != "TimeoutError" and "net::ERR_" not in str(exc):
                raise
            self._phase("waiting for the provider")
            page.wait_for_timeout(GOTO_RETRY_SECONDS * 1000)
            self._check_stop()
            page.goto(url, timeout=90000, wait_until="domcontentloaded")

    def _keep_picture(self, page):
        """The page as it stood when the driver gave up, beside the run's media, for the diagnosis."""
        folder = self.media_path.parent / "diagnostics"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            name = "chatgpt-open-{}-{}.png".format(int(time.time()), uuid.uuid4().hex[:6])
            page.screenshot(path=str(folder / name))
        except Exception:
            pass

    def _session_token(self, page, seconds: float) -> Optional[str]:
        # Measured 2026-09-30: a fresh browser's first read answered empty; the token came 1.1s later.
        deadline = time.time() + seconds
        token = page.evaluate(SESSION_TOKEN)
        while not token and time.time() < deadline:
            page.wait_for_timeout(1000)
            token = page.evaluate(SESSION_TOKEN)
        return token

    def _composer_ready(self, page, seconds: float) -> bool:
        deadline = time.time() + seconds
        while time.time() < deadline:
            page.wait_for_timeout(500)
            if page.locator(COMPOSER).count() and page.locator(COMPOSER).first.is_visible():
                return True
        return False

    def _open(self, thread_url: Optional[str] = None):
        """Open the conversation's own thread, or a new one if there is none.

        Measured 2026-09-24: when a stored thread was slow to load, quietly
        falling back to a fresh chat produced a confident wrong answer that
        looked like success. So a fresh chat is opened only when the server says
        the thread is gone (404). Anything else is a provider failure: retried,
        refunded, visible, never a silent loss of context.
        """
        page = self._ensure_page()
        if thread_url:
            wanted = thread_url.rsplit("/c/", 1)[-1].split("?")[0].split("#")[0]
            reloaded = False
            for attempt in range(OPEN_ATTEMPTS):
                self._goto(page, thread_url)
                ready = self._composer_ready(page, 45)
                # A composer is not enough: the site can bounce a slow thread to
                # the root page, where a composer is also waiting, in a brand
                # new chat. The url has to be the thread that was asked for.
                landed = self._thread_id(page)
                self.last_open = {"wanted": wanted[:8], "landed": (landed or page.url)[:60],
                                  "composer": ready, "on_thread": landed == wanted,
                                  "attempt": attempt + 1}
                if ready and landed == wanted:
                    return page
                data = self._thread_nodes(page, wanted)
                status = data.get("status") if data else None
                if status == 404:
                    break  # gone for good; a fresh chat is the only option left
                if status in (429, 500, 502, 503) and attempt + 1 < OPEN_ATTEMPTS:
                    # Measured 2026-09-24: a throttled thread is bounced to the
                    # root page with a 429 behind it. That passes; talking into
                    # the wrong chat does not. Wait it out and try the thread again.
                    self._phase("waiting for the provider")
                    time.sleep(OPEN_RETRY_SECONDS * (2 ** attempt))
                    continue
                # The thread is there and so is the page, only its composer is late: load it once more.
                if status == 200 and landed == wanted and not reloaded and attempt + 1 < OPEN_ATTEMPTS:
                    reloaded = True
                    continue
                self._keep_picture(page)
                raise ProviderError(
                    "thread {} did not open: landed on {}, server status {}".format(
                        wanted[:8], (landed or page.url)[:60], status))
        # Measured 2026-09-29: a freshly launched browser mounted the composer at 7.8 to 34.9s, and once
        # not within the wait; a second load comes from a warm cache.
        for _ in range(2):
            self._goto(page, HOME)
            if self._composer_ready(page, 45):
                return page
        self._keep_picture(page)
        # Measured 2026-09-27: a signed-in session met a changed page and was
        # reported as logged out, which sent the diagnosis the wrong way.
        try:
            token = page.evaluate(SESSION_TOKEN)
        except Exception as exc:
            raise ProviderError("composer never appeared and the session could not be read: "
                                "{}".format(type(exc).__name__))
        if not token:
            raise ProviderError("composer never appeared and there is no session token: the "
                                "session is logged out; run scripts/login_provider.py chatgpt")
        raise ProviderError("composer never appeared although the session is signed in: "
                            "chatgpt.com has changed its page; measure it with "
                            "tests/provider_probe.py composer")

    @staticmethod
    def _flat(text: str) -> str:
        """One line of single spaces, so raw prompt and rendered text compare."""
        return " ".join((text or "").split())

    def _clear_composer(self, page, box):
        try:
            box.click(timeout=5000)
            page.keyboard.press("ControlOrMeta+a")
            page.keyboard.press("Backspace")
        except Exception:
            pass

    def _send(self, page, prompt: str):
        """Type the turn and prove it landed before pressing Enter.

        insert_text, never keyboard.type: type() presses a key per character and
        maps a newline to Enter, and a replayed history is full of newlines, so
        one job would go out as several turns.
        """
        box = page.locator(COMPOSER).first
        whole = self._flat(prompt)
        head, tail = whole[:40], whole[-40:]
        for attempt in range(3):
            if attempt or self._flat(box.inner_text()):
                self._clear_composer(page, box)
                if self._flat(box.inner_text()):
                    # Typing into what is left would send it along with the prompt.
                    self._phase("retrying the composer")
                    continue
            try:
                box.click(timeout=10000)
            except Exception:
                box.focus()
            page.keyboard.insert_text(prompt)
            page.wait_for_timeout(300)
            landed = self._flat(box.inner_text())
            if landed.startswith(head) and landed.endswith(tail):
                break
            self._phase("retrying the composer")
        else:
            raise ProviderError("the prompt never reached the composer")

        # Enter rather than the send button: with an attachment in the composer
        # the preview panel is painted over the button and swallows the click,
        # which the button being visible and enabled does not reveal.
        page.keyboard.press("Enter")
        for _ in range(20):
            page.wait_for_timeout(500)
            if not (box.inner_text() or "").strip():
                return
        button = page.locator(SEND_BUTTON).first
        if button.count():
            button.click(timeout=10000, force=True)

    @staticmethod
    def _thread_id(page) -> Optional[str]:
        url = page.url
        if "/c/" not in url:
            return None
        tail = url.rsplit("/c/", 1)[1].split("?")[0].split("#")[0]
        # A turn whose first request failed leaves a client-side placeholder in
        # the address (measured: /c/WEB:<uuid>, and since 2026-09-27
        # /c/local-chatgpt%3A<uuid>); the server knows no such thread.
        if not tail or ":" in unquote(tail):
            return None
        return tail

    def _read_memory(self, page) -> str:
        """The account's memory switch as the server reports it: on, off or unknown.

        No session token at all means the session is logged out; the anonymous
        composer would still take a message, so that is refused outright. An
        expired token is replaced once and the question asked again, so that a
        turn is never let through on a stale credential.
        """
        got = {}
        # Until the read below succeeds, health must not show the last turn's answer.
        self.memory = "unknown"
        for attempt in range(2):
            if not self._access_token:
                self._access_token = self._session_token(page, 20)
            if not self._access_token:
                raise ProviderError("no session token: the provider session is logged out; "
                                    "run scripts/login_provider.py chatgpt")
            try:
                got = page.evaluate(FETCH_USER_SETTINGS, [self._access_token, list(MEMORY_KEYS)])
            except Exception:
                got = {}
            if got.get("status") == 401 and attempt == 0:
                self._access_token = None
                continue
            break
        if got.get("status") == 401:
            raise ProviderError("the provider rejected a fresh session token; the session is "
                                "logged out or expired, run scripts/login_provider.py chatgpt")
        values = got.get("values") or {}
        present = [values[k] for k in MEMORY_KEYS if k in values]
        if any(v is True for v in present):
            self.memory = "on"
        elif present and all(v is False for v in present):
            self.memory = "off"
        else:
            self.memory = "unknown"
        return self.memory

    def _banner(self, page) -> list:
        """Every error banner on the page, oldest first, as its text."""
        try:
            return list(page.evaluate(ERROR_BANNER_PRESENT) or [])
        except Exception:
            # A page in the middle of a navigation has no context to ask; that
            # is not a banner.
            return []

    def _fail_on_banner(self, page, seen_before):
        # A banner is this turn's only if it was not there before the turn was
        # sent; a new one is appended after any older ones, so every banner is
        # counted, not just the first in the page.
        fresh = list((Counter(self._banner(page)) - Counter(seen_before or [])).elements())
        if fresh:
            said = "the provider showed its error banner: {}".format(fresh[0])
            if "cloudflare" in fresh[0].lower():
                self._keep_check(page, fresh[0])
                # Only on the site's own word that this send was refused: a turn it may have taken is not sent again.
                if any(r["cf_mitigated"] and r["method"] == "POST" and r["url"].endswith(SEND_PATH) and r["at"] >= self._sent_at
                       for r in self._refused):
                    raise SendRefused(said)
            raise ProviderError(said)

    def _thread_nodes(self, page, thread_id: str):
        """The thread as the server sees it.

        None only when there is no session token at all. Otherwise the fetched
        status comes back with the data, because a thread created seconds ago
        answers 404 for a moment before it can be read, and that is "not yet",
        not "never".
        """
        if not self._access_token:
            self._access_token = page.evaluate(SESSION_TOKEN)
        if not self._access_token:
            return None
        data = page.evaluate(FETCH_THREAD, [thread_id, self._access_token])
        if data.get("status") == 401:
            self._access_token = None
        return data

    def _baseline_ids(self, page) -> set:
        """The ids of every node the thread holds before the send; none for a new chat.

        A follow-up turn that cannot know them would take the earlier answers for its own, so
        the read is tried again and, still failing, the turn is refused before it is sent.
        """
        self._named_before = set()
        thread_id = self._thread_id(page)
        if not thread_id:
            return set()
        pause, status = BASELINE_PAUSE_SECONDS, None
        for attempt in range(BASELINE_TRIES):
            if attempt:
                page.wait_for_timeout(pause * 1000)
                pause *= 2
                self._stop_unsent()
            data = self._thread_nodes(page, thread_id)
            status = data.get("status") if data else "no session token"
            # A follow-up's thread always holds its earlier turn: a read with no node is no read.
            if data and status == 200 and data.get("nodes"):
                # Measured 2026-10-30 (#24): a turn that changes an earlier picture names that picture's
                # sandbox file again, as its edit's input; fetched, it came back as this turn's.
                self._named_before = {path for n in data["nodes"]
                                      for path in SANDBOX_PATH.findall(n.get("text") or "")}
                return {n["id"] for n in data["nodes"]}
            if data and status == 200:
                status = "no node"
        self._stop_unsent()
        raise ProviderError("chatgpt's thread could not be read before sending ({}), so nothing "
                            "was sent".format(status))

    @staticmethod
    def _drew(node) -> bool:
        """Whether a server node is the image tool's finished result."""
        return (node["role"] == "tool" and node["content_type"] == PICTURE_NODE
                and node["status"] == "finished_successfully")

    def _settle_via_server(self, page, baseline_ids: set, deadline: float, banner_before=None):
        """Wait until the server marks the new assistant turn finished.

        Returns (reply text, the turn's new nodes), or None the moment the
        server view is not usable here, so the caller can fall back to watching
        the page. A thread url normally appears within seconds of sending; a
        page that never gets one (a temporary chat, measured) is handed back
        early instead of eating the whole budget.
        """
        announced = False
        started = time.time()
        fresh = []
        unreadable = 0
        next_fetch = 0.0
        backoff = SERVER_POLL_SECONDS
        drawn = None
        while time.time() < deadline:
            page.wait_for_timeout(1000)
            self._check_stop()
            self._fail_on_banner(page, banner_before)
            thread_id = self._thread_id(page)
            if not thread_id:
                if time.time() - started > NO_THREAD_GRACE:
                    return None
                continue
            # While the page shows the model still working, the server has
            # nothing new to say; ask it only when the page looks finished.
            if page.locator(STOP_BUTTON).count():
                drawn = None
                continue
            if time.time() < started + START_FLOOR:
                continue
            if time.time() < next_fetch:
                continue
            data = self._thread_nodes(page, thread_id)
            if data is None:
                return None
            status = data.get("status")
            if status == 429:
                backoff = min(backoff * 2, SERVER_POLL_MAX)
                next_fetch = time.time() + backoff
                continue
            if status != 200:
                # A fresh thread is not readable on its first tick; a thread
                # that stays unreadable is one this view cannot help with.
                unreadable += 1
                if unreadable > 10:
                    return None
                next_fetch = time.time() + backoff
                continue
            unreadable = 0
            backoff = SERVER_POLL_SECONDS
            next_fetch = time.time() + backoff
            fresh = sorted(
                (n for n in data["nodes"] if n["role"] != "user" and n["id"] not in baseline_ids),
                key=lambda n: n["create_time"],
            )
            work = [n for n in fresh if n["content_type"] not in NOT_THE_REPLY]
            answers = [n for n in work if n["role"] == "assistant"]
            if not answers:
                continue
            if not announced:
                self._phase("reply started")
                announced = True
            last = answers[-1]
            newest = work[-1]
            picture = self._drew(newest) and newest["create_time"] >= started - PICTURE_CLOCK_SLACK
            if not picture or not drawn or drawn[0] != newest["id"]:
                drawn = (newest["id"], time.time()) if picture else None
            closed = last["status"] == "finished_successfully" and last.get("end_turn")
            if closed or (drawn and time.time() - drawn[1] >= PICTURE_QUIET_SECONDS):
                self._phase("reply finished")
                text = "\n\n".join(
                    n["text"] for n in answers if n["content_type"] == "text" and n["text"]
                ).strip()
                return text, fresh
        return "", fresh

    def _fetch_sandbox_files(self, page, thread_id: str, fresh: list, prompt: str,
                             skip_names: set):
        """Pull every file the turn produced straight from the server.

        The paths are named in the tool output; the download endpoint needs the
        final assistant message id. No button, no label, no language.
        """
        answers = [n for n in fresh if n["role"] == "assistant" and n.get("end_turn")]
        if not answers or not self._access_token:
            return []
        message_id = answers[-1]["id"]
        # What the model hands over is named in its final message; the tool
        # output also names every scratch file it wrote along the way (measured:
        # the two empty text files inside a zip came back as three downloads).
        # Prefer the final message, fall back to everything only when it names
        # nothing. In a turn that drew, the assistant's own nodes hold the image tool's input (measured
        # 2026-10-30: all 18 reference pictures of the thread, by sandbox names); only the tool's output
        # names what it made.
        preferred = SANDBOX_PATH.findall(answers[-1]["text"] or "")
        drew = any(self._drew(n) for n in fresh)
        candidates = preferred or SANDBOX_PATH.findall(
            "\n".join(n["text"] for n in fresh if n["text"] and (not drew or n["role"] == "tool")))
        paths = []
        for match in candidates:
            if (match not in paths and PurePosixPath(match).name not in skip_names
                    and match not in self._named_before):
                paths.append(match)

        artifacts = []
        for path in paths:
            try:
                got = page.evaluate(FETCH_INTERPRETER_FILE,
                                    [thread_id, message_id, path, self._access_token])
            except Exception:
                continue
            if got.get("status") != 200 or not got.get("data"):
                continue
            header, _, payload = got["data"].partition(",")
            blob = base64.b64decode(payload)
            offered = PurePosixPath(got.get("name") or path).name or "download"
            filename = "chatgpt-{}-{}".format(uuid.uuid4().hex[:8], offered)
            (self.media_path / filename).write_bytes(blob)
            mime = got.get("mime") or ""
            self._phase("file appeared")
            artifacts.append(
                MediaArtifact(
                    filename=filename,
                    type="image" if mime.startswith("image/") else "file",
                    metadata={"name": offered, "size": len(blob), "mime": mime,
                              "prompt": prompt[:500], "source": "chatgpt-interpreter"},
                )
            )
        return artifacts

    def _reply_text(self, page, baseline: int) -> str:
        turns = page.locator(ASSISTANT_TURN)
        if turns.count() <= baseline:
            return ""
        try:
            return turns.last.inner_text()
        except Exception:
            return ""

    def _await_result(self, page, baseline: int, seen_before, prompt: str, seen_downloads,
                      banner_before=None):
        """Wait for the answer to settle, then take whatever it turned out to be.

        One loop for every kind of request. Branching on what the caller asked
        for was wrong twice: an image-only answer was read as finished before it
        had started, and a picture asked for in plain chat was thrown away
        because the chat path only looked for words.
        """
        deadline = time.time() + REPLY_TIMEOUT
        floor = time.time() + START_FLOOR
        text = ""
        sources = []
        stable = 0

        while time.time() < deadline:
            page.wait_for_timeout(1000)
            # Once a second is the cancel checkpoint: a job the api has taken
            # away stops here instead of running to the end for nobody.
            self._check_stop()
            self._fail_on_banner(page, banner_before)

            if page.locator(STOP_BUTTON).count():
                stable = 0
                continue
            if time.time() < floor:
                continue

            current = self._reply_text(page, baseline)
            found = [s for s in page.evaluate(COLLECT_CANDIDATE_IMAGES) if s not in seen_before]
            if current.strip() and not text.strip():
                self._phase("reply started")
            if found and not sources:
                self._phase("picture appeared")

            # Nothing yet is not the same as nothing to come: an empty answer
            # never counts as settled, it just keeps the wait going.
            if not current.strip() and not found:
                stable = 0
                continue

            if current == text and found == sources:
                stable += 1
                if stable >= SETTLE_SECONDS:
                    break
            else:
                text, sources = current, found
                stable = 0

        return text, self._download(page, sources, prompt) + self._save_files(
            page, seen_downloads, prompt)

    def _save_files(self, page, seen_downloads, prompt: str):
        artifacts = []
        for label in [l for l in page.evaluate(SNAPSHOT_DOWNLOADS) if l not in seen_downloads]:
            try:
                with page.expect_download(timeout=120000) as caught:
                    page.locator("button.behavior-btn").filter(has_text=label).first.click()
                download = caught.value
                self._phase("file appeared")
                # The name comes from the page, so it is untrusted: reduce it to
                # a bare name and give it a unique prefix of our own.
                offered = PurePosixPath(download.suggested_filename).name or "download"
                filename = "chatgpt-{}-{}".format(uuid.uuid4().hex[:8], offered)
                target = self.media_path / filename
                download.save_as(str(target))
            except Exception:
                continue
            artifacts.append(
                MediaArtifact(filename=filename, type="file",
                              metadata={"name": offered, "size": target.stat().st_size,
                                        "prompt": prompt[:500], "source": "chatgpt"})
            )
        return artifacts

    def _download(self, page, sources, prompt: str):
        artifacts = []
        for source in sources:
            try:
                data_url = page.evaluate(FETCH_AS_DATA_URL, source)
            except Exception:
                continue
            if not data_url or not data_url.startswith("data:"):
                continue
            header, _, payload = data_url.partition(",")
            blob = base64.b64decode(payload)
            suffix = ".png" if "png" in header else ".jpg"
            filename = "chatgpt-{}{}".format(uuid.uuid4().hex, suffix)
            (self.media_path / filename).write_bytes(blob)
            artifacts.append(
                MediaArtifact(filename=filename, type="image",
                              metadata={"prompt": prompt[:500], "source": "chatgpt"})
            )
        return artifacts

    def _not_copies(self, files):
        """The sandbox files whose bytes the media store does not hold yet, each once.

        Measured 2026-10-28: a picture turn's tool output names the picture's sandbox copy, and the
        server hands back the very file the page showed, so the person got it twice. Measured
        2026-10-30: a turn named the reference pictures of its thread by sandbox names of their own,
        and 30 of them came back as pictures. A copy is removed from disk, never stored.
        """
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        new = {artifact.filename for artifact in files}
        sizes = {(self.media_path / name).stat().st_size for name in new}
        known = {digest(path) for path in self.media_path.iterdir()
                 if path.name not in new and path.is_file() and path.stat().st_size in sizes}
        kept = []
        for artifact in files:
            path = self.media_path / artifact.filename
            made = digest(path)
            if made in known:
                path.unlink()
            else:
                known.add(made)
                kept.append(artifact)
        return kept

    def _stopped(self, sent: bool, pressed: bool):
        self.last_stop = {"sent": sent, "pressed": pressed, "at": round(time.time(), 1)}

    def _drop_attachments(self, page):
        """Nothing attached by an earlier turn may ride along with this one.

        Measured 2026-10-22: a chip attached on a thread's own page is there again when that thread
        is loaded again (a per-conversation draft), gone at any other load; select-all plus
        Backspace does not take it; a plain click on its remove control takes nothing, a hover on
        the preview and then the click takes it. A chip that is still there is removed, and one
        that cannot be removed refuses the turn.
        """
        removes, previews = page.locator(ATTACHMENT_REMOVE), page.locator(ATTACHMENT_PREVIEW)
        try:
            for _ in range(3):
                if not removes.count():
                    break
                try:
                    (previews.first if previews.count() else removes.first).hover(timeout=3000)
                    removes.first.click(timeout=3000)
                except Exception:
                    break
                page.wait_for_timeout(1500)
            # A preview with no control the driver can tell apart (another interface language) is
            # an attachment too: refused, never sent along.
            left = removes.count() or previews.count()
        except Exception as exc:
            from playwright._impl._errors import is_target_closed_error
            if is_target_closed_error(exc):
                raise
            raise ProviderError("chatgpt's composer could not be looked at before sending ({}), so "
                                "nothing was sent".format(type(exc).__name__))
        if left:
            raise ProviderError("chatgpt's composer holds an attachment of another turn that could not be "
                                "removed, so nothing was sent")

    def _stop_unsent(self):
        """Stop here if the job has been taken away, noting that its turn never went out."""
        try:
            self._check_stop()
        except JobCancelled:
            self._stopped(sent=False, pressed=False)
            raise

    def _press_stop(self, page) -> bool:
        """Press the site's stop button if a reply is still being written; True once pressed."""
        try:
            button = page.locator(STOP_BUTTON).first
            if button.count():
                button.click(timeout=5000)
                return True
        except Exception:
            pass
        return False

    def _run(self, prompt: str, upload=None, thread_url: Optional[str] = None):
        """A turn, tried once more if Cloudflare refused its very send.

        Measured 2026-11-01: the check comes and goes within a minute, and the turn after a refused one went
        through each time. A send answered 403 never reached ChatGPT, so nothing is made twice or charged twice.
        A second refusal goes up as any provider error does, and the pool backs off.
        """
        try:
            return self._turn(prompt, upload, thread_url)
        except SendRefused:
            self._phase("waiting for the provider")
            waited = 0
            while waited < CHECK_RETRY_SECONDS:
                self._page.wait_for_timeout(CHECK_POLL_SECONDS * 1000)
                waited += CHECK_POLL_SECONDS
                self._check_stop()
            return self._turn(prompt, upload, thread_url)

    def _turn(self, prompt: str, upload=None, thread_url: Optional[str] = None):
        """One turn; `upload` is a file name in media_path, or a list of them (issue #22)."""
        uploads = [upload] if isinstance(upload, str) else list(upload or [])
        # Never let a cancel report the previous turn's thread as this one's.
        self.last_cancelled_thread = None
        page = self._past_check(self._open(thread_url), thread_url)
        self._drop_attachments(page)
        on_thread = self._thread_id(page)
        # Look before speaking: with memory on, this turn would be written into
        # a store that every other user's turn can read (measured 2026-09-23).
        if self._read_memory(page) == "on":
            raise ProviderError(MEMORY_ON_ERROR, kind="provider_misconfigured")
        baseline = page.locator(ASSISTANT_TURN).count()
        missing = [name for name in uploads if not (self.media_path / name).exists()]
        if missing:
            return GenerationResult.failure("reference image {} not found".format(", ".join(missing)))
        # Before anything is attached: a turn refused here must leave the shared composer empty.
        baseline_ids = self._baseline_ids(page)

        if uploads:
            paths = [str(self.media_path / name) for name in uploads]
            # A picture attached for a job already gone would wait in the shared composer for the next turn.
            self._stop_unsent()
            if len(paths) == 1:
                page.locator(UPLOAD_INPUT).first.set_input_files(paths[0])
            else:
                # Measured 2026-10-30: the first image input takes one file; this one takes several.
                page.locator(UPLOAD_MANY).first.set_input_files(paths)
            page.wait_for_timeout(3000)

        seen_before = set(page.evaluate(SNAPSHOT_IMAGES))
        seen_downloads = set(page.evaluate(SNAPSHOT_DOWNLOADS))
        # A banner left over from an earlier turn is not this turn's failure.
        banner_before = self._banner(page)
        # The page must still be on the thread it opened and read: a bounce to a new chat would
        # send the turn where its conversation is not (DECISIONS 2026-09-24).
        if self._thread_id(page) != on_thread:
            raise ProviderError("chatgpt left the conversation's thread before sending, so nothing was sent")
        # The last moment a job taken away can stay unsent: once typed, the turn is the site's.
        self._stop_unsent()
        started = self._sent_at = time.time()
        self.last_cancelled_thread = thread_url
        self._send(page, prompt)

        try:
            settled = self._settle_via_server(page, baseline_ids, started + REPLY_TIMEOUT, banner_before)
            if settled is None:
                # No server view here; watch the page the old way.
                self.last_settle = "dom"
                text, media = self._await_result(page, baseline, seen_before, prompt, seen_downloads,
                                                 banner_before)
            else:
                self.last_settle = "server"
                text, fresh = settled
                # The server says the turn is over; give the page a moment to paint
                # what it produced, then collect pictures from the page and files
                # from the server. The button click stays only as a fallback.
                page.wait_for_timeout(1500)
                sources = [s for s in page.evaluate(COLLECT_CANDIDATE_IMAGES) if s not in seen_before]
                # A turn that drew waits for the paint whatever node closed it: measured 2026-10-28,
                # an empty closing answer can land in the picture's own second, before the paint.
                drew = any(self._drew(n) for n in fresh)
                waited = 0
                while not sources and drew and waited < PICTURE_PAINT_SECONDS:
                    page.wait_for_timeout(1000)
                    self._check_stop()
                    waited += 1
                    sources = [s for s in page.evaluate(COLLECT_CANDIDATE_IMAGES) if s not in seen_before]
                media = self._download(page, sources, prompt)
                files = self._fetch_sandbox_files(
                    page, self._thread_id(page) or "", fresh, prompt, set(uploads))
                media += self._not_copies(files) if files else self._save_files(
                    page, seen_downloads, prompt)
        except JobCancelled:
            # Left alone the site writes or draws the turn out for nobody; measured 2026-10-01, its stop
            # button ends a text where it is and a picture before it arrives.
            self._stopped(sent=True, pressed=self._press_stop(page))
            # The message is already on the site, so a thread exists or is
            # about to: wait for its address (measured: a few seconds after
            # sending) so the api can keep or remove it instead of losing it to
            # the shared account's Library.
            waited = 0.0
            while not self._thread_id(page) and waited < CANCEL_THREAD_WAIT:
                page.wait_for_timeout(500)
                waited += 0.5
            if self._thread_id(page):
                self.last_cancelled_thread = page.url
            raise

        # Read the address only once the turn is over: a brand new chat is still
        # on the root url until the first message has been sent, and a failed
        # first turn leaves a placeholder the server does not know.
        landed = page.url if self._thread_id(page) else None

        if not text.strip() and not media:
            return GenerationResult(
                success=False, thread_url=landed, error_kind="provider_timeout",
                error="chatgpt returned nothing after {:.0f}s".format(time.time() - started),
            )
        return GenerationResult(success=True, text=text, media=media, thread_url=landed)

    def delete_thread(self, thread_url: str) -> bool:
        """Hide a thread in the shared account; a thread the server no longer knows counts as gone."""
        wanted = thread_url.rsplit("/c/", 1)[-1].split("?")[0].split("#")[0]
        if not wanted or wanted.startswith("WEB:"):
            return True
        page = self._ensure_page()
        if not page.url.startswith(HOME):
            page.goto(HOME, timeout=90000, wait_until="domcontentloaded")
        if not self._access_token:
            self._access_token = self._session_token(page, 20)
        if not self._access_token:
            raise ProviderError("no session token: the provider session is logged out; "
                                "run scripts/login_provider.py chatgpt")
        got = page.evaluate(DELETE_THREAD, [wanted, self._access_token])
        status = got.get("status")
        if status == 401:
            self._access_token = None
        if status in (200, 404):
            return True
        raise ProviderError("thread {} was not deleted: server status {}".format(wanted[:8], status))

    def clean_library_page(self, cursor: Optional[str], day: str, known) -> dict:
        """One page of the nightly cleanup (issue #27): move to the Library's trash the pictures created
        before `day` whose thread `known` says is the platform's, and nothing else on the account.

        `known` takes thread addresses and answers those the platform stores. A file that cannot be
        moved is reported and does not stop the rest; a list that cannot be read is an error.
        """
        page = self._ensure_page()
        if not page.url.startswith(HOME):
            page.goto(HOME, timeout=90000, wait_until="domcontentloaded")
        if not self._access_token:
            self._access_token = self._session_token(page, 20)
        if not self._access_token:
            raise ProviderError("no session token: the provider session is logged out; "
                                "run scripts/login_provider.py chatgpt")
        token = self._access_token
        got = page.evaluate(FETCH_LIBRARY_PAGE, [token, cursor])
        if got.get("status") == 401:
            self._access_token = None
        if got.get("status") != 200:
            raise ProviderError("chatgpt's library could not be read ({})".format(got.get("status")))
        pictures = [
            item for item in got.get("items") or []
            if item.get("library_file_category") == "image" and item.get("access_kind") == "owned"
            and not item.get("trashed_at") and item.get("origination_thread_id")
            and str(item.get("record_creation_time") or "")[:10] and str(item["record_creation_time"])[:10] < day]
        address = {item["id"]: "{}c/{}".format(HOME, item["origination_thread_id"]) for item in pictures}
        ours = known(sorted(set(address.values()))) if address else set()
        report = {"removed": 0, "bytes": 0, "failed": [], "not_ours": 0, "cursor": got.get("cursor")}
        for item in pictures:
            if address[item["id"]] not in ours:
                report["not_ours"] += 1
                continue
            status = page.evaluate(TRASH_LIBRARY_FILE, [token, item["id"]]).get("status")
            if status == 200:
                report["removed"] += 1
                report["bytes"] += item.get("file_size_bytes") or 0
            else:
                report["failed"].append((item["id"], status))
            page.wait_for_timeout(200)
        return report

    def chat(self, message: str, history: Optional[list] = None,
             thread_url: Optional[str] = None) -> GenerationResult:
        prompt = message
        # With a thread the model already has the history in front of it;
        # replaying our copy would show it everything twice.
        if history and not thread_url:
            lines = ["{}: {}".format(turn["role"], turn["content"]) for turn in history]
            prompt = (
                "Here is our conversation so far.\n\n"
                + "\n\n".join(lines)
                + "\n\nReply to this next message only:\n"
                + message
            )
        return self._run(prompt, thread_url=thread_url)

    def generate_image(self, prompt: str, reference_filename: Optional[str] = None,
                       thread_url: Optional[str] = None) -> GenerationResult:
        instruction = "Generate an image: {}".format(prompt)
        if isinstance(reference_filename, list) and len(reference_filename) > 1:
            instruction = ("Use the {} attached images as references, in the order they are attached, and "
                           "generate a new image: {}").format(len(reference_filename), prompt)
        elif reference_filename:
            instruction = "Use the attached image as the reference and generate a new image: {}".format(prompt)
        result = self._run(instruction, upload=reference_filename, thread_url=thread_url)
        self._read_storage(self._page)
        # Measured 2026-11-01: "You've hit the Free plan limit for image generations requests. You can create
        # more images when the limit resets in 11 hours." An ordinary closed turn, the words the only sign.
        if result.success and not result.media and LIMIT_REACHED.search(result.text or ""):
            resets = LIMIT_RESETS.search(result.text)
            seconds = int(resets.group(1)) * (3600 if resets.group(2).lower() == "hour" else 60) if resets else 3600
            return GenerationResult(success=False, thread_url=result.thread_url, error_kind="provider_limit",
                                    hold_seconds=seconds, error="the chatgpt account is at its limit: {}".format(
                                        self._flat(result.text)[:300]))
        return result

    def _read_storage(self, page):
        """Read the account's file store for health, at most every STORAGE_READ_SECONDS (#23).

        Diagnostics only: the turn's result never depends on it, and a read that fails is kept as
        its status in `storage["error"]`, not raised.
        """
        now = time.time()
        if page is None or (self._storage_read_at is not None and now - self._storage_read_at < STORAGE_READ_SECONDS):
            return
        self._storage_read_at = now
        try:
            token = self._access_token or page.evaluate(SESSION_TOKEN)
            got = page.evaluate(FETCH_STORAGE_USAGE, token) if token else {"status": "no session token"}
        except Exception as exc:
            # The turn already has its pictures; a page gone now is the next turn's to meet.
            got = {"status": "{}: {}".format(type(exc).__name__, exc)[:200]}
        if got.get("status") != 200 or not got.get("allowed_bytes"):
            self.storage = {"error": got.get("status"), "read_at": round(now, 1)}
            return
        share = round(got["used_bytes"] / got["allowed_bytes"], 3)
        self.storage = {"used_bytes": got["used_bytes"], "allowed_bytes": got["allowed_bytes"],
                        "remaining_bytes": got.get("remaining_bytes"), "is_over_limit": bool(got.get("is_over_limit")),
                        "used_share": share,
                        "warning": share >= STORAGE_WARN_SHARE or bool(got.get("is_over_limit")),
                        "read_at": round(now, 1)}

    def generate_video_script(self, image_filename: str, duration: int = 5,
                              thread_url: Optional[str] = None) -> GenerationResult:
        instruction = (
            "Write a Wan 2.2 video prompt of {} seconds for the attached image. "
            "Describe camera movement, character animation and ambient motion. "
            "Answer with a single paragraph under 150 words and nothing else."
        ).format(duration)
        return self._run(instruction, upload=image_filename, thread_url=thread_url)
