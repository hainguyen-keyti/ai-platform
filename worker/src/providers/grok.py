import base64
import json
import re
import time
import uuid
from typing import Optional

from src.providers.base import (BaseProvider, FeatureType, GenerationResult, JobCancelled,
                                MediaArtifact, ProviderError)
from src.providers.session import NO_SESSION, open_session, profile_of, saved

HOME = "https://grok.com/"

# Measured 2026-09-24: this account gets the ProseMirror composer, an anonymous
# session gets the plain textarea, and both cohorts are live at once. ProseMirror
# ignores fill(), so the send path clicks and types through the keyboard.
COMPOSER = ('[data-testid="chat-input"] .ProseMirror[contenteditable="true"]',
            '.ProseMirror[contenteditable="true"]',
            'textarea[aria-label="Ask Grok anything"]',
            '[data-testid="chat-input"] textarea')

# Cloudflare shows a managed challenge on the whole origin and clears itself in
# about 14 seconds cold, 5 with a warm session. No click is needed, only time.
CHALLENGE_WAIT = 60
CHALLENGE_TEXT = ("security verification", "just a moment", "verify you are human")

REPLY_TIMEOUT = 300
THREAD_WAIT = 45
# A thread that can be read and still lists no question of this turn this long after Enter never
# received it. Measured 2026-10-28 (issue #13): the question is listed at the first read, 4-6s after
# Enter; a turn the server never got was waited on to the ceiling, 321s.
HEARD_WAIT = 30
SERVER_POLL_SECONDS = 2
# A turn that reads finished while it is still empty has not started. Grok
# creates the assistant row before the words arrive, and inflightResponses can
# be empty in that gap, which is exactly how an earlier settle chose nothing.
START_FLOOR = 4
# The read of the thread before a follow-up's send: tries with a doubling pause, as for ChatGPT.
BASELINE_TRIES = 3
BASELINE_PAUSE_SECONDS = 6
# A turn that finishes carrying nothing is a refusal, whatever the cause. Grok
# says nothing about it in any endpoint: measured 2026-09-24, a spent free tier
# leaves the assistant row finished and empty while /rest/rate-limits still
# reports a full window, and only the page says "Free tier limit reached". So
# the shape decides (finished and empty), and the page is quoted for the person.
EMPTY_GRACE = 12
OPEN_ATTEMPTS = 3
OPEN_RETRY_SECONDS = 10
CANCEL_THREAD_WAIT = 15

SERVER_TURNS = "/rest/app-chat/conversations/{}/responses?includeThreads=true"
SERVER_NODES = "/rest/app-chat/conversations/{}/response-node?includeThreads=true"
DELETE_THREAD = "/rest/app-chat/conversations/soft/{}"

# The assistant's text carries the card markup for whatever it drew; a person
# should read the words, not the tag.
GROK_RENDER = re.compile(r"<grok:render[^>]*>.*?</grok:render>|<grok:render[^>]*/?>", re.S)
ASSET_URL = re.compile(r"https://assets\.grok\.com/users/([^/]+)/")

SIGNED_OUT = "the grok session is signed out; run scripts/login_provider.py grok"
MEMORY_ON = ("the shared Grok account has memory switched on, so this turn was not sent; ask the "
             "account owner to turn it off (Settings, Data Controls, Personalize Grok with your "
             "conversation history) and try again")

FETCH = """
async ([path, method, body]) => {
    const opts = {method: method, credentials: 'include'};
    if (body) { opts.headers = {'Content-Type': 'application/json'}; opts.body = body; }
    const r = await fetch(path, opts);
    let t = ''; try { t = await r.text(); } catch (e) {}
    return {status: r.status, body: t};
}
"""

FETCH_AS_DATA_URL = """
async (url) => {
    const r = await fetch(url, {credentials: 'include'});
    if (!r.ok) return null;
    const blob = await r.blob();
    return await new Promise((resolve) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.readAsDataURL(blob);
    });
}
"""

# The origin is compared, not searched for: a page-controlled url like
# https://evil.example/x?assets.grok.com/users/ would otherwise be fetched with
# this session's cookies and stored as the user's own picture.
PAGE_ASSETS = """
() => Array.from(document.querySelectorAll('img'))
        .map((i) => i.currentSrc || i.src)
        .filter((s) => {
            try { const u = new URL(s);
                  return u.origin === 'https://assets.grok.com' && u.pathname.startsWith('/users/'); }
            catch (e) { return false; }
        })
"""


class GrokProvider(BaseProvider):
    """Drives a logged-in grok.com session through cloakbrowser.

    The turn is typed into the page, which is what makes this work at all: every
    write grok.com makes carries an `x-statsig-id` the site mints per request, so
    a request forged from outside the page is refused with 403 code 7. The page
    signs its own send. Reads need no such header, so the state of a turn is read
    from the server and the rendering is only a hint.
    """

    name = "grok"
    # Chat and image for now. A video script uploads a reference picture, and
    # grok's upload flow is a different shape that has not been measured.
    supported_features = (FeatureType.CHAT, FeatureType.IMAGE)
    # Whether the server lists the running turn's question yet; reset by _run before each send.
    heard = False

    def __init__(self, media_path, sessions_path):
        super().__init__(media_path, sessions_path)
        self._context = None
        self._page = None
        self.last_settle = None
        self.last_open = None
        self.last_cancelled_thread = None
        # What the account's memory switch read before the last turn: on, off or unknown.
        self.memory = None

    def start(self) -> None:
        if not saved(self.sessions_path, self.name):
            raise RuntimeError(NO_SESSION.format(profile_of(self.sessions_path, self.name), self.name))

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
        self._context = open_session(self.sessions_path, self.name)
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        return self._page

    @staticmethod
    def thread_id(url: Optional[str]) -> Optional[str]:
        if not url or "/c/" not in url:
            return None
        return url.rsplit("/c/", 1)[1].split("?")[0].split("#")[0] or None

    def _api(self, page, path, method="GET", body=None):
        got = page.evaluate(FETCH, [path, method, json.dumps(body) if body is not None else None])
        return got.get("status"), got.get("body") or ""

    def _read_memory(self, page) -> str:
        """The account's memory switch as the server reports it: on, off or unknown.

        `enableMemory` in /rest/user-settings mirrors Settings, Data Controls, "Personalize Grok
        with your conversation history" (measured 2026-09-27). Anything but a plain true or false
        is unknown, which does not block: the rule decided for ChatGPT and Gemini.
        """
        self.memory = "unknown"
        try:
            status, raw = self._api(page, "/rest/user-settings")
            value = json.loads(raw).get("enableMemory") if status == 200 else None
        except Exception:
            value = None
        if value is True:
            self.memory = "on"
        elif value is False:
            self.memory = "off"
        return self.memory

    def _wait_for_challenge(self, page) -> bool:
        deadline = time.time() + CHALLENGE_WAIT
        while time.time() < deadline:
            page.wait_for_timeout(2000)
            try:
                body = (page.inner_text("body") or "").lower()
            except Exception:
                continue
            if not any(word in body for word in CHALLENGE_TEXT):
                return True
        return False

    def _dismiss_overlays(self, page):
        # Anything that can sit over the composer: the cookie dialog and the
        # product tips. Their own reject or dismiss control only; the platform
        # never accepts optional cookies on someone's behalf.
        for sel in ("#onetrust-reject-all-handler",
                    "#onetrust-banner-sdk button[aria-label='Close']",
                    "#onetrust-close-btn-container button",
                    "[role=dialog] button:has-text('Dismiss')",
                    "[role=dialog] button[aria-label='Close']"):
            try:
                found = page.locator(sel)
                if found.count() and found.first.is_visible():
                    found.first.click(timeout=3000)
                    page.wait_for_timeout(300)
            except Exception:
                continue

    def _composer(self, page, seconds: float = 30):
        deadline = time.time() + seconds
        while time.time() < deadline:
            for sel in COMPOSER:
                try:
                    if page.locator(sel).count() and page.locator(sel).first.is_visible():
                        return sel
                except Exception:
                    continue
            page.wait_for_timeout(1000)
        return None

    def _signed_in(self, page) -> bool:
        """The sidebar only lists threads for an account; an anonymous page has none.

        Only the server refusing the account (401, 403) is signed out. Any other answer is the
        provider unwell for a moment, and must not send the admin to log in again.
        """
        status, _ = self._api(page, "/rest/app-chat/conversations?pageSize=1")
        if status in (401, 403):
            return False
        if status != 200:
            raise ProviderError("grok could not say whether the session is signed in (status {})".format(status))
        return True

    def _open(self, thread_url: Optional[str] = None):
        page = self._ensure_page()
        wanted = self.thread_id(thread_url)
        target = "{}c/{}".format(HOME, wanted) if wanted else HOME

        for attempt in range(OPEN_ATTEMPTS):
            page.goto(target, timeout=90000, wait_until="domcontentloaded")
            cleared = self._wait_for_challenge(page)
            self._dismiss_overlays(page)
            composer = self._composer(page, 30 if cleared else 5)
            landed = self.thread_id(page.url)
            self.last_open = {"wanted": (wanted or "new")[:8], "cleared": cleared,
                              "composer": bool(composer), "landed": (landed or page.url)[:60],
                              "attempt": attempt + 1}
            if composer and (not wanted or landed == wanted):
                if not self._signed_in(page):
                    raise ProviderError(SIGNED_OUT, kind="provider_misconfigured")
                return page, composer
            if wanted:
                status, _ = self._api(page, SERVER_NODES.format(wanted))
                if status == 404:
                    # Gone for good: the only case where a fresh chat is right.
                    # Forget what we were looking for, or the guard above can
                    # never be satisfied and three attempts burn for nothing.
                    wanted, target = None, HOME
                    continue
                # 403 is also what a page still behind the challenge returns, so
                # it alone proves nothing; ask the account, and only when the
                # page itself claimed to be through the challenge.
                if status == 401 or (cleared and status == 403 and not self._signed_in(page)):
                    raise ProviderError(SIGNED_OUT, kind="provider_misconfigured")
            if attempt + 1 < OPEN_ATTEMPTS:
                self._phase("waiting for the provider")
                time.sleep(OPEN_RETRY_SECONDS * (2 ** attempt))
        raise ProviderError(
            "grok did not open {}: cleared={} landed={}".format(
                (self.thread_id(thread_url) or "a new chat")[:8],
                (self.last_open or {}).get("cleared"),
                (self.last_open or {}).get("landed")))

    @staticmethod
    def _flat(text: str) -> str:
        """One line of single spaces, so raw prompt and rendered text compare."""
        return " ".join((text or "").split())

    def _composer_text(self, page, composer) -> str:
        try:
            return self._flat(page.locator(composer).first.inner_text())
        except Exception:
            return ""

    def _clear_composer(self, page, composer):
        try:
            page.locator(composer).first.click(timeout=3000)
            page.keyboard.press("ControlOrMeta+a")
            page.keyboard.press("Backspace")
        except Exception:
            pass

    def _send(self, page, composer, prompt: str):
        """Type the turn and prove it landed before pressing Enter.

        Measured 2026-09-24: a click that hits an overlay leaves the keystrokes
        going nowhere, Enter then sends an empty turn, and grok answers it with
        an assistant row that never fills. Reading the composer back is what
        tells the difference between a send and a silent miss.
        """
        # A ProseMirror renders each line as its own block, so the composer's
        # innerText never equals the prompt character for character: both sides
        # are flattened before they are compared, and a retry starts from an
        # empty box rather than appending to what is already there.
        wanted = self._flat(prompt)[:40]
        for attempt in range(3):
            if attempt:
                self._clear_composer(page, composer)
            self._dismiss_overlays(page)
            # The composer is looked for again at every try. Measured 2026-10-28: a thread opened
            # again first shows a textarea labelled like the composer, the only one there at the
            # open, and mounts the real editor seconds later; the textarea is then gone, and three
            # tries typed into it reached nothing.
            composer = self._composer(page, 10) or composer
            box = page.locator(composer).first
            try:
                box.scroll_into_view_if_needed(timeout=5000)
            except Exception:
                pass
            try:
                box.click(timeout=8000)
            except Exception:
                # Visible but unclickable, usually something painted over it.
                try:
                    box.evaluate("(el) => el.focus()")
                except Exception:
                    pass
            # insert_text, never keyboard.type: Playwright's type() presses a
            # key per character and maps "\n" to Enter, which on grok.com sends.
            # A prompt carrying our replayed history would go out a line at a
            # time, each line spending one of the account's few turns.
            page.keyboard.insert_text(prompt)
            page.wait_for_timeout(500)
            if wanted in self._composer_text(page, composer):
                page.keyboard.press("Enter")
                return
            self._phase("retrying the composer")
            page.wait_for_timeout(1500)
        raise ProviderError("the turn never reached grok's composer")

    @staticmethod
    def _turn_content(turn):
        """What a turn actually carries: words with the card markup removed, and pictures."""
        text = GROK_RENDER.sub("", (turn or {}).get("message") or "").strip()
        assets = [item for item in ((turn or {}).get("fileAttachmentsMetadata")
                                    or (turn or {}).get("fileAttachmentAssetMetadata") or [])
                  if (item.get("fileMimeType") or item.get("mimeType") or "").startswith("image/")]
        return text, assets

    def _server_turn(self, page, cid, baseline_ids):
        """The newest assistant turn as the server tells it, and whether it is done."""
        status, raw = self._api(page, SERVER_TURNS.format(cid))
        if status != 200:
            return None, "working", status
        try:
            body = json.loads(raw)
        except ValueError:
            return None, "working", status
        # Whether the server has this turn's question at all, read by _run (issue #13).
        self.heard = self.heard or any(r.get("sender") == "human" and r.get("responseId") not in baseline_ids
                                       for r in (body.get("responses") or []))
        answers = [r for r in (body.get("responses") or [])
                   if r.get("sender") == "assistant" and r.get("responseId") not in baseline_ids]
        if not answers:
            return None, "working", status
        last = answers[-1]
        if last.get("partial"):
            return last, "working", status
        node_status, node_raw = self._api(page, SERVER_NODES.format(cid))
        try:
            inflight = json.loads(node_raw).get("inflightResponses") if node_status == 200 else None
        except ValueError:
            inflight = None
        if inflight != []:
            return last, "working", status
        text, assets = self._turn_content(last)
        # Finished and empty is not finished: either the words are a moment
        # behind, or the provider refused. The caller waits a little, then says so.
        return last, ("done" if (text or assets) else "empty"), status

    def _baseline_ids(self, page, cid):
        """The ids of every response the thread holds before the send; none for a new conversation.

        A follow-up turn that cannot know them would take the earlier answer for its own (measured
        on a stub, 2026-10-21: a read answering 429 or 500 gave the previous turn's words after 4s),
        so the read is tried again and, still failing, the turn is refused before it is sent.
        """
        if not cid:
            return set()
        pause, status = BASELINE_PAUSE_SECONDS, None
        for attempt in range(BASELINE_TRIES):
            if attempt:
                page.wait_for_timeout(pause * 1000)
                pause *= 2
                self._check_stop()
            try:
                status, raw = self._api(page, SERVER_TURNS.format(cid))
            except Exception as exc:
                # A rejected fetch or a page mid-navigation is a read that failed, tried again; a
                # browser that closed is not, and reaches the pool, which drops it.
                from playwright._impl._errors import is_target_closed_error
                if is_target_closed_error(exc) or "has been closed" in str(exc).lower():
                    raise
                status = type(exc).__name__
                continue
            if status != 200:
                continue
            try:
                ids = {r.get("responseId") for r in (json.loads(raw).get("responses") or [])}
            except (ValueError, AttributeError):
                status = "no json"
                continue
            # A follow-up's thread always holds its earlier turn: a read with no response is no read.
            if ids:
                return ids
            status = "no response"
        self._check_stop()
        raise ProviderError("grok's thread could not be read before sending ({}), so nothing was "
                            "sent".format(status))

    def _assets(self, page, turn, prompt: str):
        """Whatever the turn drew, as bytes, fetched inside the session.

        The server names the assets; the page supplies the account id the asset
        url is built from, because the url is user-scoped and Cloudflare-gated.
        """
        wanted = []
        for item in (turn.get("fileAttachmentsMetadata")
                     or turn.get("fileAttachmentAssetMetadata") or []):
            ident = item.get("fileMetadataId") or item.get("assetId")
            mime = item.get("fileMimeType") or item.get("mimeType") or ""
            if ident and mime.startswith("image/"):
                wanted.append((ident, mime))
        if not wanted:
            return []

        on_page = page.evaluate(PAGE_ASSETS) or []
        owner = None
        for url in on_page:
            found = ASSET_URL.search(url)
            if found:
                owner = found.group(1)
                break

        artifacts = []
        for ident, mime in wanted:
            url = next((u for u in on_page if ident in u), None)
            if not url and owner:
                url = "https://assets.grok.com/users/{}/generated/{}/image.jpg".format(owner, ident)
            if not url:
                continue
            try:
                data_url = page.evaluate(FETCH_AS_DATA_URL, url)
            except Exception:
                continue
            if not data_url or not data_url.startswith("data:"):
                continue
            header, _, payload = data_url.partition(",")
            blob = base64.b64decode(payload)
            suffix = ".png" if "png" in header else ".jpg"
            filename = "grok-{}{}".format(uuid.uuid4().hex, suffix)
            (self.media_path / filename).write_bytes(blob)
            self._phase("picture appeared")
            artifacts.append(MediaArtifact(
                filename=filename, type="image",
                metadata={"prompt": prompt[:500], "source": "grok", "asset": ident,
                          "size": len(blob), "mime": mime}))
        return artifacts

    def _refusal_reason(self, page) -> str:
        """What the page says about a turn that produced nothing, for the person to read."""
        try:
            said = page.evaluate(
                "() => ((document.querySelector('main') || document.body).innerText || '')"
                ".split('\\n').map(s => s.trim()).filter(Boolean).slice(-3).join(' ')")
        except Exception:
            said = ""
        return self._flat(said or "no reason shown")[:120]

    def _run(self, prompt: str, thread_url: Optional[str] = None):
        self.last_cancelled_thread = None
        page, composer = self._open(thread_url)
        # Look before speaking: with memory on, this turn would be remembered for every other user.
        if self._read_memory(page) == "on":
            raise ProviderError(MEMORY_ON, kind="provider_misconfigured")
        self.last_cancelled_thread = thread_url

        cid = self.thread_id(page.url)
        baseline_ids = self._baseline_ids(page, cid)
        self.heard = False
        started = time.time()
        self._phase("waiting")
        try:
            self._send(page, composer, prompt)
            deadline = started + REPLY_TIMEOUT
            turn, settled = None, False
            announced = False
            empty_since = None
            while time.time() < deadline:
                page.wait_for_timeout(SERVER_POLL_SECONDS * 1000)
                self._check_stop()
                if time.time() - started < START_FLOOR:
                    continue
                if not cid:
                    cid = self.thread_id(page.url)
                    if cid:
                        self.last_cancelled_thread = "{}c/{}".format(HOME, cid)
                    elif time.time() - started > THREAD_WAIT:
                        raise ProviderError("grok never opened a thread for this turn")
                    continue
                turn, state, status = self._server_turn(page, cid, baseline_ids)
                if status in (401, 403):
                    raise ProviderError(
                        "grok refused to report the turn (status {})".format(status))
                # Only a read that went through proves the question is missing; one that failed
                # proves nothing and the wait goes on.
                if status == 200 and not self.heard and time.time() - started > HEARD_WAIT:
                    raise ProviderError(
                        "grok never received this turn: its thread lists no question of it {:.0f}s "
                        "after the send".format(time.time() - started))
                if turn and not announced:
                    self._phase("reply started")
                    announced = True
                if state == "empty":
                    empty_since = empty_since or time.time()
                    if time.time() - empty_since > EMPTY_GRACE:
                        raise ProviderError(
                            "grok answered with nothing: {}".format(self._refusal_reason(page)))
                    continue
                empty_since = None
                if state == "done":
                    settled = True
                    break
        except JobCancelled:
            # Already sent: a new chat gets its address seconds later, so wait for it, or the api can
            # neither keep nor remove the thread.
            waited = 0
            while not self.thread_id(page.url) and waited < THREAD_WAIT:
                page.wait_for_timeout(1000)
                waited += 1
            landed = self.thread_id(page.url)
            if landed:
                self.last_cancelled_thread = "{}c/{}".format(HOME, landed)
            raise

        self.last_settle = "server" if settled else "timeout"
        landed = self.thread_id(page.url)
        thread = "{}c/{}".format(HOME, landed) if landed else None
        if not turn:
            return GenerationResult(
                success=False, thread_url=thread, error_kind="provider_timeout",
                error="grok returned nothing after {:.0f}s".format(time.time() - started))

        text, _ = self._turn_content(turn)
        media = self._assets(page, turn, prompt)
        if not text and not media:
            return GenerationResult(
                success=False, thread_url=thread, error_kind="provider_timeout",
                error="grok's turn carried neither words nor a picture")
        return GenerationResult(success=True, text=text, media=media, thread_url=thread)

    def delete_thread(self, thread_url: str) -> bool:
        """Soft delete, which the site answers 404 for a thread already gone."""
        cid = self.thread_id(thread_url)
        if not cid:
            return True
        # Reuse the page that is already on the site: opening a fresh one pays
        # the Cloudflare wait again for what is one call.
        page = self._page
        if page is None or "grok.com" not in (page.url or ""):
            page, _ = self._open()
        status, _ = self._api(page, DELETE_THREAD.format(cid), method="DELETE")
        if status in (200, 204, 404):
            return True
        raise ProviderError("grok did not delete thread {}: status {}".format(cid[:8], status))

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
        if reference_filename:
            raise ProviderError("grok's first driver cannot attach a reference picture",
                                kind="worker_error")
        return self._run("Generate an image: {}".format(prompt), thread_url=thread_url)

    def generate_video_script(self, image_filename: str, duration: int = 5,
                              thread_url: Optional[str] = None) -> GenerationResult:
        raise ProviderError("grok's first driver serves chat and image only", kind="worker_error")
