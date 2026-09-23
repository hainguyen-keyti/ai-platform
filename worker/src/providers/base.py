from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional


class FeatureType(str, Enum):
    CHAT = "chat"
    IMAGE = "image"
    VIDEO_SCRIPT = "video_script"


@dataclass
class MediaArtifact:
    filename: str
    type: str = "image"
    metadata: dict = field(default_factory=dict)


@dataclass
class GenerationResult:
    success: bool
    text: str = ""
    media: List[MediaArtifact] = field(default_factory=list)
    error: Optional[str] = None
    # Where the provider ended up. Stored against the conversation so the next
    # turn lands in the same thread instead of starting from nothing.
    thread_url: Optional[str] = None

    @classmethod
    def failure(cls, message: str) -> "GenerationResult":
        return cls(success=False, error=message)


class BaseProvider(ABC):
    """One AI service driven through a browser session.

    Every method is synchronous because the underlying browser driver is; the
    runner calls providers from a plain thread and never from an event loop.
    """

    name: str = "base"
    supported_features: tuple = ()

    def __init__(self, media_path: Path, sessions_path: Path):
        self.media_path = Path(media_path)
        self.sessions_path = Path(sessions_path)
        self.media_path.mkdir(parents=True, exist_ok=True)
        self.sessions_path.mkdir(parents=True, exist_ok=True)

    def supports(self, feature: str) -> bool:
        return feature in {f.value for f in self.supported_features}

    @abstractmethod
    def start(self) -> None:
        """Open the session. Raises if the provider cannot be used."""

    @abstractmethod
    def chat(self, message: str, history: Optional[list] = None,
             thread_url: Optional[str] = None) -> GenerationResult:
        ...

    @abstractmethod
    def generate_image(self, prompt: str, reference_filename: Optional[str] = None,
                       thread_url: Optional[str] = None) -> GenerationResult:
        ...

    @abstractmethod
    def generate_video_script(self, image_filename: str, duration: int = 5,
                              thread_url: Optional[str] = None) -> GenerationResult:
        ...

    def stop(self) -> None:
        return None
