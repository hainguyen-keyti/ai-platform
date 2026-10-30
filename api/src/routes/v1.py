import json
import struct
import uuid
from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from src.config import settings
from src.db.client import db, many, one
from src.jobs import cancel_job, create_job, get_job, provider_status
from src.models import FEATURES, MAX_REFERENCES, PROVIDERS, TAKES_REFERENCE
from src.quota import today
from src.routes.media import CONTENT_TYPES, _safe_path
from src.security import api_key_user

# The image API for programs: called with a personal API key only, never a login token.
router = APIRouter(prefix="/v1", tags=["v1"])

MAX_PICTURE_BYTES = 10 * 1024 * 1024
# The whole request: the picture, the prompt and the form's own framing.
MAX_REQUEST_BYTES = MAX_PICTURE_BYTES + 256 * 1024
# A body a little over the limit is read to its end and dropped, so its sender can read the 413
# (answered unread, uvicorn closes on a sender still writing); one declared far over it is refused unread.
MAX_DRAIN_BYTES = 16 * 1024 * 1024
# A small file can claim a huge picture, which the shared browser would then try to decode.
MAX_SIDE, MAX_PIXELS = 16384, 50_000_000
STATUSES = {"pending": "queued"}
JPEG_FRAMES = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
# Segments a decoder reads past before its frame: DHT, DAC, DQT, DRI, COM and APPn. Anything else
# (FF 00 above all, which a decoder skips as stray bytes) could make this walk and a decoder disagree.
JPEG_SEGMENTS = {0xC4, 0xCC, 0xDB, 0xDD, 0xFE} | set(range(0xE0, 0xF0))
JPEG_STEPS = 4096


class RequestLimit:
    """Caps a request to /v1/images before anything keeps it, with or without a key: whether its length
    is declared or not, a body over the limit is refused with 413 and none of it is kept."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path, root = scope.get("path", ""), scope.get("root_path", "")
        if root and path.startswith(root):
            path = path[len(root):]
        if scope["type"] != "http" or path != "/v1/images":
            return await self.app(scope, receive, send)
        declared = dict(scope.get("headers") or []).get(b"content-length", b"")
        length = int(declared) if declared.isdigit() else None
        seen = 0

        async def limited():
            nonlocal seen
            if length is not None and length > MAX_DRAIN_BYTES:
                raise HTTPException(status_code=413, detail="the request is over 10 MB")
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > MAX_REQUEST_BYTES or (length or 0) > MAX_REQUEST_BYTES:
                    more = message.get("more_body", False)
                    while more and seen <= MAX_DRAIN_BYTES:
                        message = await receive()
                        seen += len(message.get("body", b""))
                        more = message.get("more_body", False)
                    raise HTTPException(status_code=413, detail="the request is over 10 MB")
            return message

        await self.app(scope, limited, send)


def _picture_size(picture: bytes):
    """(suffix, width, height) from the picture's own header, never its name or declared type;
    None when it is not a PNG, JPEG or WEBP whose size can be read."""
    if picture.startswith(b"\x89PNG\r\n\x1a\n"):
        if len(picture) >= 24 and picture[12:16] == b"IHDR":
            return (".png",) + struct.unpack(">II", picture[16:24])
        return None
    if picture.startswith(b"\xff\xd8\xff"):
        at = 2
        for _ in range(JPEG_STEPS):
            if at + 4 > len(picture) or picture[at] != 0xFF:
                return None
            marker = picture[at + 1]
            if marker == 0xFF:
                at += 1
            elif marker == 0x01 or 0xD0 <= marker <= 0xD7:
                at += 2
            elif marker in JPEG_FRAMES:
                if at + 9 > len(picture):
                    return None
                height, width = struct.unpack(">HH", picture[at + 5:at + 9])
                return ".jpg", width, height
            elif marker in JPEG_SEGMENTS:
                at += 2 + struct.unpack(">H", picture[at + 2:at + 4])[0]
            else:
                return None
        return None
    if picture[:4] == b"RIFF" and picture[8:12] == b"WEBP" and len(picture) >= 30:
        chunk = picture[12:16]
        if chunk == b"VP8X":
            return (".webp", 1 + int.from_bytes(picture[24:27], "little"),
                    1 + int.from_bytes(picture[27:30], "little"))
        if chunk == b"VP8L" and picture[20] == 0x2F:
            bits = int.from_bytes(picture[21:25], "little")
            return ".webp", (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if chunk == b"VP8 " and picture[23:26] == b"\x9d\x01\x2a":
            return (".webp", int.from_bytes(picture[26:28], "little") & 0x3FFF,
                    int.from_bytes(picture[28:30], "little") & 0x3FFF)
    return None


def _image_request(user_id: str, request_id: str) -> dict:
    """A request made through /v1, and only that: not the web's own picture or chat turns."""
    job = get_job(user_id, request_id)
    with db() as conn:
        row = one(conn, "SELECT payload FROM jobs WHERE id = ? AND user_id = ?", (request_id, user_id))
    made_here = bool(row) and json.loads(row["payload"] or "{}").get("via") == "v1"
    if job["feature"] != "image" or not made_here:
        raise HTTPException(status_code=404, detail="image request not found")
    job["continued_from"] = json.loads(row["payload"] or "{}").get("continued_from")
    return job


@router.get("/providers")
def providers(user: dict = Depends(api_key_user)):
    """Which providers a worker serves now, and what each does for /v1/images (issue #16)."""
    served = {p["name"]: p["served"] for p in provider_status()["providers"]}
    return {"providers": [{"name": name, "served": served.get(name, False),
                           "makes_pictures": "image" in FEATURES[name],
                           "takes_reference": name in TAKES_REFERENCE} for name in PROVIDERS]}


@router.get("/account")
def account(user: dict = Depends(api_key_user)):
    """The credits left today and when they come back (issue #20). api_key_user has already done the
    day's refill, so the first read of a new day shows the refilled balance, not yesterday's leftover."""
    return {"credits_left": user["quota_remaining"], "credits_daily": user.get("quota_daily"),
            "refills_at": "{}T00:00:00Z".format((date.fromisoformat(today()) + timedelta(days=1)).isoformat())}


@router.post("/images", status_code=202)
def create_image(prompt: str = Form(max_length=8000), image: Optional[List[UploadFile]] = File(default=None),
                 provider: str = Form(default="chatgpt", max_length=40),
                 continue_from: Optional[str] = Form(default=None, max_length=64),
                 user: dict = Depends(api_key_user)):
    prompt = prompt.strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="a prompt is required")
    # Refused before the picture is read or kept: a provider that is not there, and a reference
    # picture to one whose picture turn takes none (issue #16).
    if provider not in PROVIDERS:
        raise HTTPException(status_code=400, detail="unknown provider {!r}; one of {}".format(
            provider[:40], ", ".join(PROVIDERS)))
    images = image or []
    if images and provider not in TAKES_REFERENCE:
        raise HTTPException(status_code=400, detail="{} takes no reference picture; use {}".format(
            provider, " or ".join(TAKES_REFERENCE)))
    # Issue #22: up to four for chatgpt, in the order sent; one for gemini.
    if len(images) > MAX_REFERENCES.get(provider, 0):
        raise HTTPException(status_code=400, detail="{} takes at most {} reference picture(s); {} were sent".format(
            provider, MAX_REFERENCES.get(provider, 0), len(images)))
    # Issue #21: a request continues an earlier done /v1 request of the same person and provider in
    # that request's conversation, so the worker sends it into the stored thread. Refused before the
    # picture is read or kept, and before anything is charged.
    conversation_id = None
    if continue_from:
        earlier = _image_request(user["id"], continue_from)
        if earlier["status"] != "done":
            raise HTTPException(status_code=409, detail="request {} is {}; only a done request can be continued".format(
                continue_from, STATUSES.get(earlier["status"], earlier["status"])))
        if earlier["provider"] != provider:
            raise HTTPException(status_code=409, detail="request {} was made by {}; continue it with {}".format(
                continue_from, earlier["provider"], earlier["provider"]))
        conversation_id = earlier["conversation_id"]
    # Every picture is checked before any is kept.
    uploads, kept = [], []
    for given in images:
        picture = given.file.read(MAX_PICTURE_BYTES + 1)
        if len(picture) > MAX_PICTURE_BYTES:
            raise HTTPException(status_code=413, detail="the picture is over 10 MB")
        size = _picture_size(picture)
        if not size or not size[1] or not size[2]:
            raise HTTPException(status_code=415, detail="the picture must be a PNG, JPEG or WEBP")
        suffix, width, height = size
        if max(width, height) > MAX_SIDE or width * height > MAX_PIXELS:
            raise HTTPException(status_code=413, detail="the picture is over {} pixels a side or {} megapixels".format(
                MAX_SIDE, MAX_PIXELS // 1_000_000))
        filename = "upload-{}{}".format(uuid.uuid4().hex, suffix)
        uploads.append({"filename": filename, "picture": picture,
                        "metadata": {"source": "upload", "size": len(picture), "width": width, "height": height,
                                     "name": (given.filename or "")[:120]}})
    try:
        for upload in uploads:
            path = settings.media_path / upload["filename"]
            path.write_bytes(upload.pop("picture"))
            kept.append(path)
        payload = {"prompt": prompt, "via": "v1"}
        if conversation_id:
            payload["continued_from"] = continue_from
        created = create_job(user=user, provider=provider, feature="image", payload=payload,
                             conversation_id=conversation_id,
                             user_message="Generate an image: {}".format(prompt), title=prompt, upload=uploads)
    except BaseException:
        # Refused (no credit, nobody serving the provider) or a write that failed: no picture is kept.
        for path in kept:
            path.unlink(missing_ok=True)
        raise
    return {"id": created["job_id"], "status": "queued"}


@router.get("/images/{request_id}")
def image_status(request_id: str, user: dict = Depends(api_key_user)):
    job = _image_request(user["id"], request_id)
    result = job["result"] or {}
    ids = result.get("media") or []
    with db() as conn:
        rows = {r["id"]: r for r in many(
            conn, "SELECT id, filename FROM media WHERE user_id = ? AND id IN ({})".format(
                ", ".join("?" * len(ids))), (user["id"], *ids))} if ids else {}
    images = []
    for media_id in ids:
        row = rows.get(media_id)
        path = _safe_path(row["filename"]) if row else None
        if path is None or not path.exists():
            continue
        images.append({
            "id": media_id,
            "url": "/v1/images/{}/files/{}".format(job["id"], media_id),
            "content_type": CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream"),
            "bytes": path.stat().st_size,
        })
    return {
        "id": job["id"],
        "provider": job["provider"],
        "continued_from": job["continued_from"],
        "status": STATUSES.get(job["status"], job["status"]),
        "text": result.get("text") or "",
        "error": job["error"],
        "images": images,
        "created_at": job["created_at"],
        "finished_at": job["finished_at"],
    }


@router.post("/images/{request_id}/cancel")
def cancel_image(request_id: str, user: dict = Depends(api_key_user)):
    """Cancel a request made through /v1, queued or running, and give its credit back once; one
    already over is left as it ended (issue #20). The web's own jobs stay out of reach, as on reads."""
    _image_request(user["id"], request_id)
    cancel_job(user["id"], request_id)
    return image_status(request_id, user)


@router.get("/images/{request_id}/files/{media_id}")
def image_file(request_id: str, media_id: str, user: dict = Depends(api_key_user)):
    job = _image_request(user["id"], request_id)
    # Only what this request made: not the picture sent with it, not another request's.
    if media_id not in ((job["result"] or {}).get("media") or []):
        raise HTTPException(status_code=404, detail="picture not found")
    with db() as conn:
        row = one(conn, "SELECT filename FROM media WHERE id = ? AND user_id = ?", (media_id, user["id"]))
    path = _safe_path(row["filename"]) if row else None
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="picture not found")
    return FileResponse(str(path), media_type=CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream"),
                        filename=path.name)
