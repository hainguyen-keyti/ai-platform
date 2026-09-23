import base64
import re
import time
import uuid
from pathlib import PurePosixPath
from typing import Optional

from src.providers.base import (BaseProvider, FeatureType, GenerationResult, MediaArtifact,
                                ProviderError)

HOME = "https://chatgpt.com/"
TEXTAREA = "#prompt-textarea"
SEND_BUTTON = 'button[data-testid="send-button"]'
STOP_BUTTON = '[data-testid="stop-button"]'
ASSISTANT_TURN = '[data-message-author-role="assistant"]'
UPLOAD_INPUT = "#upload-files"

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
# How long the page must stay quiet and unchanged before the answer counts as
# over. Two seconds was thin: a reply that runs several tools puts the stop
# button away between them, and a pause there reads as an ending.
SETTLE_SECONDS = 6

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
COLLECT_CANDIDATE_IMAGES = """
() => {
    const out = [];
    for (const img of document.querySelectorAll("img")) {
        const src = img.src || "";
        if (!src.includes("estuary") && !src.includes("oaiusercontent")) continue;
        if (img.naturalWidth < 256 || img.naturalHeight < 256) continue;
        const turn = img.closest("[data-message-author-role]");
        if (turn && turn.getAttribute("data-message-author-role") === "user") continue;
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
        .filter((b) => b.closest('[data-message-author-role="assistant"]'))
        .map((b) => (b.textContent || "").trim())
        .filter((t) => t.length > 0 && t.length < 200)
"""


class ChatGPTProvider(BaseProvider):
    """Drives a logged-in chatgpt.com session through cloakbrowser.

    Every job starts a brand new chat. The browser session is shared by all
    platform users, so reusing one thread would leak one user's context into
    another's reply; a fresh chat plus our own history is what keeps them apart.
    """

    name = "chatgpt"
    supported_features = (FeatureType.CHAT, FeatureType.IMAGE, FeatureType.VIDEO_SCRIPT)

    def __init__(self, media_path, sessions_path):
        super().__init__(media_path, sessions_path)
        self.session_file = self.sessions_path / "chatgpt.json"
        self._browser = None
        self._context = None
        self._page = None
        self._access_token = None
        self.last_settle = None

    def start(self) -> None:
        # The browser itself is created on first use: the sync driver is bound to
        # the thread that creates it, and that must be the runner thread.
        if not self.session_file.exists():
            raise RuntimeError(
                "no saved session at {}; run scripts/login_provider.py chatgpt".format(self.session_file)
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

    def _composer_ready(self, page, seconds: float) -> bool:
        deadline = time.time() + seconds
        while time.time() < deadline:
            page.wait_for_timeout(500)
            if page.locator(TEXTAREA).count() and page.locator(TEXTAREA).first.is_visible():
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
            page.goto(thread_url, timeout=90000, wait_until="domcontentloaded")
            if self._composer_ready(page, 45):
                return page
            thread_id = self._thread_id(page) or thread_url.rsplit("/c/", 1)[-1]
            data = self._thread_nodes(page, thread_id)
            status = data.get("status") if data else None
            if status != 404:
                raise ProviderError(
                    "thread {} did not open (server status {})".format(thread_id[:8], status))
        page.goto(HOME, timeout=90000, wait_until="domcontentloaded")
        if self._composer_ready(page, 45):
            return page
        raise ProviderError("composer never appeared; the session is probably logged out")

    def _send(self, page, prompt: str):
        box = page.locator(TEXTAREA).first
        try:
            box.click(timeout=10000)
        except Exception:
            box.focus()
        box.fill(prompt)
        page.wait_for_timeout(300)

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
        return url.rsplit("/c/", 1)[1].split("?")[0].split("#")[0] or None

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
        thread_id = self._thread_id(page)
        if not thread_id:
            return set()
        data = self._thread_nodes(page, thread_id)
        if not data or data.get("status") != 200:
            return set()
        return {n["id"] for n in data["nodes"]}

    def _settle_via_server(self, page, baseline_ids: set, deadline: float):
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
        while time.time() < deadline:
            page.wait_for_timeout(1000)
            self._check_stop()
            thread_id = self._thread_id(page)
            if not thread_id:
                if time.time() - started > NO_THREAD_GRACE:
                    return None
                continue
            # While the page shows the model still working, the server has
            # nothing new to say; ask it only when the page looks finished.
            if page.locator(STOP_BUTTON).count() or time.time() < started + START_FLOOR:
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
            answers = [n for n in fresh if n["role"] == "assistant"]
            if not answers:
                continue
            if not announced:
                self._phase("reply started")
                announced = True
            last = answers[-1]
            if last["status"] == "finished_successfully" and last.get("end_turn"):
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
        # nothing.
        preferred = SANDBOX_PATH.findall(answers[-1]["text"] or "")
        candidates = preferred or SANDBOX_PATH.findall(
            "\n".join(n["text"] for n in fresh if n["text"]))
        paths = []
        for match in candidates:
            if match not in paths and PurePosixPath(match).name not in skip_names:
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

    def _await_result(self, page, baseline: int, seen_before, prompt: str, seen_downloads):
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

    def _run(self, prompt: str, upload: Optional[str] = None, thread_url: Optional[str] = None):
        page = self._open(thread_url)
        baseline = page.locator(ASSISTANT_TURN).count()

        if upload:
            path = self.media_path / upload
            if not path.exists():
                return GenerationResult.failure("reference image {} not found".format(upload))
            page.locator(UPLOAD_INPUT).set_input_files(str(path))
            page.wait_for_timeout(3000)

        seen_before = set(page.evaluate(SNAPSHOT_IMAGES))
        seen_downloads = set(page.evaluate(SNAPSHOT_DOWNLOADS))
        baseline_ids = self._baseline_ids(page)
        started = time.time()
        self._send(page, prompt)

        settled = self._settle_via_server(page, baseline_ids, started + REPLY_TIMEOUT)
        if settled is None:
            # No server view here; watch the page the old way.
            self.last_settle = "dom"
            text, media = self._await_result(page, baseline, seen_before, prompt, seen_downloads)
        else:
            self.last_settle = "server"
            text, fresh = settled
            # The server says the turn is over; give the page a moment to paint
            # what it produced, then collect pictures from the page and files
            # from the server. The button click stays only as a fallback.
            page.wait_for_timeout(1500)
            sources = [s for s in page.evaluate(COLLECT_CANDIDATE_IMAGES) if s not in seen_before]
            media = self._download(page, sources, prompt)
            files = self._fetch_sandbox_files(
                page, self._thread_id(page) or "", fresh, prompt, {upload} if upload else set())
            media += files or self._save_files(page, seen_downloads, prompt)

        # Read the address only once the turn is over: a brand new chat is still
        # on the root url until the first message has been sent.
        landed = page.url if "/c/" in page.url else None

        if not text.strip() and not media:
            return GenerationResult(
                success=False, thread_url=landed, error_kind="provider_timeout",
                error="chatgpt returned nothing after {:.0f}s".format(time.time() - started),
            )
        return GenerationResult(success=True, text=text, media=media, thread_url=landed)

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
        if reference_filename:
            instruction = (
                "Using the attached image as the character reference, generate a new image: {}"
            ).format(prompt)
        return self._run(instruction, upload=reference_filename, thread_url=thread_url)

    def generate_video_script(self, image_filename: str, duration: int = 5,
                              thread_url: Optional[str] = None) -> GenerationResult:
        instruction = (
            "Write a Wan 2.2 video prompt of {} seconds for the attached image. "
            "Describe camera movement, character animation and ambient motion. "
            "Answer with a single paragraph under 150 words and nothing else."
        ).format(duration)
        return self._run(instruction, upload=image_filename, thread_url=thread_url)
