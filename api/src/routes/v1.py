import json
import struct
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from src.config import settings
from src.db.client import db, many, one
from src.jobs import create_job, get_job
from src.routes.media import CONTENT_TYPES, _safe_path
from src.security import api_key_user

# The image API for programs: called with a personal API key only, never a login token.
router = APIRouter(prefix="/v1", tags=["v1"])

MAX_PICTURE_BYTES = 10 * 1024 * 1024
# The whole request: the picture, the prompt and the form's own framing.
MAX_REQUEST_BYTES = MAX_PICTURE_BYTES + 256 * 1024
# Past the limit the rest is read and dropped so the caller gets its 413; past this it is cut off.
MAX_DRAIN_BYTES = 64 * 1024 * 1024
# A small file can claim a huge picture, which the shared browser would then try to decode.
MAX_SIDE, MAX_PIXELS = 16384, 50_000_000
STATUSES = {"pending": "queued"}
JPEG_FRAMES = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


class RequestLimit:
    """Caps a request to /v1/images before anything keeps it, with or without a key: over the limit,
    the rest is dropped as it arrives and the answer is 413."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] != "/v1/images":
            return await self.app(scope, receive, send)
        declared = dict(scope.get("headers") or []).get(b"content-length", b"")
        too_long = declared.isdigit() and int(declared) > MAX_REQUEST_BYTES
        seen = 0

        async def limited():
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if too_long or seen > MAX_REQUEST_BYTES:
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
        while at + 4 <= len(picture):
            if picture[at] != 0xFF:
                return None
            marker = picture[at + 1]
            if marker == 0xFF:
                at += 1
            elif marker == 0x01 or 0xD0 <= marker <= 0xD8:
                at += 2
            elif marker in (0xD9, 0xDA):
                return None
            elif marker in JPEG_FRAMES:
                if at + 9 > len(picture):
                    return None
                height, width = struct.unpack(">HH", picture[at + 5:at + 9])
                return ".jpg", width, height
            else:
                at += 2 + struct.unpack(">H", picture[at + 2:at + 4])[0]
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
    if job["feature"] != "image" or job["provider"] != "chatgpt" or not made_here:
        raise HTTPException(status_code=404, detail="image request not found")
    return job


@router.post("/images", status_code=202)
def create_image(prompt: str = Form(max_length=8000), image: Optional[UploadFile] = File(default=None),
                 user: dict = Depends(api_key_user)):
    prompt = prompt.strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="a prompt is required")
    upload, path, picture = None, None, b""
    if image is not None:
        picture = image.file.read(MAX_PICTURE_BYTES + 1)
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
        path = settings.media_path / filename
        upload = {"filename": filename,
                  "metadata": {"source": "upload", "size": len(picture), "width": width, "height": height,
                               "name": (image.filename or "")[:120]}}
    try:
        if path is not None:
            path.write_bytes(picture)
        created = create_job(user=user, provider="chatgpt", feature="image", payload={"prompt": prompt, "via": "v1"},
                             user_message="Generate an image: {}".format(prompt), title=prompt, upload=upload)
    except BaseException:
        # Refused (no credit, nobody serving ChatGPT) or a write that failed: the picture is not kept.
        if path is not None:
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
        "status": STATUSES.get(job["status"], job["status"]),
        "text": result.get("text") or "",
        "error": job["error"],
        "images": images,
        "created_at": job["created_at"],
        "finished_at": job["finished_at"],
    }


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
