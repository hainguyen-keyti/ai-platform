import json
import uuid

from fastapi import HTTPException

from src.config import settings
from src.db.client import db, many, one
from src.models import PROVIDERS

HISTORY_LIMIT = 10
TERMINAL = ("done", "failed", "cancelled")


def _rollback(conn):
    try:
        conn.execute("ROLLBACK")
    except Exception:
        pass


def _refund(conn, user_id):
    conn.execute(
        "UPDATE users SET quota_remaining = quota_remaining + 1 WHERE id = ?", (user_id,)
    )


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
    """Insert a job and everything that must land with it, in one transaction.

    The single credit is taken here. Every later transition out of a live state
    that produced nothing for the user gives exactly one credit back.
    """
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


def _sweep_stranded(conn):
    """Give expired running jobs back to the queue, or fail them past the cap.

    Runs inside the claim transaction, so the worker asking for work is what
    frees work a dead worker left behind. No separate janitor process.
    """
    stranded = many(
        conn,
        "SELECT id, user_id, attempts FROM jobs"
        " WHERE status = 'running' AND lease_expires_at IS NOT NULL"
        " AND lease_expires_at < datetime('now')",
    )
    for job in stranded:
        if job["attempts"] >= settings.job_max_attempts:
            conn.execute(
                "UPDATE jobs SET status = 'failed', error = ?, error_kind = 'stranded',"
                " lease_expires_at = NULL, finished_at = datetime('now') WHERE id = ?",
                ("the worker lost this job {} times".format(job["attempts"]), job["id"]),
            )
            _refund(conn, job["user_id"])
        else:
            conn.execute(
                "UPDATE jobs SET status = 'pending', lease_expires_at = NULL, phase = 'requeued'"
                " WHERE id = ?",
                (job["id"],),
            )


def claim_next_job():
    lease = "+{} seconds".format(settings.job_lease_seconds)
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            _sweep_stranded(conn)
            row = one(
                conn,
                "SELECT j.id, j.provider, j.feature, j.payload, j.attempts,"
                " c.provider_thread_url AS thread_url"
                " FROM jobs j LEFT JOIN conversations c ON c.id = j.conversation_id"
                " WHERE j.status = 'pending' ORDER BY j.created_at, j.rowid LIMIT 1",
            )
            if row:
                row["attempts"] += 1
                conn.execute(
                    "UPDATE jobs SET status = 'running', attempts = ?, phase = 'claimed',"
                    " started_at = COALESCE(started_at, datetime('now')),"
                    " lease_expires_at = datetime('now', ?) WHERE id = ?",
                    (row["attempts"], lease, row["id"]),
                )
            conn.execute("COMMIT")
        except Exception:
            _rollback(conn)
            raise
    if not row:
        return None
    row["payload"] = json.loads(row["payload"])
    row["attempt"] = row.pop("attempts")
    row["lease_seconds"] = settings.job_lease_seconds
    return row


def _live_attempt(conn, job_id, attempt):
    """The job as it stands, or an explanation of why this attempt may not touch it."""
    job = one(conn, "SELECT * FROM jobs WHERE id = ?", (job_id,))
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if job["status"] != "running":
        raise HTTPException(
            status_code=409, detail="job is {}, this attempt may not change it".format(job["status"])
        )
    if job["attempts"] != attempt:
        raise HTTPException(
            status_code=409,
            detail="attempt {} is stale, the job is on attempt {}".format(attempt, job["attempts"]),
        )
    return job


def heartbeat(job_id, attempt):
    """Renew the lease. Tells the worker whether its attempt is still the live one."""
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            job = one(conn, "SELECT status, attempts FROM jobs WHERE id = ?", (job_id,))
            if not job:
                raise HTTPException(status_code=404, detail="job not found")
            alive = job["status"] == "running" and job["attempts"] == attempt
            if alive:
                conn.execute(
                    "UPDATE jobs SET lease_expires_at = datetime('now', ?) WHERE id = ?",
                    ("+{} seconds".format(settings.job_lease_seconds), job_id),
                )
            conn.execute("COMMIT")
        except Exception:
            _rollback(conn)
            raise
    return {"alive": alive, "cancelled": job["status"] == "cancelled"}


def record_progress(job_id, attempt, phase):
    with db() as conn:
        conn.execute(
            "UPDATE jobs SET phase = ? WHERE id = ? AND status = 'running' AND attempts = ?",
            (phase, job_id, attempt),
        )
    return {"phase": phase}


def record_result(job_id, attempt, status, text, media, error, error_kind=None, thread_url=None):
    media_ids = []
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            job = _live_attempt(conn, job_id, attempt)

            # Remember where the provider put this conversation so the next turn
            # lands in the same place and can build on this one.
            if thread_url and job["conversation_id"]:
                conn.execute(
                    "UPDATE conversations SET provider_thread_url = ? WHERE id = ?",
                    (thread_url, job["conversation_id"]),
                )

            # The message comes first so its pictures can point at it.
            message_id = None
            if status == "done" and job["conversation_id"] and (text or media):
                message_id = uuid.uuid4().hex
                conn.execute(
                    "INSERT INTO messages (id, conversation_id, role, content)"
                    " VALUES (?, ?, 'assistant', ?)",
                    (message_id, job["conversation_id"], text or ""),
                )

            if status == "done":
                for item in media or []:
                    media_id = uuid.uuid4().hex
                    conn.execute(
                        "INSERT INTO media (id, user_id, conversation_id, message_id, provider,"
                        " type, prompt, filename, metadata) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            changed = conn.execute(
                "UPDATE jobs SET status = ?, result = ?, error = ?, error_kind = ?,"
                " lease_expires_at = NULL, phase = NULL, finished_at = datetime('now')"
                " WHERE id = ? AND status = 'running' AND attempts = ?",
                (status, json.dumps(result), error, error_kind, job_id, attempt),
            ).rowcount
            if changed != 1:
                raise HTTPException(status_code=409, detail="job changed under this attempt")
            # A job that produced nothing must not cost the user a credit.
            if status == "failed":
                _refund(conn, job["user_id"])
            conn.execute("COMMIT")
        except Exception:
            _rollback(conn)
            raise
    return {"text": text or "", "media": media_ids}


def cancel_job(user_id, job_id):
    """Stop a job and give the credit back. Idempotent on a job already over."""
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            job = one(conn, "SELECT * FROM jobs WHERE id = ? AND user_id = ?", (job_id, user_id))
            if not job:
                raise HTTPException(status_code=404, detail="job not found")
            if job["status"] not in TERMINAL:
                conn.execute(
                    "UPDATE jobs SET status = 'cancelled', cancel_requested = 1, error = ?,"
                    " error_kind = 'cancelled', lease_expires_at = NULL, phase = NULL,"
                    " finished_at = datetime('now') WHERE id = ?",
                    ("cancelled by the user", job_id),
                )
                _refund(conn, job["user_id"])
            conn.execute("COMMIT")
        except Exception:
            _rollback(conn)
            raise
    return get_job(user_id, job_id)


def get_job(user_id, job_id):
    with db() as conn:
        job = one(conn, "SELECT * FROM jobs WHERE id = ? AND user_id = ?", (job_id, user_id))
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return {
        "id": job["id"],
        "status": job["status"],
        "phase": job["phase"],
        "attempts": job["attempts"],
        "feature": job["feature"],
        "provider": job["provider"],
        "conversation_id": job["conversation_id"],
        "result": json.loads(job["result"]) if job["result"] else None,
        "error": job["error"],
        "error_kind": job["error_kind"],
        "created_at": job["created_at"],
        "finished_at": job["finished_at"],
    }
