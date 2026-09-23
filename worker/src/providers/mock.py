import struct
import time
import uuid
import zlib
from typing import Optional

from src.config import settings
from src.providers.base import BaseProvider, FeatureType, GenerationResult, MediaArtifact


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


class MockProvider(BaseProvider):
    """Stands in for a real service so the rest of the stack can be exercised."""

    supported_features = (FeatureType.CHAT, FeatureType.IMAGE, FeatureType.VIDEO_SCRIPT)

    def __init__(self, media_path, sessions_path, name="chatgpt"):
        super().__init__(media_path, sessions_path)
        self.name = name

    def start(self) -> None:
        return None

    def _pace(self):
        if settings.mock_delay > 0:
            time.sleep(settings.mock_delay)

    def chat(self, message: str, history: Optional[list] = None) -> GenerationResult:
        self._pace()
        # The real provider answers a request for a picture with a picture, no
        # matter which words the user used to ask. A mock that always replies in
        # text cannot cover that path at all.
        if any(word in message.lower() for word in ("image", "picture", "draw", "ảnh", "vẽ")):
            return self.generate_image(message)
        return GenerationResult(
            success=True,
            text="mock reply from {} to: {}".format(self.name, message.strip()[:200]),
        )

    def generate_image(self, prompt: str, reference_filename: Optional[str] = None) -> GenerationResult:
        self._pace()
        filename = "mock-{}.png".format(uuid.uuid4().hex)
        (self.media_path / filename).write_bytes(solid_png(64, 64, (220, 60, 60)))
        return GenerationResult(
            success=True,
            text="mock image for: {}".format(prompt.strip()[:200]),
            media=[MediaArtifact(filename=filename, type="image",
                                 metadata={"width": 64, "height": 64, "mock": True})],
        )

    def generate_video_script(self, image_filename: str, duration: int = 5) -> GenerationResult:
        self._pace()
        return GenerationResult(
            success=True,
            text=(
                "mock {}-second script for {}: slow dolly in, subtle character motion, "
                "ambient background movement, consistent lighting.".format(duration, image_filename)
            ),
        )
