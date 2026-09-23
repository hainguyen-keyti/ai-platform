import json
import uuid

from fastapi import HTTPException

from src.config import settings
from src.db.client import db, many, one
from src.models import PROVIDERS

HISTORY_LIMIT = 10


def _rollback(conn):
    try:
        conn.execute("ROLLBACK")
    except Exception:
        pass


def _resolve_media(conn, user_id, media_id):
    row = one(conn, "SELECT * FROM media WHERE id = ? AND user_id = ?", (media_id, user_id))
    if not row:
        raise HTTPException(status_code=404, detail="media not found")
    return row


def _history(conn, conversation_id):
    if not conversation_id:
        return []
    rows = many(
        conn,
        "SELECT role, content FROM messages WHERE conversation_id = ?"
        " ORDER BY created_at DESC, rowid DESC LIMIT ?",
        (conversation_id, HISTORY_LIMIT),
    )
    return list(reversed(rows))


def create_job(user, provider, feature, payload, conversation_id=None,
               user_message=None, title=None, reference_media_id=None, media_id=None):
    """Insert a job and everything that must land with it, in one transaction."""
    if provider not in PROVIDERS:
        raise HTTPException(status_code=400, detail="unknown provider {}".format(provider))

    job_id = uuid.uuid4().hex
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            fresh = one(conn, "SELECT quota_remaining FROM users WHERE id = ?", (user["id"],))
            if not fresh or fresh["quota_remaining"] <= 0:
                raise HTTPException(status_code=402, detail="quota exhausted")

            if conversation_id:
                owned = one(
                    conn,
                    "SELECT id FROM conversations WHERE id = ? AND user_id = ?",
                    (conversation_id, user["id"]),
                )
                if not owned:
                    raise HTTPException(status_code=404, detail="conversation not found")
            else:
                conversation_id = uuid.uuid4().hex
                conn.execute(
                    "INSERT INTO conversations (id, user_id, provider, title) VALUES (?, ?, ?, ?)",
                    (conversation_id, user["id"], provider, (title or "New chat")[:80]),
                )

            if reference_media_id:
                payload["reference_filename"] = _resolve_media(
                    conn, user["id"], reference_media_id)["filename"]
            if media_id:
                payload["filename"] = _resolve_media(conn, user["id"], media_id)["filename"]

            if user_message:
                conn.execute(
                    "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, 'user', ?)",
                    (uuid.uuid4().hex, conversation_id, user_message),
                )

            if feature == "chat":
                payload["history"] = _history(conn, conversation_id)[:-1] or []

            conn.execute(
                "UPDATE users SET quota_remaining = quota_remaining - 1 WHERE id = ?",
                (user["id"],),
            )
            conn.execute(
                "INSERT INTO jobs (id, user_id, conversation_id, provider, feature, payload)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (job_id, user["id"], conversation_id, provider, feature, json.dumps(payload)),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = datetime('now') WHERE id = ?",
                (conversation_id,),
            )
            conn.execute("COMMIT")
        except Exception:
            _rollback(conn)
            raise

    return {"job_id": job_id, "conversation_id": conversation_id}


def claim_next_job():
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = one(
                conn,
                "SELECT id, provider, feature, payload FROM jobs"
                " WHERE status = 'pending' ORDER BY created_at, rowid LIMIT 1",
            )
            if row:
                conn.execute(
                    "UPDATE jobs SET status = 'running', started_at = datetime('now') WHERE id = ?",
                    (row["id"],),
                )
            conn.execute("COMMIT")
        except Exception:
            _rollback(conn)
            raise
    if not row:
        return None
    row["payload"] = json.loads(row["payload"])
    return row


def record_result(job_id, status, text, media, error):
    media_ids = []
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            job = one(conn, "SELECT * FROM jobs WHERE id = ?", (job_id,))
            if not job:
                raise HTTPException(status_code=404, detail="job not found")
            if job["status"] in ("done", "failed"):
                conn.execute("COMMIT")
                return json.loads(job["result"]) if job["result"] else {}

            for item in media or []:
                media_id = uuid.uuid4().hex
                conn.execute(
                    "INSERT INTO media (id, user_id, conversation_id, provider, type, prompt,"
                    " filename, metadata) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        media_id,
                        job["user_id"],
                        job["conversation_id"],
                        job["provider"],
                        item.get("type") or "image",
                        (json.loads(job["payload"]) or {}).get("prompt"),
                        item["filename"],
                        json.dumps(item.get("metadata") or {}),
                    ),
                )
                media_ids.append(media_id)

            if status == "done" and text and job["conversation_id"]:
                conn.execute(
                    "INSERT INTO messages (id, conversation_id, role, content)"
                    " VALUES (?, ?, 'assistant', ?)",
                    (uuid.uuid4().hex, job["conversation_id"], text),
                )

            result = {"text": text or "", "media": media_ids}
            conn.execute(
                "UPDATE jobs SET status = ?, result = ?, error = ?, finished_at = datetime('now')"
                " WHERE id = ?",
                (status, json.dumps(result), error, job_id),
            )
            # A job that produced nothing must not cost the user a credit.
            if status == "failed":
                conn.execute(
                    "UPDATE users SET quota_remaining = quota_remaining + 1 WHERE id = ?",
                    (job["user_id"],),
                )
            conn.execute("COMMIT")
        except Exception:
            _rollback(conn)
            raise
    return {"text": text or "", "media": media_ids}


def get_job(user_id, job_id):
    with db() as conn:
        job = one(conn, "SELECT * FROM jobs WHERE id = ? AND user_id = ?", (job_id, user_id))
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return {
        "id": job["id"],
        "status": job["status"],
        "feature": job["feature"],
        "provider": job["provider"],
        "conversation_id": job["conversation_id"],
        "result": json.loads(job["result"]) if job["result"] else None,
        "error": job["error"],
        "created_at": job["created_at"],
        "finished_at": job["finished_at"],
    }
