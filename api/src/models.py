from typing import Any, Optional

from pydantic import BaseModel, EmailStr, Field

PROVIDERS = ("chatgpt", "grok", "gemini")


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
    text: str = ""
    media: list[WorkerMedia] = Field(default_factory=list)
    error: Optional[str] = None
    thread_url: Optional[str] = Field(default=None, max_length=500)


class QuotaUpdate(BaseModel):
    quota_remaining: int = Field(ge=0, le=1000000)
