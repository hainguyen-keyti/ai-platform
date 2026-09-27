import re
import time
import unicodedata
import uuid
from typing import Optional
from urllib.parse import urlparse

from src.providers.base import (BaseProvider, FeatureType, GenerationResult, JobCancelled,
                                MediaArtifact, ProviderError)

# Everything below was measured on the owner's account on 2026-09-25 and 2026-09-27; see
# docs/research/2026-09-27-gemini.md. The interface is Vietnamese, so nothing keys on words.
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
# Where a signed-out session is sent instead of the settings page.
SIGNED_OUT_PATH = "/saved-info"
SWITCH = 'button[role="switch"]'
# The upload control carries no data-test-id, only a localised label: the weakest selector here.
UPLOAD_CONTROL = ("button[aria-label*='Nội dung tải lên']", "button[aria-label*='Upload']")
UPLOAD_INPUT = 'input[type="file"][accept="image/*"]'
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
    if (!after.length) return {query: true, text: ''};
    const content = after[after.length - 1].querySelector('message-content');
    return {query: true, text: content ? (content.innerText || '') : ''};
}
"""

REPLY_TIMEOUT = 300
THREAD_WAIT = 30
# A reopened thread paints its earlier turns a moment after the composer shows.
HISTORY_WAIT = 20
# So does the conversation list its rows (0.3 to 2.4s, measured 2026-09-27).
LIST_WAIT = 15
OPEN_ATTEMPTS = 2
UPLOAD_WAIT = 30
SETTINGS_WAIT = 15

SIGNED_OUT = "the gemini session is signed out; run scripts/login_provider.py gemini"
PERSONAL_CONTEXT_ON = ("the shared Gemini account has personal context switched on, so this turn "
                       "was not sent; ask the account owner to turn it off "
                       "(gemini.google.com/personalization-settings) and try again")


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


class GeminiProvider(BaseProvider):
    """Drives the owner's gemini.google.com session through cloakbrowser.

    The page signs its own calls (a WAA handshake), so turns are typed into it. The server's word
    that a turn is over is its StreamGenerate response finishing; pictures are caught from the
    network while the turn runs, because reopening the thread does not fetch them again.
    """

    name = "gemini"
    supported_features = (FeatureType.CHAT, FeatureType.IMAGE, FeatureType.VIDEO_SCRIPT)

    def __init__(self, media_path, sessions_path):
        super().__init__(media_path, sessions_path)
        self.session_file = self.sessions_path / "gemini.json"
        self._browser = None
        self._context = None
        self._page = None
        self.last_settle = None
        self.last_open = None
        self.last_cancelled_thread = None
        self.last_stream = None
        self.last_pictures = []
        self.memory = None

    def start(self) -> None:
        if not self.session_file.exists():
            raise RuntimeError(
                "no saved session at {}; run scripts/login_provider.py gemini".format(self.session_file))

    def stop(self) -> None:
        if self._context is not None:
            try:
                self._context.storage_state(path=str(self.session_file))
            except Exception:
                pass
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
        self._browser = self._context = self._page = None

    def _ensure_page(self):
        if self._page is not None:
            return self._page
        import cloakbrowser

        self._browser = cloakbrowser.launch(headless=True)
        self._context = self._browser.new_context(storage_state=str(self.session_file))
        self._page = self._context.new_page()
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

    # --- the leak switch -------------------------------------------------------------

    def _read_personal_context(self) -> str:
        """The personal context switch as the settings page shows it: on, off, unknown or signed-out.

        Read in a tab of its own, so the conversation's page is never moved. Only a page that
        stayed on /personalization-settings is read: a signed-out session lands on /saved-info,
        whose own switches are not this one.
        """
        self.memory = "unknown"
        page = self._context.new_page()
        try:
            page.goto(SETTINGS_URL, timeout=60000, wait_until="domcontentloaded")
            deadline = time.time() + SETTINGS_WAIT
            off_site = False
            while time.time() < deadline:
                page.wait_for_timeout(500)
                landed = urlparse(page.url or "")
                path = landed.path.rstrip("/")
                # Sent to /saved-info (measured): no account.
                if path == SIGNED_OUT_PATH:
                    self.memory = "signed-out"
                    return self.memory
                # Off the site, to Google's sign-in: no account, unless it comes back, which a
                # cookie refresh passing through Google would (re-review, 2026-09-27).
                off_site = bool(landed.hostname and landed.hostname != GEMINI_HOST)
                if path != SETTINGS_PATH:
                    continue
                switches = page.locator(SWITCH)
                if switches.count() == 1:
                    checked = switches.first.get_attribute("aria-checked")
                    self.memory = {"true": "on", "false": "off"}.get(checked, "unknown")
                    return self.memory
            if off_site:
                self.memory = "signed-out"
            return self.memory
        except Exception:
            return self.memory
        finally:
            try:
                page.close()
            except Exception:
                pass

    def _guard(self):
        """Look before speaking. On refuses; signed out refuses; unknown does not block."""
        state = self._read_personal_context()
        if state == "signed-out":
            raise ProviderError(SIGNED_OUT, kind="provider_misconfigured")
        if state == "on":
            raise ProviderError(PERSONAL_CONTEXT_ON, kind="provider_misconfigured")

    # --- opening and typing ------------------------------------------------------------

    def _open(self, thread_url: Optional[str] = None):
        page = self._ensure_page()
        wanted = self._thread_id(type("AtUrl", (), {"url": thread_url or ""})())
        target = "{}/{}".format(HOME, wanted) if wanted else HOME
        for attempt in range(OPEN_ATTEMPTS):
            page.goto(target, timeout=90000, wait_until="domcontentloaded")
            ready = self._composer_ready(page, 30)
            landed = self._thread_id(page)
            self.last_open = {"wanted": (wanted or "new")[:8], "composer": ready,
                              "landed": (landed or page.url)[:60], "attempt": attempt + 1}
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
        page.keyboard.press("Enter")

    def _attach(self, page, filename: str):
        path = self.media_path / filename
        if not path.exists():
            raise ProviderError("reference image {} not found".format(filename), kind="worker_error")
        if not page.locator(UPLOAD_INPUT).count():
            for sel in UPLOAD_CONTROL:
                if page.locator(sel).count():
                    page.locator(sel).first.click(timeout=10000)
                    break
            page.wait_for_timeout(1500)
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
            announced = False
            while "how" not in ended and time.time() - started < REPLY_TIMEOUT:
                page.wait_for_timeout(1000)
                self._check_stop()
                if streams and not announced:
                    self._phase("reply started")
                    announced = True
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
        self.last_settle = "server"
        if ended["how"] != "finished":
            raise ProviderError("gemini's stream broke off: {}".format(ended["how"]))
        response = next((s for s in streams if s.request is ended["request"]),
                        streams[0] if streams else None)
        status = response.status if response is not None else None
        if status != 200:
            raise ProviderError("gemini refused the turn: its stream answered {}".format(status))

        # The server says the turn is over; the words are the answer the page painted after THIS
        # turn's own question, once they hold still for a second. Earlier turns sit above that
        # question however late they paint, so none of them can pass for this turn's answer.
        words = query_words(prompt)
        text, last = "", None
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
        if not text and not media:
            return GenerationResult(success=False, thread_url=landed, error_kind="provider_timeout",
                                    error="gemini's turn carried neither words nor a picture")
        return GenerationResult(success=True, text=text, media=media, thread_url=landed)

    # --- threads ---------------------------------------------------------------------

    def delete_thread(self, thread_url: str) -> bool:
        """The row's own menu, its delete item and the dialog's matching button (measured).

        A thread that no longer exists opens back on /app, which counts as gone.
        """
        cid = self._thread_id(type("AtUrl", (), {"url": thread_url or ""})())
        if not cid:
            return True
        page = self._ensure_page()
        page.goto("{}/{}".format(HOME, cid), timeout=90000, wait_until="domcontentloaded")
        self._composer_ready(page, 30)
        if self._thread_id(page) != cid:
            return True
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
                self._composer_ready(page, 30)
                if self._thread_id(page) != cid:
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
        return self._run(instruction, upload=reference_filename, thread_url=thread_url)

    def generate_video_script(self, image_filename: str, duration: int = 5,
                              thread_url: Optional[str] = None) -> GenerationResult:
        instruction = (
            "Write a Wan 2.2 video prompt of {} seconds for the attached image. "
            "Describe camera movement, character animation and ambient motion. "
            "Answer with a single paragraph under 150 words and nothing else."
        ).format(duration)
        return self._run(instruction, upload=image_filename, thread_url=thread_url)
