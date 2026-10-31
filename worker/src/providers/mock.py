import base64
import hashlib
import io
import struct
import time
import uuid
import zipfile
import zlib
from typing import Optional

from src.config import settings
from src.providers.base import (MEMORY_ON_ERROR, BaseProvider, FeatureType, GenerationResult,
                                JobCancelled, MediaArtifact, ProviderError)

IMAGE_WORDS = ("image", "picture", "draw", "ảnh", "vẽ")
FILE_WORDS = ("zip", "archive", "nén")
# Phrases that make the mock misbehave on purpose, so the failure paths can be
# exercised without a real provider.
SLOW_PHRASE = "take your time"
BROKEN_PHRASE = "pretend the provider broke"
MEMORY_PHRASE = "pretend memory is on"
UNSENT_PHRASE = "wait before you speak"
SILENT_PHRASE = "and say nothing of it"
LYING_PHRASE = "and call it unsent"
# A driver that calls a turn done with neither words nor media (the safety plan, 2026-10-21).
EMPTY_PHRASE = "answer with nothing"
# A picture request answered in words, as a provider that will not draw answers it.
WORDS_ONLY_PHRASE = "answer in words only"
# Gemini makes a video when asked for one (2026-10-06); the mock answers this phrase with a clip.
VIDEO_PHRASE = "make a short video"
SLOW_SECONDS = 6.0
LIE_SECONDS = 2.5

# One second of 64x64 H.264 that a browser plays: ffmpeg -f lavfi -i color=c=0x2a9d8f:s=64x64:d=1:r=10
# -c:v libx264 -pix_fmt yuv420p -bsf:v filter_units=remove_types=6 -map_metadata -1 -fflags +bitexact
# -flags:v +bitexact -movflags +faststart
TINY_MP4 = base64.b64decode(
    "AAAAIGZ0eXBpc29tAAACAGlzb21pc28yYXZjMW1wNDEAAAONbW9vdgAAAGxtdmhkAAAAAAAAAAAAAAAAAAAD6AAA"
    "A+gAAQAAAQAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAgAAAtx0cmFrAAAAXHRraGQAAAADAAAAAAAAAAAAAAABAAAAAAAAA+gAAAAAAAAAAAAA"
    "AAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAAEAAAABAAAAAAAAkZWR0cwAAABxlbHN0"
    "AAAAAAAAAAEAAAPoAAAIAAABAAAAAAJUbWRpYQAAACBtZGhkAAAAAAAAAAAAAAAAAAAoAAAAKABVxAAAAAAALWhk"
    "bHIAAAAAAAAAAHZpZGUAAAAAAAAAAAAAAABWaWRlb0hhbmRsZXIAAAAB/21pbmYAAAAUdm1oZAAAAAEAAAAAAAAA"
    "AAAAACRkaW5mAAAAHGRyZWYAAAAAAAAAAQAAAAx1cmwgAAAAAQAAAb9zdGJsAAAAv3N0c2QAAAAAAAAAAQAAAK9h"
    "dmMxAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAAAEAAQABIAAAASAAAAAAAAAABDExhdmMgbGlieDI2NAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAGP//AAAANWF2Y0MBZAAK/+EAGGdkAAqs2UQmwEQAAAMABAAAAwBQPEiWWAEABmjr48siwP34"
    "+AAAAAAQcGFzcAAAAAEAAAABAAAAFGJ0cnQAAAAAAAAFUAAAAAAAAAAYc3R0cwAAAAAAAAABAAAACgAABAAAAAAU"
    "c3RzcwAAAAAAAAABAAAAAQAAAGBjdHRzAAAAAAAAAAoAAAABAAAIAAAAAAEAABQAAAAAAQAACAAAAAABAAAAAAAA"
    "AAEAAAQAAAAAAQAAFAAAAAABAAAIAAAAAAEAAAAAAAAAAQAABAAAAAABAAAIAAAAABxzdHNjAAAAAAAAAAEAAAAB"
    "AAAACgAAAAEAAAA8c3RzegAAAAAAAAAAAAAACgAAACoAAAAOAAAADAAAAAwAAAAMAAAAFAAAAA4AAAAMAAAADAAA"
    "ABQAAAAUc3RjbwAAAAAAAAABAAADvQAAAD11ZHRhAAAANW1ldGEAAAAAAAAAIWhkbHIAAAAAAAAAAG1kaXJhcHBs"
    "AAAAAAAAAAAAAAAACGlsc3QAAAAIZnJlZQAAALJtZGF0AAAAJmWIhAAR//7n4/wKTmHw/nZAJz9bXcqLo1x7Yoza"
    "kvH3bhD2xGfxAAAACkGaJGxBD/6qV94AAAAIQZ5CeId/Bb0AAAAIAZ5hdEN/B3wAAAAIAZ5jakN/B30AAAAQQZpo"
    "SahBaJlMCHf//qmdNQAAAApBnoZFESw7/wW9AAAACAGepXRDfwd9AAAACAGep2pDfwd8AAAAEEGaqUmoQWyZTAhv"
    "//6nj4g="
)


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
        # The account-level switch the real provider reads before every turn.
        # A message can flip it on; the next ordinary message flips it back.
        self.memory = "off"
        self.deleted_threads = []
        self.slow_to_delete = set()
        self.last_cancelled_thread = None
        self.last_stop = None

    def delete_thread(self, thread_url: str) -> bool:
        if thread_url in self.slow_to_delete:
            # A misreported turn's thread stays a while, so a gate can be seen waiting for it.
            time.sleep(LIE_SECONDS)
        self.deleted_threads.append(thread_url)
        return True

    def start(self) -> None:
        return None

    def _refuse_if_memory_on(self):
        if self.memory == "on":
            raise ProviderError(MEMORY_ON_ERROR, kind="provider_misconfigured")

    def _pace(self, seconds: Optional[float] = None, interruptible: bool = True):
        """Sleep in small steps so a cancel lands within a quarter second."""
        total = settings.mock_delay if seconds is None else seconds
        deadline = time.time() + total
        while time.time() < deadline:
            if interruptible:
                self._check_stop()
            time.sleep(min(0.25, max(0.0, deadline - time.time())))
        if interruptible:
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
        self.memory = "on" if MEMORY_PHRASE in lowered else "off"
        self._refuse_if_memory_on()
        if UNSENT_PHRASE in lowered:
            # Like ChatGPT since 4536183: a job taken away before its turn went out never sends
            # it, so no thread is made, and the driver's stop record is the only word on that.
            # Two more phrases play a driver not to be believed: one that keeps silent, and one
            # that says unsent of a turn whose thread it reports a moment later.
            self.last_cancelled_thread = None
            try:
                self._pace(SLOW_SECONDS)
            except JobCancelled:
                if SILENT_PHRASE not in lowered:
                    self.last_stop = {"sent": False, "pressed": False, "at": round(time.time(), 1)}
                if LYING_PHRASE in lowered:
                    time.sleep(LIE_SECONDS)
                    self.last_cancelled_thread = self._thread(thread_url)
                    self.slow_to_delete.add(self.last_cancelled_thread)
                raise
        # Like the real site, the thread exists the moment the message is sent,
        # cancelled or not; the api learns of it either way.
        thread = self._thread(thread_url)
        self.last_cancelled_thread = thread
        if EMPTY_PHRASE in lowered:
            # Whitespace only: words to a naive check, nothing to a person.
            self._pace()
            return GenerationResult(success=True, thread_url=thread, text="  \n", media=[])
        if SLOW_PHRASE in lowered and any(word in lowered for word in IMAGE_WORDS):
            # A slow picture is saved first and finishes whatever happens, like
            # a provider that completes after the platform gave up on the job;
            # what the api then refuses, the runner has to remove.
            picture = self._store(solid_png(64, 64, (220, 60, 60)), ".png", "image", message)
            self._pace(interruptible=False)
            self._pace(SLOW_SECONDS, interruptible=False)
            self._phase("picture appeared")
            return GenerationResult(
                success=True, thread_url=thread,
                text="mock image for: {} [thread={}]".format(message.strip()[:120], thread),
                media=[picture],
            )
        self._pace()
        if SLOW_PHRASE in lowered:
            self._pace(SLOW_SECONDS)
        if BROKEN_PHRASE in lowered:
            return GenerationResult.failure(
                "mock provider showed its error banner", kind="provider_error")

        self._phase("reply started")

        # The real provider answers with whatever the request calls for, in the
        # same chat turn. A mock that only ever replies in text cannot reach the
        # media paths at all.
        if any(word in lowered for word in FILE_WORDS):
            self._phase("file appeared")
            # Shaped like the real reply: a bold sandbox link the interface must
            # render as text, since the file is already a card of its own.
            return GenerationResult(
                success=True, thread_url=thread,
                text=("Đã gói xong. [**Tải file a_b.zip**](sandbox:/mnt/data/a_b.zip) "
                      "mock archive for: {} [thread={}]").format(message.strip()[:120], thread),
                media=[self._store(two_file_zip(), ".zip", "file", message)],
            )
        if VIDEO_PHRASE in lowered:
            self._phase("video appeared")
            return GenerationResult(
                success=True, thread_url=thread,
                text="mock video for: {} [thread={}]".format(message.strip()[:120], thread),
                media=[self._store(TINY_MP4, ".mp4", "video", message)],
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
        self._refuse_if_memory_on()
        thread = self._thread(thread_url)
        self.last_cancelled_thread = thread
        self._pace()
        if BROKEN_PHRASE in prompt.lower():
            return GenerationResult.failure("mock provider showed its error banner", kind="provider_error")
        if WORDS_ONLY_PHRASE in prompt.lower():
            return GenerationResult(success=True, thread_url=thread, text="Please upload the  previous picture.", media=[])
        # Says what reached it, so the gate can tell the exact picture a person sent was handed over.
        seen = ""
        # One name, or a list of them (issue #22): each is said in the order handed over.
        for name in [reference_filename] if isinstance(reference_filename, str) else reference_filename or []:
            reference = self.media_path / name
            if not reference.is_file():
                return GenerationResult.failure("the reference picture is missing", kind="provider_error")
            blob = reference.read_bytes()
            seen += " with reference {} bytes sha256 {}".format(len(blob), hashlib.sha256(blob).hexdigest()[:16])
        self._phase("picture appeared")
        return GenerationResult(
            success=True, thread_url=thread,
            # The thread too, as chat() says it, so a gate sees a follow-up land in its thread (#21).
            text="mock image for: {}{} [thread={}]".format(prompt.strip()[:200], seen, thread),
            media=[self._store(solid_png(64, 64, (220, 60, 60)), ".png", "image", prompt)],
        )

    def generate_video_script(self, image_filename: str, duration: int = 5,
                              thread_url: Optional[str] = None) -> GenerationResult:
        self._refuse_if_memory_on()
        thread = self._thread(thread_url)
        self.last_cancelled_thread = thread
        self._pace()
        self._phase("reply started")
        return GenerationResult(
            success=True, thread_url=thread,
            text=(
                "mock {}-second script for {}: slow dolly in, subtle character motion, "
                "ambient background movement, consistent lighting.".format(duration, image_filename)
            ),
        )
