from typing import Any, Optional

from pydantic import BaseModel, EmailStr, Field

PROVIDERS = ("chatgpt", "grok", "gemini")
# What each provider's driver offers, its `supported_features`; the gate reads both and fails when
# they differ. Grok writes no video script (DECISIONS 2026-09-25).
FEATURES = {
    "chatgpt": ("chat", "image", "video_script"),
    "grok": ("chat", "image"),
    "gemini": ("chat", "image", "video_script"),
}
# The providers whose picture turn takes a reference picture; grok's driver refuses one
# (worker/src/providers/grok.py, generate_image).
TAKES_REFERENCE = ("chatgpt", "gemini")


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


class WorkerClaim(BaseModel):
    providers: list[str] = Field(default_factory=list, max_length=8)


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


class TombstoneResult(BaseModel):
    ok: bool
    error: Optional[str] = Field(default=None, max_length=500)
