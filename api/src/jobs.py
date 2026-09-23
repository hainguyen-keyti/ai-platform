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
                "SELECT j.id, j.provider, j.feature, j.payload,"
                " c.provider_thread_url AS thread_url"
                " FROM jobs j LEFT JOIN conversations c ON c.id = j.conversation_id"
                " WHERE j.status = 'pending' ORDER BY j.created_at, j.rowid LIMIT 1",
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


def record_result(job_id, status, text, media, error, thread_url=None):
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

            # Remember where the provider put this conversation so the next turn
            # lands in the same place and can build on this one.
            if thread_url and job["conversation_id"]:
                conn.execute(
                    "UPDATE conversations SET provider_thread_url = ? WHERE id = ?",
                    (thread_url, job["conversation_id"]),
                )

            # The message comes first so its pictures can point at it. Without
            # that link the gallery strip floats loose at the end of the thread
            # instead of sitting where the answer was given.
            message_id = None
            if status == "done" and job["conversation_id"] and (text or media):
                message_id = uuid.uuid4().hex
                conn.execute(
                    "INSERT INTO messages (id, conversation_id, role, content)"
                    " VALUES (?, ?, 'assistant', ?)",
                    (message_id, job["conversation_id"], text or ""),
                )

            for item in media or []:
                media_id = uuid.uuid4().hex
                conn.execute(
                    "INSERT INTO media (id, user_id, conversation_id, message_id, provider, type,"
                    " prompt, filename, metadata) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        media_id,
                        job["user_id"],
                        job["conversation_id"],
                        message_id,
                        job["provider"],
                        item.get("type") or "image",
                        (json.loads(job["payload"]) or {}).get("prompt"),
                        item["filename"],
                        json.dumps(item.get("metadata") or {}),
                    ),
                )
                media_ids.append(media_id)

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
