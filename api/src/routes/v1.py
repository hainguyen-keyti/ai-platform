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
STATUSES = {"pending": "queued"}


def _picture_kind(head: bytes) -> Optional[str]:
    """The file's own signature decides, never its name or its declared type."""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    return None


def _image_request(user_id: str, request_id: str) -> dict:
    job = get_job(user_id, request_id)
    if job["feature"] != "image":
        raise HTTPException(status_code=404, detail="image request not found")
    return job


@router.post("/images", status_code=202)
def create_image(prompt: str = Form(max_length=8000), image: Optional[UploadFile] = File(default=None),
                 user: dict = Depends(api_key_user)):
    prompt = prompt.strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="a prompt is required")
    upload, path = None, None
    if image is not None:
        picture = image.file.read(MAX_PICTURE_BYTES + 1)
        if len(picture) > MAX_PICTURE_BYTES:
            raise HTTPException(status_code=413, detail="the picture is over 10 MB")
        suffix = _picture_kind(picture[:12])
        if not suffix:
            raise HTTPException(status_code=415, detail="the picture must be a PNG, JPEG or WEBP")
        filename = "upload-{}{}".format(uuid.uuid4().hex, suffix)
        path = settings.media_path / filename
        path.write_bytes(picture)
        upload = {"filename": filename,
                  "metadata": {"source": "upload", "size": len(picture), "name": (image.filename or "")[:120]}}
    try:
        created = create_job(user=user, provider="chatgpt", feature="image", payload={"prompt": prompt},
                             user_message="Generate an image: {}".format(prompt), title=prompt, upload=upload)
    except BaseException:
        # Refused (no credit, nobody serving ChatGPT): the picture sent with it is not kept.
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
