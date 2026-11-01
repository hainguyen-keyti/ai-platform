from typing import Any, Optional

from pydantic import BaseModel, EmailStr, Field

PROVIDERS = ("chatgpt", "grok", "gemini")
# What each provider's driver offers, its `supported_features`; the gate reads both and fails when
# they differ. Grok writes no video script (DECISIONS 2026-09-25).
FEATURES = {
    "chatgpt": ("chat", "image", "video_script", "script"),
    "grok": ("chat", "image", "script"),
    "gemini": ("chat", "image", "video_script", "script"),
}
# The providers whose picture turn takes a reference picture; grok's driver refuses one
# (worker/src/providers/grok.py, generate_image).
TAKES_REFERENCE = ("chatgpt", "gemini")
# How many reference pictures one /v1 picture request may carry (issue #22): ChatGPT's driver attaches
# several through its multiple image input; Gemini's attaches one.
MAX_REFERENCES = {"chatgpt": 4, "gemini": 1}


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    invite_code: str
    name: Optional[str] = Field(default=None, max_length=80)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class ChatRequest(BaseModel):
    provider: str = Field(default="chatgpt")
    message: str = Field(min_length=1, max_length=20000)
    conversation_id: Optional[str] = None


class ImageRequest(BaseModel):
    provider: str = Field(default="chatgpt")
    prompt: str = Field(min_length=1, max_length=8000)
    reference_media_id: Optional[str] = None
    conversation_id: Optional[str] = None


class VideoScriptRequest(BaseModel):
    provider: str = Field(default="chatgpt")
    media_id: str
    duration: int = Field(default=5, ge=1, le=60)
    conversation_id: Optional[str] = None


class WorkerMedia(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    type: str = Field(default="image", max_length=32)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScriptRequest(BaseModel):
    """A video script through /v1 (issue #30). Grok writes them unless told otherwise (the owner, 2026-11-01)."""
    brief: str = Field(min_length=1, max_length=8000)
    target: str = Field(max_length=40)
    provider: str = Field(default="grok", max_length=40)
    scenes: Optional[int] = Field(default=None, ge=1, le=30)
    total_seconds: Optional[int] = Field(default=None, ge=1, le=600)
    language: str = Field(default="vi", min_length=2, max_length=40)
    session: Optional[str] = Field(default=None, max_length=64)


class WorkerResult(BaseModel):
    status: str = Field(pattern="^(done|failed)$")
    # The attempt this result belongs to. A result from an attempt that has since
    # been reclaimed is refused, which is what stops a job settling twice.
    attempt: int = Field(ge=1)
    text: str = ""
    media: list[WorkerMedia] = Field(default_factory=list)
    error: Optional[str] = None
    error_kind: Optional[str] = Field(default=None, max_length=40)
    thread_url: Optional[str] = Field(default=None, max_length=500)
    # How long the account should be left alone, when the provider said (issue #29).
    hold_seconds: Optional[int] = Field(default=None, ge=0, le=604800)


class WorkerPacing(BaseModel):
    """What a worker's runner has spent of its picture budget, told with each claim and ping."""
    images_last_3h: int = Field(ge=0)
    image_budget: int = Field(ge=0)
    budget_free_in: float = Field(default=0, ge=0)


class WorkerClaim(BaseModel):
    providers: list[str] = Field(default_factory=list, max_length=8)
    pacing: Optional[WorkerPacing] = None
    # Which of the provider's accounts asks (issue #29); none means its default account, named as it is.
    account: Optional[str] = Field(default=None, max_length=80)


class WorkerHeartbeat(BaseModel):
    attempt: int = Field(ge=1)


class WorkerProgress(BaseModel):
    attempt: int = Field(ge=1)
    phase: str = Field(min_length=1, max_length=40)


class QuotaUpdate(BaseModel):
    quota_remaining: int = Field(ge=0, le=1000000)
    quota_daily: Optional[int] = Field(default=None, ge=0, le=1000000)


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60, pattern=r"\S")


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=80)


class ThreadsKnown(BaseModel):
    provider: str = Field(max_length=40)
    thread_urls: list[str] = Field(default_factory=list, max_length=100)


class TombstoneResult(BaseModel):
    ok: bool
    error: Optional[str] = Field(default=None, max_length=500)
