import json
from pathlib import PurePosixPath

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse

from src.config import settings
from src.db.client import db, many, one
from src.security import current_user

router = APIRouter(prefix="/media", tags=["media"])

CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".zip": "application/zip",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".json": "application/json",
    ".csv": "text/csv",
}


def _public(row):
    return {
        "id": row["id"],
        "type": row["type"],
        "provider": row["provider"],
        "prompt": row["prompt"],
        "filename": row["filename"],
        "conversation_id": row["conversation_id"],
        "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
        "created_at": row["created_at"],
    }


def _owned(user_id, media_id):
    with db() as conn:
        row = one(conn, "SELECT * FROM media WHERE id = ? AND user_id = ?", (media_id, user_id))
    if not row:
        raise HTTPException(status_code=404, detail="media not found")
    return row


def _safe_path(filename):
    # The name comes from the worker; refuse anything that is not a bare file name.
    name = PurePosixPath(filename).name
    if not name or name != filename or name in (".", ".."):
        raise HTTPException(status_code=400, detail="bad media filename")
    return settings.media_path / name


@router.get("")
def list_media(user: dict = Depends(current_user),
               limit: int = Query(default=100, ge=1, le=500),
               offset: int = Query(default=0, ge=0)):
    with db() as conn:
        total = one(conn, "SELECT COUNT(*) AS n FROM media WHERE user_id = ?", (user["id"],))["n"]
        rows = many(
            conn,
            "SELECT * FROM media WHERE user_id = ? ORDER BY created_at DESC, rowid DESC"
            " LIMIT ? OFFSET ?",
            (user["id"], limit, offset),
        )
    return {"total": total, "items": [_public(r) for r in rows]}


@router.get("/{media_id}")
def get_media(media_id: str, user: dict = Depends(current_user)):
    return _public(_owned(user["id"], media_id))


@router.get("/{media_id}/file")
def get_media_file(media_id: str, user: dict = Depends(current_user)):
    row = _owned(user["id"], media_id)
    path = _safe_path(row["filename"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="file missing on disk")
    return FileResponse(
        str(path),
        media_type=CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream"),
        filename=row["filename"],
    )


@router.delete("/{media_id}", status_code=204)
def delete_media(media_id: str, user: dict = Depends(current_user)):
    row = _owned(user["id"], media_id)
    path = _safe_path(row["filename"])
    with db() as conn:
        conn.execute("DELETE FROM media WHERE id = ? AND user_id = ?", (media_id, user["id"]))
    path.unlink(missing_ok=True)
    return Response(status_code=204)
