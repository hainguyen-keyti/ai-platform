import io
import struct
import time
import uuid
import zipfile
import zlib
from typing import Optional

from src.config import settings
from src.providers.base import BaseProvider, FeatureType, GenerationResult, MediaArtifact

IMAGE_WORDS = ("image", "picture", "draw", "ảnh", "vẽ")
FILE_WORDS = ("zip", "archive", "nén")
# Phrases that make the mock misbehave on purpose, so the failure paths can be
# exercised without a real provider.
SLOW_PHRASE = "take your time"
BROKEN_PHRASE = "pretend the provider broke"
SLOW_SECONDS = 6.0


def solid_png(width: int, height: int, rgb: tuple) -> bytes:
    """A real, decodable PNG without pulling in an image library."""
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def two_file_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("a.txt", "first file\n")
        archive.writestr("b.txt", "second file\n")
    return buffer.getvalue()


class MockProvider(BaseProvider):
    """Stands in for a real service so the rest of the stack can be exercised."""

    supported_features = (FeatureType.CHAT, FeatureType.IMAGE, FeatureType.VIDEO_SCRIPT)

    def __init__(self, media_path, sessions_path, name="chatgpt"):
        super().__init__(media_path, sessions_path)
        self.name = name

    def start(self) -> None:
        return None

    def _pace(self, seconds: Optional[float] = None):
        """Sleep in small steps so a cancel lands within a quarter second."""
        total = settings.mock_delay if seconds is None else seconds
        deadline = time.time() + total
        while time.time() < deadline:
            self._check_stop()
            time.sleep(min(0.25, max(0.0, deadline - time.time())))
        self._check_stop()

    def _thread(self, thread_url: Optional[str]) -> str:
        # Reuse what the caller was given, otherwise open one. This is the whole
        # behaviour under test: same conversation, same thread.
        return thread_url or "mock-thread-{}".format(uuid.uuid4().hex[:12])

    def _store(self, blob: bytes, suffix: str, kind: str, prompt: str) -> MediaArtifact:
        filename = "mock-{}{}".format(uuid.uuid4().hex, suffix)
        (self.media_path / filename).write_bytes(blob)
        return MediaArtifact(filename=filename, type=kind,
                             metadata={"prompt": prompt[:200], "size": len(blob), "mock": True})

    def chat(self, message: str, history: Optional[list] = None,
             thread_url: Optional[str] = None) -> GenerationResult:
        lowered = message.lower()
        self._pace()
        if SLOW_PHRASE in lowered:
            self._pace(SLOW_SECONDS)
        if BROKEN_PHRASE in lowered:
            return GenerationResult.failure(
                "mock provider showed its error banner", kind="provider_error")

        thread = self._thread(thread_url)
        self._phase("reply started")

        # The real provider answers with whatever the request calls for, in the
        # same chat turn. A mock that only ever replies in text cannot reach the
        # media paths at all.
        if any(word in lowered for word in FILE_WORDS):
            self._phase("file appeared")
            return GenerationResult(
                success=True, thread_url=thread,
                text="mock archive for: {} [thread={}]".format(message.strip()[:120], thread),
                media=[self._store(two_file_zip(), ".zip", "file", message)],
            )
        if any(word in lowered for word in IMAGE_WORDS):
            self._phase("picture appeared")
            return GenerationResult(
                success=True, thread_url=thread,
                text="mock image for: {} [thread={}]".format(message.strip()[:120], thread),
                media=[self._store(solid_png(64, 64, (220, 60, 60)), ".png", "image", message)],
            )
        return GenerationResult(
            success=True, thread_url=thread,
            text="mock reply from {} to: {} [thread={}]".format(
                self.name, message.strip()[:160], thread),
        )

    def generate_image(self, prompt: str, reference_filename: Optional[str] = None,
                       thread_url: Optional[str] = None) -> GenerationResult:
        self._pace()
        thread = self._thread(thread_url)
        self._phase("picture appeared")
        return GenerationResult(
            success=True, thread_url=thread,
            text="mock image for: {}".format(prompt.strip()[:200]),
            media=[self._store(solid_png(64, 64, (220, 60, 60)), ".png", "image", prompt)],
        )

    def generate_video_script(self, image_filename: str, duration: int = 5,
                              thread_url: Optional[str] = None) -> GenerationResult:
        self._pace()
        thread = self._thread(thread_url)
        self._phase("reply started")
        return GenerationResult(
            success=True, thread_url=thread,
            text=(
                "mock {}-second script for {}: slow dolly in, subtle character motion, "
                "ambient background movement, consistent lighting.".format(duration, image_filename)
            ),
        )
