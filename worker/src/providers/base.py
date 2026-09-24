from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional


class FeatureType(str, Enum):
    CHAT = "chat"
    IMAGE = "image"
    VIDEO_SCRIPT = "video_script"


MEMORY_ON_ERROR = ("the provider's memory is on for the shared account, so this turn was not sent; "
                   "turn it off (Settings, Personalization, Enable memory) and try again")


class JobCancelled(Exception):
    """The job being worked on was cancelled or reclaimed; stop and do not report."""


class ProviderError(Exception):
    """The provider itself is unwell: logged out, throttled, showing an error banner.

    kind names the failure for the api and the pool: provider_error by default,
    provider_misconfigured when the account is in a state the platform must not
    speak into, such as memory switched on.
    """

    def __init__(self, message: str, kind: str = "provider_error"):
        super().__init__(message)
        self.kind = kind


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
    # Why it failed, in a form the api and the pool can act on:
    # provider_error, provider_timeout, cancelled, worker_error.
    error_kind: Optional[str] = None
    # Where the provider ended up. Stored against the conversation so the next
    # turn lands in the same thread instead of starting from nothing.
    thread_url: Optional[str] = None

    @classmethod
    def failure(cls, message: str, kind: Optional[str] = None) -> "GenerationResult":
        return cls(success=False, error=message, error_kind=kind)


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
        self._phase_hook = None
        self._stop_hook = None

    def bind(self, phase_hook=None, stop_hook=None):
        """Attach the current job's progress and cancellation channels."""
        self._phase_hook = phase_hook
        self._stop_hook = stop_hook

    def _phase(self, name: str):
        if self._phase_hook:
            try:
                self._phase_hook(name)
            except Exception:
                pass

    def _check_stop(self):
        if self._stop_hook and self._stop_hook():
            raise JobCancelled()

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
