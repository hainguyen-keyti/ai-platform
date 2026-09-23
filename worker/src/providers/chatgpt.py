import base64
import time
import uuid
from pathlib import PurePosixPath
from typing import Optional

from src.providers.base import BaseProvider, FeatureType, GenerationResult, MediaArtifact

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

# A file ChatGPT builds is offered by a button, not a link: there is no href to
# read, and the bytes live behind the same session-bound endpoint as pictures.
# Clicking it and catching the browser download is the only way in.
SNAPSHOT_DOWNLOADS = """
() => Array.from(document.querySelectorAll("button"))
        .map((b) => (b.textContent || "").trim())
        .filter((t) => /^Download\\s+\\S/.test(t))
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

    def _open(self, thread_url: Optional[str] = None):
        """Open the conversation's own thread, or a new one if there is none.

        A stored thread can be gone: deleted in the ChatGPT interface, or
        belonging to an account that no longer has it. Falling back to a fresh
        chat loses the history but keeps the request working.
        """
        page = self._ensure_page()
        for target in ([thread_url] if thread_url else []) + [HOME]:
            page.goto(target, timeout=90000, wait_until="domcontentloaded")
            deadline = time.time() + 45
            while time.time() < deadline:
                page.wait_for_timeout(500)
                if page.locator(TEXTAREA).count() and page.locator(TEXTAREA).first.is_visible():
                    return page
        raise RuntimeError("composer never appeared; the session is probably logged out")

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

            if page.locator(STOP_BUTTON).count():
                stable = 0
                continue
            if time.time() < floor:
                continue

            current = self._reply_text(page, baseline)
            found = [s for s in page.evaluate(COLLECT_CANDIDATE_IMAGES) if s not in seen_before]

            # Nothing yet is not the same as nothing to come: an empty answer
            # never counts as settled, it just keeps the wait going.
            if not current.strip() and not found:
                stable = 0
                continue

            if current == text and found == sources:
                stable += 1
                if stable >= 2:
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
                    page.locator("button").filter(has_text=label).first.click()
                download = caught.value
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
        started = time.time()
        self._send(page, prompt)
        text, media = self._await_result(page, baseline, seen_before, prompt, seen_downloads)

        # Read the address only once the turn is over: a brand new chat is still
        # on the root url until the first message has been sent.
        landed = page.url if "/c/" in page.url else None

        if not text.strip() and not media:
            return GenerationResult(
                success=False, thread_url=landed,
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
