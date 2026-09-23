import base64
import time
import uuid
from typing import Optional

from src.providers.base import BaseProvider, FeatureType, GenerationResult, MediaArtifact

HOME = "https://chatgpt.com/"
TEXTAREA = "#prompt-textarea"
SEND_BUTTON = 'button[data-testid="send-button"]'
STOP_BUTTON = '[data-testid="stop-button"]'
ASSISTANT_TURN = '[data-message-author-role="assistant"]'
UPLOAD_INPUT = "#upload-files"

CHAT_TIMEOUT = 180
IMAGE_TIMEOUT = 300
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

# Document-wide on purpose. Scoping this to the assistant turn looks tidier but
# missed every generated image in a real run: the result is not always rendered
# inside that element. A reference image the user uploaded is excluded by
# diffing against a snapshot taken before the prompt is sent, not by position.
COLLECT_CANDIDATE_IMAGES = """
() => {
    const out = [];
    for (const img of document.querySelectorAll("img")) {
        const src = img.src || "";
        if (!src.includes("estuary") && !src.includes("oaiusercontent")) continue;
        if (img.naturalWidth < 256 || img.naturalHeight < 256) continue;
        if (!out.includes(src)) out.push(src);
    }
    return out;
}
"""

SNAPSHOT_IMAGES = """
() => Array.from(document.querySelectorAll("img"), (img) => img.src || "")
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

    def _new_chat(self):
        page = self._ensure_page()
        page.goto(HOME, timeout=90000, wait_until="domcontentloaded")
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

    def _await_reply(self, page, baseline: int, timeout: int) -> str:
        """Wait for a new assistant turn to appear and stop changing.

        An image-only reply has no text at all, so "the text stopped changing"
        is true one second after sending, before the model has started. The
        floor below keeps that from being read as a finished reply; past it the
        stop button is what decides.
        """
        deadline = time.time() + timeout
        floor = time.time() + START_FLOOR
        text = ""
        stable = 0
        while time.time() < deadline:
            page.wait_for_timeout(1000)
            turns = page.locator(ASSISTANT_TURN)
            if turns.count() <= baseline:
                continue
            current = turns.last.inner_text()
            if current == text:
                stable += 1
                if stable >= 2 and time.time() > floor and page.locator(STOP_BUTTON).count() == 0:
                    return text
            else:
                text = current
                stable = 0
        return text

    def _text_so_far(self, page, baseline: int) -> str:
        """Whatever the assistant has written by now, without waiting for it."""
        turns = page.locator(ASSISTANT_TURN)
        if turns.count() <= baseline:
            return ""
        try:
            return turns.last.inner_text()
        except Exception:
            return ""

    def _save_images(self, page, prompt: str, deadline: float, seen_before):
        artifacts = []
        sources = []
        while time.time() < deadline:
            sources = [s for s in page.evaluate(COLLECT_CANDIDATE_IMAGES) if s not in seen_before]
            if sources:
                break
            page.wait_for_timeout(2000)

        for source in sources:
            try:
                data_url = page.evaluate(FETCH_AS_DATA_URL, source)
            except Exception:
                continue
            if not data_url or not data_url.startswith("data:"):
                continue
            header, _, payload = data_url.partition(",")
            suffix = ".png" if "png" in header else ".jpg"
            filename = "chatgpt-{}{}".format(uuid.uuid4().hex, suffix)
            (self.media_path / filename).write_bytes(base64.b64decode(payload))
            artifacts.append(
                MediaArtifact(filename=filename, type="image",
                              metadata={"prompt": prompt[:500], "source": "chatgpt"})
            )
        return artifacts

    def _run(self, prompt: str, timeout: int, want_images: bool, upload: Optional[str] = None):
        page = self._new_chat()
        baseline = page.locator(ASSISTANT_TURN).count()

        if upload:
            path = self.media_path / upload
            if not path.exists():
                return GenerationResult.failure("reference image {} not found".format(upload))
            page.locator(UPLOAD_INPUT).set_input_files(str(path))
            page.wait_for_timeout(3000)

        seen_before = set(page.evaluate(SNAPSHOT_IMAGES))

        started = time.time()
        self._send(page, prompt)

        media = []
        if want_images:
            # The picture is the completion signal here. Waiting for the text
            # reply first burned the whole budget every time, because an
            # image-only answer never produces a turn to settle on.
            media = self._save_images(page, prompt, time.time() + IMAGE_TIMEOUT, seen_before)
            text = self._text_so_far(page, baseline)
            if not media:
                # Carry the reply and the elapsed time back: a refusal, a slow
                # render and a wait that never ran look identical without them.
                return GenerationResult(
                    success=False,
                    text=text,
                    error="no image after {:.0f}s; reply was: {}".format(
                        time.time() - started, (text or "(empty)")[:400]
                    ),
                )
        else:
            text = self._await_reply(page, baseline, timeout)

        if not text.strip() and not media:
            return GenerationResult.failure("empty reply from chatgpt")
        return GenerationResult(success=True, text=text, media=media)

    def chat(self, message: str, history: Optional[list] = None) -> GenerationResult:
        prompt = message
        if history:
            lines = ["{}: {}".format(turn["role"], turn["content"]) for turn in history]
            prompt = (
                "Here is our conversation so far.\n\n"
                + "\n\n".join(lines)
                + "\n\nReply to this next message only:\n"
                + message
            )
        return self._run(prompt, CHAT_TIMEOUT, want_images=False)

    def generate_image(self, prompt: str, reference_filename: Optional[str] = None) -> GenerationResult:
        instruction = "Generate an image: {}".format(prompt)
        if reference_filename:
            instruction = (
                "Using the attached image as the character reference, generate a new image: {}"
            ).format(prompt)
        return self._run(instruction, IMAGE_TIMEOUT, want_images=True, upload=reference_filename)

    def generate_video_script(self, image_filename: str, duration: int = 5) -> GenerationResult:
        instruction = (
            "Write a Wan 2.2 video prompt of {} seconds for the attached image. "
            "Describe camera movement, character animation and ambient motion. "
            "Answer with a single paragraph under 150 words and nothing else."
        ).format(duration)
        return self._run(instruction, CHAT_TIMEOUT, want_images=False, upload=image_filename)
