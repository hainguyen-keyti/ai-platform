import json
import re
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from src.providers.base import (BaseProvider, FeatureType, GenerationResult, JobCancelled,
                                MediaArtifact, ProviderError)
from src.providers.session import NO_SESSION, open_session, profile_of, saved

# Everything below was measured on a real account on 2026-09-25 and 2026-09-27.
# The interface is Vietnamese, so nothing keys on words.
HOME = "https://gemini.google.com/app"
COMPOSER = 'rich-textarea .ql-editor[contenteditable="true"]'
# The turn is this streamed request, not the batchexecute rpcs around it: its body carries the
# answer and it finishes after any picture has arrived (13.1s picture, 15.0s stream).
STREAM = "BardFrontendService/StreamGenerate"
# A generated picture is fetched from here during its turn and nowhere else. A user's upload is a
# blob during the turn and /rd-gg/ when reopened, so the match is exact, never a prefix of this.
PICTURE_HOST = "lh3.googleusercontent.com"
PICTURE_PATH = "/rd-gg-dl/"
GEMINI_HOST = "gemini.google.com"
SETTINGS_URL = "https://gemini.google.com/personalization-settings"
SETTINGS_PATH = "/personalization-settings"
# The account's other memory switch has this page to itself (measured 2026-10-01), and it is where
# a signed-out session asking for the settings page is sent instead.
SAVED_INFO_URL = "https://gemini.google.com/saved-info"
SAVED_INFO_PATH = "/saved-info"
# Where Google sends a machine it suspects of automated traffic (measured 2026-09-27); its query's
# token holds the network's address, so that url never goes into an error.
BLOCK_HOST = "www.google.com"
BLOCK_PATH = "/sorry/"
SWITCH = 'button[role="switch"]'
# The upload control carries no data-test-id. While the page gets ready it shows a placeholder, "Add
# files", that opens nothing; the real button replaces it 0.5 to 2.5s after the composer, inside
# simplified-input-menu (measured 2026-10-06). Its place comes first, then labels it has carried.
UPLOAD_CONTROL = ("simplified-input-menu button[aria-haspopup='menu']",
                  "button[aria-label*='Upload' i]", "button[aria-label*='Nội dung tải lên']")
UPLOAD_INPUT = 'input[type="file"][accept="image/*"]'
UPLOAD_CONTROL_WAIT = 15
UPLOAD_OPEN_WAIT = 5
# A video is made after the stream ends (measured 2026-10-06: the stream done at 6.7s, the video at
# 73.5s) and is served from this host; an mp4 carries "ftyp" at byte 4.
VIDEO_HOST = "contribution.usercontent.google.com"
VIDEO_WAIT = 300
THREAD = re.compile(r"/app/([0-9a-f]{8,})(?:[/?#]|$)")

# Measured 2026-09-27: each turn is a user-query, then a model-response holding a message-content,
# in document order. Words alone cannot say which question is this turn's (every video script job
# opens with the same ones), so the questions already on the page are marked before the send, and
# this turn's question is the newest one that is NOT marked. Its words are then only a check. The
# questions are counted too: a page that rebuilds its elements loses the marks, not the count.
MARK_QUERIES = """
() => {
    const queries = document.querySelectorAll('user-query');
    queries.forEach((q) => q.setAttribute('data-platform-before', ''));
    return queries.length;
}
"""

ANSWER_AFTER_QUERY = """
([words, before]) => {
    const queries = document.querySelectorAll('user-query');
    const mine = queries.length > before ? queries[queries.length - 1] : null;
    if (!mine || mine.hasAttribute('data-platform-before')) return {query: false, text: ''};
    const shown = (mine.innerText || '').normalize('NFC').toLowerCase();
    if (!words.every((w) => shown.includes(w))) return {query: false, text: ''};
    const after = Array.from(document.querySelectorAll('model-response'))
        .filter((r) => mine.compareDocumentPosition(r) & Node.DOCUMENT_POSITION_FOLLOWING);
    if (!after.length) return {query: true, text: '', note: '', video: '', player: false};
    const answer = after[after.length - 1];
    // The text of `root` without the elements `hide` picks, each put back as it was.
    const readWithout = (root, hide) => {
        const hidden = Array.from(root.querySelectorAll(hide));
        const display = hidden.map((n) => n.style.display);
        hidden.forEach((n) => { n.style.display = 'none'; });
        const read = root.innerText || '';
        hidden.forEach((n, i) => { n.style.display = display[i]; });
        return read;
    };
    const content = answer.querySelector('message-content');
    // While its video is made, an answer shows a note and holds no message-content (2026-10-06); its
    // screen-reader label ("Gemini said") is no note.
    if (!content) {
        return {query: true, text: '', note: readWithout(answer, '.cdk-visually-hidden').trim(), video: '',
                player: false};
    }
    // A generated video's player shows its own time ("0:00 / 0:10"), which is no part of the words.
    const clip = content.querySelector('generated-video video');
    return {query: true, text: readWithout(content, 'generated-video'), note: '',
            video: clip ? (clip.currentSrc || clip.src || '') : '',
            player: !!content.querySelector('generated-video')};
}
"""

REPLY_TIMEOUT = 300
THREAD_WAIT = 30
# A reopened thread paints its earlier turns after the composer shows: a moment on 2026-09-27, about
# 35s on Gemini's new web app (2026-10-28, issue #14), where deleting with 20s refused every thread.
HISTORY_WAIT = 60
# Gemini's new web app (2026-10-28, issue #14) sends no StreamGenerate: the turn shows this button in
# the input area from the send until it is over (gone at 30.3s and 33.3s), and its words can paint
# long after the button goes (76.7s after the send), so they are waited for this long.
STOP_BUTTON = 'button[aria-label="Stop response"]'
# What a failed turn's page showed (issue #15): where it was, what it counted, the Stop response
# button, and any text it put up as an alert or a status, which is where an error would be said.
PAGE_FACTS = """
() => ({
    url: location.href,
    questions: document.querySelectorAll('user-query').length,
    answers: document.querySelectorAll('model-response').length,
    messageContents: document.querySelectorAll('message-content').length,
    'Stop response': document.querySelectorAll('button[aria-label="Stop response"]').length,
    lastAnswer: ([...document.querySelectorAll('model-response')].pop() || {}).innerText || '',
    alerts: [...document.querySelectorAll('[role="alert"], [role="status"], snack-bar-container, '
                                          + 'mat-snack-bar-container')]
        .map((e) => (e.innerText || '').trim()).filter(Boolean).slice(0, 5),
})
"""
ANSWER_WAIT = 90
# So does the conversation list its rows (0.3 to 2.4s, measured 2026-09-27).
LIST_WAIT = 15
OPEN_ATTEMPTS = 2
UPLOAD_WAIT = 30
SETTINGS_WAIT = 15

SIGNED_OUT = "the gemini session is signed out; run scripts/login_provider.py gemini"
BLOCKED = ("Google is showing this machine its unusual-traffic check for Gemini "
           "(www.google.com/sorry), so the worker backs off; wait for it to lift, logging in "
           "again will not help")
PERSONAL_CONTEXT_ON = ("the shared Gemini account has personal context switched on, so this turn "
                       "was not sent; ask the account owner to turn it off "
                       "(gemini.google.com/personalization-settings) and try again")
SAVED_INFO_ON = ("the shared Gemini account has saved info switched on, so this turn was not "
                 "sent; ask the account owner to turn it off (gemini.google.com/saved-info) and "
                 "try again")
# Answers Gemini gives when its turn failed, as seen on the real site (job b55dcf5d, 2026-10-01).
FAILURE_SENTENCES = ("I encountered an error doing what you asked. Could you try again?",)
# Each memory switch: its page, that page's own path, and the refusal while it is on.
MEMORY_SWITCHES = ((SETTINGS_URL, SETTINGS_PATH, PERSONAL_CONTEXT_ON),
                   (SAVED_INFO_URL, SAVED_INFO_PATH, SAVED_INFO_ON))


def query_words(prompt: str) -> list:
    """A few words of the prompt that every way of showing it keeps.

    Compared in NFC and lower case, because a prompt typed in decomposed Vietnamese is shown
    composed; letters only, because a list is shown without its numbers and emoji as pictures
    (tier 1 re-review, 2026-09-27).
    """
    words = []
    for word in re.findall(r"\w+", unicodedata.normalize("NFC", prompt or "").lower()):
        if len(word) >= 3 and not word.isdigit() and word not in words:
            words.append(word)
        if len(words) == 3:
            break
    return words


def is_generated_picture(url: str, content_type: str, size) -> bool:
    """A picture generated in this turn, by where it came from; never by what it looks like."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return (parsed.scheme == "https" and parsed.hostname == PICTURE_HOST
            and parsed.path.startswith(PICTURE_PATH)
            and (content_type or "").startswith("image/") and bool(size))


def is_blocked(url: str) -> bool:
    """Google's unusual-traffic check: no waiting on the page clears it, and nothing may solve it."""
    try:
        parsed = urlparse(url or "")
    except ValueError:
        return False
    return parsed.hostname == BLOCK_HOST and parsed.path.startswith(BLOCK_PATH)


class GeminiProvider(BaseProvider):
    """Drives the owner's gemini.google.com session through cloakbrowser.

    The page signs its own calls (a WAA handshake), so turns are typed into it. The server's word
    that a turn is over is its StreamGenerate response finishing; pictures are caught from the
    network while the turn runs, because reopening the thread does not fetch them again.
    """

    name = "gemini"
    supported_features = (FeatureType.CHAT, FeatureType.IMAGE, FeatureType.VIDEO_SCRIPT, FeatureType.SCRIPT)

    def __init__(self, media_path, sessions_path, account=None):
        super().__init__(media_path, sessions_path, account)
        self._context = None
        self._page = None
        self.last_settle = None
        self.last_open = None
        self.last_cancelled_thread = None
        self.last_stream = None
        self.last_pictures = []
        self.memory = None
        # A failed turn's page is kept here, beside the media (storage/failures, git-ignored with
        # storage/), so its cause can be named from its own record (issue #15).
        self.failures_path = self.media_path.parent / "failures"
        self._sent_on = None

    def start(self) -> None:
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
        return self._page

    @staticmethod
    def _thread_id(page) -> Optional[str]:
        found = THREAD.search(getattr(page, "url", "") or "")
        return found.group(1) if found else None

    @staticmethod
    def _flat(text: str) -> str:
        return " ".join((text or "").split())

    def _composer_ready(self, page, seconds: float) -> bool:
        deadline = time.time() + seconds
        while time.time() < deadline:
            page.wait_for_timeout(500)
            if page.locator(COMPOSER).count() and page.locator(COMPOSER).first.is_visible():
                return True
        return False

    # --- the leak switches -----------------------------------------------------------

    def _switch(self, page, url: str, own: str) -> str:
        """The one switch of a settings page as that page shows it: on, off, unknown, signed-out or
        blocked (Google's unusual-traffic check).

        Only a page of the site that stayed on its own path and shows exactly one switch is read:
        the labels follow the interface's language, so a switch is told by where it is. On is
        believed at once; off only when two polls in a row say so, since a first paint could be a
        default. A signed-out session asking for /personalization-settings lands on /saved-info,
        whose two switches are neither.
        """
        polls, error = [], None
        try:
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            started = time.time()
            deadline = started + SETTINGS_WAIT
            off_site = was_off = False
            while time.time() < deadline:
                page.wait_for_timeout(500)
                if is_blocked(page.url):
                    return "blocked"
                landed = urlparse(page.url or "")
                # Off the site, to Google's sign-in: no account, unless it comes back, which a
                # cookie refresh passing through Google would (re-review, 2026-09-27).
                off_site = bool(landed.hostname and landed.hostname != GEMINI_HOST)
                path = "" if off_site else landed.path.rstrip("/")
                # Sent to /saved-info from another page (measured): no account.
                if path == SAVED_INFO_PATH and own != SAVED_INFO_PATH:
                    return "signed-out"
                checked = count = None
                if path == own:
                    switches = page.locator(SWITCH)
                    count = switches.count()
                    if count == 1:
                        checked = switches.first.get_attribute("aria-checked")
                polls.append({"at": round(time.time() - started, 1), "path": landed.hostname if off_site else path,
                              "switches": count, "checked": checked})
                if checked == "true":
                    return "on"
                if checked == "false" and was_off:
                    return "off"
                was_off = checked == "false"
            if off_site:
                return "signed-out"
        except Exception as exc:
            error = "{}: {}".format(type(exc).__name__, str(exc).splitlines()[0][:160] if str(exc) else "")
        self._keep_switch(page, own, polls, error)
        return "unknown"

    def _keep_switch(self, page, own: str, polls: list, error: Optional[str]):
        """What a settings page showed when its switch could not be read (2026-11-06: one real turn read
        unknown and nothing said why; the next reads were off): every poll, and a picture, under
        failures_path. Keeping it never changes the reading."""
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        name = "gemini-switch-{}-{}-{}".format(stamp, own.strip("/"), uuid.uuid4().hex[:6])
        record = {"account": self.account, "asked": own, "landed": None, "error": error,
                  "settings_wait": SETTINGS_WAIT, "polls": polls}
        try:
            # Never the query: Google's check carries the network's address there.
            record["landed"] = (page.url or "").split("?")[0]
        except Exception:
            pass
        try:
            self.failures_path.mkdir(parents=True, exist_ok=True)
            (self.failures_path / (name + ".json")).write_text(json.dumps(record, indent=1), encoding="utf-8")
            page.screenshot(path=str(self.failures_path / (name + ".png")))
        except Exception:
            pass

    def _guard(self):
        """Look before speaking, at both of the account's memory switches, in a tab of its own so
        the conversation's page is never moved. A switch on refuses, naming it; signed out refuses;
        blocked refuses as a provider error, so the pool backs off; unknown does not block. A page
        that refuses is the last one loaded, and `memory` says off only when both read off."""
        self.memory = "unknown"
        read = []
        page = self._context.new_page()
        try:
            for url, own, refusal in MEMORY_SWITCHES:
                state = self._switch(page, url, own)
                if state in ("blocked", "signed-out", "on"):
                    self.memory = state
                if state == "blocked":
                    raise ProviderError(BLOCKED, kind="provider_blocked")
                if state == "signed-out":
                    raise ProviderError(SIGNED_OUT, kind="provider_misconfigured")
                if state == "on":
                    raise ProviderError(refusal, kind="provider_misconfigured")
                read.append(state)
        finally:
            try:
                page.close()
            except Exception:
                pass
        if all(state == "off" for state in read):
            self.memory = "off"

    # --- opening and typing ------------------------------------------------------------

    def _open(self, thread_url: Optional[str] = None):
        page = self._ensure_page()
        wanted = self._thread_id(type("AtUrl", (), {"url": thread_url or ""})())
        target = "{}/{}".format(HOME, wanted) if wanted else HOME
        for attempt in range(OPEN_ATTEMPTS):
            page.goto(target, timeout=90000, wait_until="domcontentloaded")
            blocked = is_blocked(page.url)
            ready = not blocked and self._composer_ready(page, 30)
            landed = self._thread_id(page)
            self.last_open = {"wanted": (wanted or "new")[:8], "composer": ready,
                              "landed": (landed or page.url.split("?")[0])[:60],
                              "attempt": attempt + 1}
            if blocked:
                raise ProviderError(BLOCKED, kind="provider_blocked")
            if ready and (not wanted or landed == wanted):
                return page
        # A deleted thread lands back on /app, and so could a slow one: nothing tells them apart,
        # so this is a failure and a refund, never a silent fresh chat (DECISIONS 2026-09-24).
        raise ProviderError("gemini did not open {}: composer {} landed {}".format(
            (wanted or "a new chat")[:8], (self.last_open or {}).get("composer"),
            (self.last_open or {}).get("landed")))

    def _clear_composer(self, page, box):
        try:
            box.click(timeout=5000)
            page.keyboard.press("ControlOrMeta+a")
            page.keyboard.press("Backspace")
        except Exception:
            pass

    def _send(self, page, prompt: str):
        """Type the turn and prove it landed before pressing Enter.

        insert_text, never keyboard.type: type() maps a newline to Enter, and a replayed history
        is full of newlines. Both ends of the read-back must match, and a box that will not clear
        is never typed into, or a prompt left over from a failed attempt goes out twice.
        """
        box = page.locator(COMPOSER).first
        whole = self._flat(prompt)
        head, tail = whole[:40], whole[-40:]
        for attempt in range(3):
            if attempt or self._flat(box.inner_text()):
                self._clear_composer(page, box)
                if self._flat(box.inner_text()):
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
            raise ProviderError("the prompt never reached gemini's composer")
        self.sent = True
        page.keyboard.press("Enter")

    def _attach(self, page, filename: str):
        path = self.media_path / filename
        if not path.exists():
            raise ProviderError("reference image {} not found".format(filename), kind="worker_error")
        if not page.locator(UPLOAD_INPUT).count():
            control, deadline = None, time.time() + UPLOAD_CONTROL_WAIT
            while True:
                control = next((sel for sel in UPLOAD_CONTROL if page.locator(sel).count()), None)
                if control or time.time() >= deadline:
                    break
                page.wait_for_timeout(250)
            if control:
                page.locator(control).first.click(timeout=10000)
                deadline = time.time() + UPLOAD_OPEN_WAIT
                while not page.locator(UPLOAD_INPUT).count() and time.time() < deadline:
                    page.wait_for_timeout(250)
        if not page.locator(UPLOAD_INPUT).count():
            raise ProviderError("gemini's upload control did not open")
        # Without its picture the turn would still go out, and "please attach an image" would be
        # stored as a video script: the server has to accept the picture first.
        try:
            with page.expect_response(lambda r: "ProcessFile" in r.url,
                                      timeout=UPLOAD_WAIT * 1000) as uploaded:
                page.locator(UPLOAD_INPUT).first.set_input_files(str(path))
            status = uploaded.value.status
        except Exception as exc:
            raise ProviderError("gemini never confirmed the reference picture: {}".format(
                type(exc).__name__))
        if status != 200:
            raise ProviderError("gemini refused the reference picture: status {}".format(status))
        page.wait_for_timeout(1000)

    # --- one turn --------------------------------------------------------------------

    def _bubbles(self, page):
        try:
            return page.locator("message-content, model-response").all_inner_texts()
        except Exception:
            return []

    def _history(self, page, reopened: bool) -> int:
        """Wait until a reopened thread shows its earlier turns and holds still.

        A reopened thread always has a turn, so one that never paints any did not load, and
        nothing is typed into it. Which answer is this turn's is decided by ANSWER_AFTER_QUERY,
        not by this count.
        """
        if not reopened:
            return len(self._bubbles(page))
        deadline = time.time() + HISTORY_WAIT
        last, steady = None, 0
        while time.time() < deadline:
            count = len(self._bubbles(page))
            steady = steady + 1 if (count and count == last) else 0
            if steady >= 2:
                return count
            last = count
            page.wait_for_timeout(1000)
        raise ProviderError("gemini never painted the earlier turns of thread {}".format(
            (self._thread_id(page) or "?")[:8]))

    def _run(self, prompt: str, upload: Optional[str] = None, thread_url: Optional[str] = None):
        """The turn; one that fails once it was sent keeps its page and says where (issue #15)."""
        self._sent_on = None
        try:
            result = self._turn(prompt, upload=upload, thread_url=thread_url)
        except ProviderError as exc:
            if self._sent_on is None:
                raise
            raise ProviderError("{} ({})".format(exc, self._keep_failure(self._sent_on)), kind=exc.kind) from exc
        if not result.success and self._sent_on is not None:
            result.error = "{} ({})".format(result.error, self._keep_failure(self._sent_on))
        return result

    def _keep_failure(self, page) -> str:
        """A picture of the page and what it counted, under failures_path, named by the time and the
        thread; what to append to the failure's message. Keeping it never changes the failure."""
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        try:
            # The random tail keeps two failures of one thread in the same second apart.
            name = "gemini-{}-{}-{}".format(stamp, self._thread_id(page) or "new", uuid.uuid4().hex[:6])
            self.failures_path.mkdir(parents=True, exist_ok=True)
            facts = page.evaluate(PAGE_FACTS)
            page.screenshot(path=str(self.failures_path / (name + ".png")))
            (self.failures_path / (name + ".txt")).write_text(
                json.dumps(facts, ensure_ascii=False, indent=1) if facts else "the page could not be read\n",
                encoding="utf-8")
        except Exception as exc:
            return "page not kept: {}: {}".format(type(exc).__name__, str(exc).splitlines()[0][:80] if str(exc) else "")
        return "page kept as {}".format(name)

    def _turn(self, prompt: str, upload: Optional[str] = None, thread_url: Optional[str] = None):
        self.last_cancelled_thread = None
        page = self._open(thread_url)
        self._guard()
        if upload:
            self._attach(page, upload)
        # A reopened thread must show that it loaded before anything is typed into it.
        self._history(page, reopened=bool(self._thread_id(page)))

        # The handlers only collect. Reading a streamed body inside one blocks the dispatcher and
        # the picture events queued behind it were lost; and Response.finished() never returns on
        # a stream that breaks after its headers (both 2026-09-27). The request's own finished or
        # failed event is what ends the wait, polled against a deadline.
        streams, candidates, ended = [], [], {}

        def on_response(r):
            if STREAM in r.url and r.request.method == "POST":
                streams.append(r)
            elif PICTURE_HOST in r.url:
                ctype = (r.headers or {}).get("content-type", "")
                entry = {"url": r.url, "type": ctype, "body": b"", "note": ""}
                # Listed before its body is read, so a picture still arriving when the turn is
                # read keeps its url for the second fetch (re-review, 2026-09-27).
                candidates.append(entry)
                # Read the moment it arrives: after the turn the body can be evicted from the
                # inspector cache (measured). Pictures are small; the stream is never read here.
                if urlparse(r.url).path.startswith(PICTURE_PATH) and ctype.startswith("image/"):
                    try:
                        entry["body"] = r.body()
                    except Exception as exc:
                        entry["note"] = type(exc).__name__

        def on_finished(req):
            if STREAM in req.url and req.method == "POST":
                ended.setdefault("request", req)
                ended.setdefault("how", "finished")

        def on_failed(req):
            if STREAM in req.url and req.method == "POST":
                ended.setdefault("request", req)
                ended.setdefault("how", "failed: {}".format(getattr(req, "failure", None)))

        # Every question on the page is marked and counted; this turn's is the one that is not.
        try:
            before = page.evaluate(MARK_QUERIES)
        except Exception as exc:
            raise ProviderError("gemini's page could not be read before sending: {}".format(
                type(exc).__name__))

        listeners = (("response", on_response), ("requestfinished", on_finished),
                     ("requestfailed", on_failed))
        for event, handler in listeners:
            page.on(event, handler)
        started = time.time()
        self.last_cancelled_thread = thread_url
        self._phase("waiting")
        try:
            self._send(page, prompt)
            self._sent_on = page
            announced = stopping_seen = False
            while "how" not in ended and time.time() - started < REPLY_TIMEOUT:
                page.wait_for_timeout(1000)
                self._check_stop()
                stopping = page.locator(STOP_BUTTON).count() > 0
                if (streams or stopping) and not announced:
                    self._phase("reply started")
                    announced = True
                # A StreamGenerate that ends still ends the turn; without one, the button it showed
                # going away does.
                if stopping:
                    stopping_seen = True
                elif stopping_seen:
                    ended.setdefault("how", "page")
            # Let the events that queued while the stream ran be delivered.
            page.wait_for_timeout(2000)
            waited = 0
            while not self._thread_id(page) and waited < THREAD_WAIT:
                page.wait_for_timeout(1000)
                waited += 1
        except JobCancelled:
            # Already sent: wait for the thread's address so the api can remove it, not leave it.
            waited = 0
            while not self._thread_id(page) and waited < THREAD_WAIT:
                page.wait_for_timeout(1000)
                waited += 1
            if self._thread_id(page):
                self.last_cancelled_thread = page.url
            raise
        finally:
            for event, handler in listeners:
                try:
                    page.remove_listener(event, handler)
                except Exception:
                    pass

        self.last_stream = {"how": ended.get("how"), "streams": len(streams),
                            "pictures seen": len(candidates)}
        landed = "{}/{}".format(HOME, self._thread_id(page)) if self._thread_id(page) else None
        if "how" not in ended:
            self.last_settle = "timeout"
            return GenerationResult(success=False, thread_url=landed, error_kind="provider_timeout",
                                    error="gemini did not finish within {}s".format(REPLY_TIMEOUT))
        self.last_settle = "page" if ended["how"] == "page" else "server"
        if ended["how"] not in ("finished", "page"):
            raise ProviderError("gemini's stream broke off: {}".format(ended["how"]))
        if ended["how"] == "finished":
            response = next((s for s in streams if s.request is ended["request"]),
                            streams[0] if streams else None)
            status = response.status if response is not None else None
            if status != 200:
                raise ProviderError("gemini refused the turn: its stream answered {}".format(status))

        # The server says the turn is over; the words are the answer the page painted after THIS
        # turn's own question, once they hold still for a second. Earlier turns sit above that
        # question however late they paint, so none of them can pass for this turn's answer.
        words = query_words(prompt)
        text, last, found = "", None, {}
        if ended["how"] == "page":
            # Ended by the button alone: its words may paint long after it (ANSWER_WAIT), so
            # nothing is read before they, a picture or a note show.
            painted_by = time.time() + ANSWER_WAIT
            while time.time() < painted_by:
                try:
                    found = page.evaluate(ANSWER_AFTER_QUERY, [words, before]) or {}
                except Exception as exc:
                    raise ProviderError("gemini's page went away while the answer was read: {}".format(
                        type(exc).__name__))
                if ((found.get("text") or "").strip() or (found.get("note") or "").strip()
                        or any(is_generated_picture(e["url"], e["type"], 1) for e in candidates)):
                    break
                page.wait_for_timeout(1000)
                self._check_stop()
        for _ in range(10):
            try:
                found = page.evaluate(ANSWER_AFTER_QUERY, [words, before]) or {}
            except Exception as exc:
                raise ProviderError("gemini's page went away while the answer was read: {}".format(
                    type(exc).__name__))
            text = (found.get("text") or "").strip()
            if text and text == last:
                break
            last = text
            page.wait_for_timeout(1000)
        clip = found.get("video") or ""

        pictures = []
        self.last_pictures = [(urlparse(e["url"]).path[:11], e["type"][:12], e["note"] or len(e["body"]))
                              for e in candidates]
        for e in candidates:
            if is_generated_picture(e["url"], e["type"], len(e["body"])) and e["body"] not in pictures:
                pictures.append(e["body"])
        if not pictures:
            # Every generated picture arrived without its bytes: fetch those urls again inside
            # this session. Only /rd-gg-dl/ urls, which only a picture generated here uses.
            for url in dict.fromkeys(e["url"] for e in candidates
                                     if is_generated_picture(e["url"], e["type"], 1)):
                try:
                    fetched = self._context.request.get(url, timeout=30000)
                    body = fetched.body() if fetched.ok else b""
                except Exception:
                    body = b""
                if body and body not in pictures:
                    pictures.append(body)
        media = []
        for body in pictures:
            filename = "gemini-{}.jpg".format(uuid.uuid4().hex)
            (self.media_path / filename).write_bytes(body)
            media.append(MediaArtifact(filename=filename, type="image",
                                       metadata={"prompt": prompt[:500], "source": "gemini",
                                                 "size": len(body)}))
        if media:
            self._phase("picture appeared")
        # The turn went out and its thread exists: a failure from here on hands the thread back.
        try:
            if not text and not media and not clip and (found.get("note") or "").strip():
                text, clip = self._await_video(page, words, before, landed)
                landed = self._landed(page) or landed
                if not text and not clip:
                    return GenerationResult(success=False, thread_url=landed, error_kind="provider_timeout",
                                            error="gemini was still making the video after {}s".format(
                                                VIDEO_WAIT))
            if clip:
                media.append(self._keep_video(clip, prompt))
        except ProviderError as exc:
            return GenerationResult(success=False, thread_url=self._landed(page) or landed,
                                    error_kind=exc.kind, error=str(exc))
        if not text and not media:
            return GenerationResult(success=False, thread_url=landed, error_kind="provider_timeout",
                                    error="gemini's turn carried neither words nor a picture")
        # Its markup and Gemini's stored record are an ordinary answer's: the words are the only sign.
        if not media and self._flat(text) in FAILURE_SENTENCES:
            return GenerationResult(success=False, thread_url=landed, error_kind="provider_error",
                                    error="gemini answered only with its own failure sentence: {!r}".format(
                                        self._flat(text)))
        return GenerationResult(success=True, text=text, media=media, thread_url=landed)

    def _landed(self, page) -> Optional[str]:
        try:
            thread = self._thread_id(page)
        except Exception:
            return None
        return "{}/{}".format(HOME, thread) if thread else None

    def _await_video(self, page, words, before, landed):
        """(the words, the video's address) once the answer that said it was making a video holds
        one; (the words, "") once it settles on words with no player instead; ("", "") when
        VIDEO_WAIT runs out. A stop hands the turn's thread back for removal."""
        self._phase("making a video")
        deadline = time.time() + VIDEO_WAIT
        last, steady = None, 0
        while time.time() < deadline:
            page.wait_for_timeout(2000)
            try:
                self._check_stop()
            except JobCancelled:
                self.last_cancelled_thread = self._landed(page) or landed or self.last_cancelled_thread
                raise
            try:
                found = page.evaluate(ANSWER_AFTER_QUERY, [words, before]) or {}
                if found.get("video"):
                    page.wait_for_timeout(1000)
                    found = page.evaluate(ANSWER_AFTER_QUERY, [words, before]) or found
            except Exception as exc:
                raise ProviderError("gemini's page went away while its video was made: {}".format(
                    type(exc).__name__))
            text = (found.get("text") or "").strip()
            if found.get("video"):
                return text, found["video"]
            # Words and no player, unchanged over three reads: the answer is words after all.
            steady = steady + 1 if (text and text == last and not found.get("player")) else 0
            if steady >= 2:
                return text, ""
            last = text
        return "", ""

    def _keep_video(self, url: str, prompt: str) -> MediaArtifact:
        """The video fetched inside this session (its address works nowhere else) and kept."""
        try:
            parsed = urlparse(url)
            scheme, host = parsed.scheme, parsed.hostname
        except ValueError:
            scheme = host = None
        if scheme != "https" or host != VIDEO_HOST:
            raise ProviderError("gemini's video is not on https://{} but on {}://{}".format(
                VIDEO_HOST, scheme, host))
        try:
            fetched = self._context.request.get(url, timeout=60000)
            status, body = fetched.status, (fetched.body() if fetched.ok else b"")
        except Exception as exc:
            raise ProviderError("gemini's video could not be fetched: {}".format(type(exc).__name__))
        if body[4:8] != b"ftyp":
            raise ProviderError("gemini's video came back as no video: status {}, {} bytes".format(
                status, len(body)))
        filename = "gemini-{}.mp4".format(uuid.uuid4().hex)
        (self.media_path / filename).write_bytes(body)
        self._phase("video appeared")
        return MediaArtifact(filename=filename, type="video",
                             metadata={"prompt": prompt[:500], "source": "gemini", "size": len(body)})

    # --- threads ---------------------------------------------------------------------

    def _thread_shows(self, page) -> Optional[bool]:
        """Whether the thread just opened is there: its turns paint (True), or the page sends it
        back to /app (False), 0.5 to 0.9s after the composer shows (measured 2026-09-27). None if
        neither happens, as when the session is sent to Google's sign-in."""
        deadline = time.time() + HISTORY_WAIT
        while time.time() < deadline:
            if page.locator("user-query").count():
                return True
            if page.url.split("?")[0].rstrip("/") == HOME:
                return False
            page.wait_for_timeout(250)
        return None

    def delete_thread(self, thread_url: str) -> bool:
        """The row's own menu, its delete item and the dialog's matching button (measured).

        A thread that no longer exists is sent back to /app, which counts as gone.
        """
        cid = self._thread_id(type("AtUrl", (), {"url": thread_url or ""})())
        if not cid:
            return True
        page = self._ensure_page()
        page.goto("{}/{}".format(HOME, cid), timeout=90000, wait_until="domcontentloaded")
        if is_blocked(page.url):
            raise ProviderError(BLOCKED)
        self._composer_ready(page, 30)
        shows = self._thread_shows(page)
        if shows is False:
            return True
        if shows is None:
            raise ProviderError("gemini thread {} neither opened nor went back to /app".format(cid[:8]))
        link = page.locator('a[href="/app/{}"]'.format(cid)).first
        deadline = time.time() + LIST_WAIT
        while not link.count() and time.time() < deadline:
            page.wait_for_timeout(250)
        if not link.count():
            raise ProviderError("gemini thread {} has no row to delete from".format(cid[:8]))
        title = (link.inner_text() or "").strip()
        # This conversation's own row: a plain div ancestor holds every row in the list.
        row = link.locator('xpath=ancestor::*[@data-test-id="conversation"][1]')
        buttons = row.locator("button")
        if not buttons.count():
            raise ProviderError("gemini offered no delete for {}".format(cid[:8]))
        if title and title not in (buttons.first.get_attribute("aria-label") or ""):
            raise ProviderError("gemini's row menu for {} did not name it".format(cid[:8]))
        # Shown only under the pointer, which the list moving after it paints defeats (measured).
        buttons.first.dispatch_event("click")
        item = page.locator('[role="menuitem"][data-test-id*="delete"]')
        if not item.count():
            raise ProviderError("gemini offered no delete for {}".format(cid[:8]))
        # The confirm button repeats the menu item's own word, whatever the language.
        word = (item.first.inner_text() or "").strip()
        item.first.click(timeout=10000)
        page.wait_for_timeout(1500)
        confirm = page.locator("mat-dialog-container").first.locator("button")
        for i in range(confirm.count()):
            if (confirm.nth(i).inner_text() or "").strip() == word:
                confirm.nth(i).click(timeout=10000)
                page.wait_for_timeout(2500)
                page.goto("{}/{}".format(HOME, cid), timeout=90000, wait_until="domcontentloaded")
                if is_blocked(page.url):
                    raise ProviderError(BLOCKED)
                self._composer_ready(page, 30)
                if self._thread_shows(page) is False:
                    return True
                raise ProviderError("gemini thread {} still opens after delete".format(cid[:8]))
        raise ProviderError("gemini's delete dialog for {} had no matching button".format(cid[:8]))

    # --- the three job kinds ---------------------------------------------------------

    def chat(self, message: str, history: Optional[list] = None,
             thread_url: Optional[str] = None) -> GenerationResult:
        prompt = message
        if history and not thread_url:
            lines = ["{}: {}".format(turn["role"], turn["content"]) for turn in history]
            prompt = ("Here is our conversation so far.\n\n" + "\n\n".join(lines)
                      + "\n\nReply to this next message only:\n" + message)
        return self._run(prompt, thread_url=thread_url)

    def generate_image(self, prompt: str, reference_filename: Optional[str] = None,
                       thread_url: Optional[str] = None) -> GenerationResult:
        instruction = "Generate an image: {}".format(prompt)
        if reference_filename:
            instruction = ("Using the attached image as the character reference, generate a new "
                           "image: {}").format(prompt)
        result = self._run(instruction, upload=reference_filename, thread_url=thread_url)
        # Measured 2026-10-29 and 31: asked for a picture, Gemini can answer in words alone ("Normally I can
        # help with things like this, but I don't seem to have access to that content"). No picture, no credit.
        if result.success and not result.media:
            return GenerationResult(success=False, thread_url=result.thread_url, error_kind="provider_error",
                                    error="gemini made no picture and said: {}".format(self._flat(result.text)[:300]))
        return result

    def generate_video_script(self, image_filename: str, duration: int = 5,
                              thread_url: Optional[str] = None) -> GenerationResult:
        instruction = (
            "Write a Wan 2.2 video prompt of {} seconds for the attached image. "
            "Describe camera movement, character animation and ambient motion. "
            "Answer with a single paragraph under 150 words and nothing else."
        ).format(duration)
        return self._run(instruction, upload=image_filename, thread_url=thread_url)
