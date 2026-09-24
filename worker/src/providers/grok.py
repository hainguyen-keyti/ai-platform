import base64
import json
import re
import time
import uuid
from typing import Optional

from src.providers.base import (BaseProvider, FeatureType, GenerationResult, JobCancelled,
                                MediaArtifact, ProviderError)

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
SERVER_POLL_SECONDS = 2
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

PAGE_ASSETS = """
() => Array.from(document.querySelectorAll('img'))
        .map((i) => i.currentSrc || i.src)
        .filter((s) => s && s.indexOf('assets.grok.com/users/') !== -1)
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

    def __init__(self, media_path, sessions_path):
        super().__init__(media_path, sessions_path)
        self.session_file = self.sessions_path / "grok.json"
        self._browser = None
        self._context = None
        self._page = None
        self.last_settle = None
        self.last_open = None
        self.last_cancelled_thread = None

    def start(self) -> None:
        if not self.session_file.exists():
            raise RuntimeError(
                "no saved session at {}; run scripts/login_provider.py grok".format(self.session_file)
            )

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
    def thread_id(url: Optional[str]) -> Optional[str]:
        if not url or "/c/" not in url:
            return None
        return url.rsplit("/c/", 1)[1].split("?")[0].split("#")[0] or None

    def _api(self, page, path, method="GET", body=None):
        got = page.evaluate(FETCH, [path, method, json.dumps(body) if body is not None else None])
        return got.get("status"), got.get("body") or ""

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

    def _dismiss_cookie_dialog(self, page):
        # The dialog can sit over the composer. Its own reject or close control
        # only; the platform never accepts optional cookies on someone's behalf.
        for sel in ("#onetrust-reject-all-handler", "#onetrust-close-btn-container button",
                    "button[aria-label='Close']"):
            try:
                if page.locator(sel).count() and page.locator(sel).first.is_visible():
                    page.locator(sel).first.click(timeout=3000)
                    return
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
        """The sidebar only lists threads for an account; an anonymous page has none."""
        status, _ = self._api(page, "/rest/app-chat/conversations?pageSize=1")
        return status == 200

    def _open(self, thread_url: Optional[str] = None):
        page = self._ensure_page()
        wanted = self.thread_id(thread_url)
        target = "{}c/{}".format(HOME, wanted) if wanted else HOME

        for attempt in range(OPEN_ATTEMPTS):
            page.goto(target, timeout=90000, wait_until="domcontentloaded")
            cleared = self._wait_for_challenge(page)
            self._dismiss_cookie_dialog(page)
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
                    target = HOME
                    continue
            if attempt + 1 < OPEN_ATTEMPTS:
                self._phase("waiting for the provider")
                time.sleep(OPEN_RETRY_SECONDS * (2 ** attempt))
        raise ProviderError(
            "grok did not open {}: cleared={} landed={}".format(
                (wanted or "a new chat")[:8], (self.last_open or {}).get("cleared"),
                (self.last_open or {}).get("landed")))

    def _send(self, page, composer, prompt: str):
        box = page.locator(composer).first
        box.click(timeout=15000)
        page.keyboard.type(prompt)
        page.wait_for_timeout(400)
        page.keyboard.press("Enter")

    def _server_turn(self, page, cid, baseline_ids):
        """The newest assistant turn as the server tells it, and whether it is done."""
        status, raw = self._api(page, SERVER_TURNS.format(cid))
        if status != 200:
            return None, False, status
        try:
            body = json.loads(raw)
        except ValueError:
            return None, False, status
        answers = [r for r in (body.get("responses") or [])
                   if r.get("sender") == "assistant" and r.get("responseId") not in baseline_ids]
        if not answers:
            return None, False, status
        last = answers[-1]
        if last.get("partial"):
            return last, False, status
        node_status, node_raw = self._api(page, SERVER_NODES.format(cid))
        try:
            inflight = json.loads(node_raw).get("inflightResponses") if node_status == 200 else None
        except ValueError:
            inflight = None
        return last, inflight == [], status

    def _baseline_ids(self, page, cid):
        if not cid:
            return set()
        status, raw = self._api(page, SERVER_TURNS.format(cid))
        if status != 200:
            return set()
        try:
            body = json.loads(raw)
        except ValueError:
            return set()
        return {r.get("responseId") for r in (body.get("responses") or [])}

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

    def _run(self, prompt: str, thread_url: Optional[str] = None):
        self.last_cancelled_thread = None
        page, composer = self._open(thread_url)
        self.last_cancelled_thread = thread_url

        cid = self.thread_id(page.url)
        baseline_ids = self._baseline_ids(page, cid)
        started = time.time()
        self._phase("waiting")
        try:
            self._send(page, composer, prompt)
            deadline = started + REPLY_TIMEOUT
            turn, settled = None, False
            announced = False
            while time.time() < deadline:
                page.wait_for_timeout(SERVER_POLL_SECONDS * 1000)
                self._check_stop()
                if not cid:
                    cid = self.thread_id(page.url)
                    if cid:
                        self.last_cancelled_thread = "{}c/{}".format(HOME, cid)
                    elif time.time() - started > THREAD_WAIT:
                        raise ProviderError("grok never opened a thread for this turn")
                    continue
                turn, settled, status = self._server_turn(page, cid, baseline_ids)
                if status in (401, 403):
                    raise ProviderError(
                        "grok refused to report the turn (status {})".format(status))
                if turn and not announced:
                    self._phase("reply started")
                    announced = True
                if settled:
                    break
        except JobCancelled:
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

        text = GROK_RENDER.sub("", turn.get("message") or "").strip()
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
