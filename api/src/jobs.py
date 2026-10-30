import json
import uuid

from fastapi import HTTPException

from src.config import settings
from src.db.client import db, many, one
from src.models import FEATURES, PROVIDERS
from src.tombstones import leave_tombstone

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


def cancel_open_jobs(conn, conversation_id):
    """Inside the caller's transaction: end every live job of a conversation, refunding each once.

    Used when the conversation itself is deleted. The worker learns through its
    next heartbeat that the job is no longer its to finish, and its late result
    is refused, so nothing of the deleted conversation is written afterwards.
    """
    live = many(
        conn,
        "SELECT id, user_id FROM jobs WHERE conversation_id = ? AND status NOT IN ('done', 'failed', 'cancelled')",
        (conversation_id,),
    )
    for job in live:
        conn.execute(
            "UPDATE jobs SET status = 'cancelled', cancel_requested = 1, error = ?,"
            " error_kind = 'cancelled', lease_expires_at = NULL, phase = NULL,"
            " finished_at = datetime('now') WHERE id = ?",
            ("the conversation was deleted while the job was live", job["id"]),
        )
        _refund(conn, job["user_id"])
    return len(live)


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
               user_message=None, title=None, reference_media_id=None, media_id=None, upload=None):
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
                    "SELECT id, provider FROM conversations WHERE id = ? AND user_id = ?",
                    (conversation_id, user["id"]),
                )
                if not owned:
                    raise HTTPException(status_code=404, detail="conversation not found")
                # The conversation holds one provider's thread. Sending another
                # provider's turn into it would hand that provider a thread url
                # from a site it is not even logged into.
                if owned["provider"] != provider:
                    raise HTTPException(
                        status_code=409,
                        detail="this conversation belongs to {}; start a new chat to use {}".format(
                            owned["provider"], provider),
                    )

            if reference_media_id:
                payload["reference_filename"] = _resolve_media(
                    conn, user["id"], reference_media_id)["filename"]
            if media_id:
                payload["filename"] = _resolve_media(conn, user["id"], media_id)["filename"]

            # A feature the provider does not offer would only fail in the worker a second later
            # (2026-10-28: a video script asked of grok); refused here, after the 404 and 409.
            if feature not in FEATURES[provider]:
                raise HTTPException(
                    status_code=400,
                    detail="{} does not offer {}; use {}".format(
                        provider, feature, " or ".join(p for p in PROVIDERS if feature in FEATURES[p])),
                )

            # After every check that already refuses (404, 409, a missing picture), before
            # anything is written or charged: a turn that would only fail is refused now, one
            # into an account its admin must fix, or one nobody would pick up (no_worker minutes
            # later).
            if _held(conn, provider):
                raise HTTPException(
                    status_code=503,
                    detail="{} is unavailable right now: its account needs its admin; try again later".format(
                        provider),
                )
            if not _served(conn, provider):
                raise HTTPException(
                    status_code=503,
                    detail="no worker is serving {} right now; try again later".format(provider),
                )
            if not conversation_id:
                conversation_id = uuid.uuid4().hex
                conn.execute(
                    "INSERT INTO conversations (id, user_id, provider, title) VALUES (?, ?, ?, ?)",
                    (conversation_id, user["id"], provider, (title or "New chat")[:80]),
                )

            message_id = None
            if user_message:
                message_id = uuid.uuid4().hex
                conn.execute(
                    "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, 'user', ?)",
                    (message_id, conversation_id, user_message),
                )

            # The pictures the person sent: kept as their media on their own message, in the order sent,
            # read by the worker. One upload, or a list of them (issue #22, several for chatgpt).
            uploads = [upload] if isinstance(upload, dict) else list(upload or [])
            if uploads:
                payload["reference_filename"] = uploads[0]["filename"]
            if len(uploads) > 1:
                payload["reference_filenames"] = [sent["filename"] for sent in uploads]
            for sent in uploads:
                conn.execute(
                    "INSERT INTO media (id, user_id, conversation_id, message_id, provider, type, prompt,"
                    " filename, metadata) VALUES (?, ?, ?, ?, ?, 'image', ?, ?, ?)",
                    (uuid.uuid4().hex, user["id"], conversation_id, message_id, provider,
                     payload.get("prompt"), sent["filename"], json.dumps(sent["metadata"])),
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


def _note_worker(conn, providers, pacing=None):
    for name in providers:
        conn.execute(
            "INSERT INTO worker_pings (provider, last_seen) VALUES (?, datetime('now'))"
            " ON CONFLICT(provider) DO UPDATE SET last_seen = datetime('now')",
            (name,),
        )
        if pacing:
            free_in = pacing.get("budget_free_in") or 0
            conn.execute(
                "UPDATE worker_pings SET images_3h = ?, image_budget = ?,"
                " budget_free_at = CASE WHEN ? > 0 THEN datetime('now', ?) END WHERE provider = ?",
                (pacing["images_last_3h"], pacing["image_budget"], free_in, "+{} seconds".format(int(free_in)), name),
            )


def _held(conn, provider):
    """Whether this provider is held out because its account needs its admin."""
    return one(
        conn, "SELECT 1 FROM provider_holds WHERE provider = ? AND until > datetime('now')", (provider,)
    ) is not None


def _hold(conn, provider, reason):
    """Inside the caller's transaction: hold a provider out whose account needs its admin.

    Every turn would fail the same way until the account is fixed, so the jobs already waiting for it
    are failed now, each refunded once, instead of one after another.
    """
    conn.execute(
        "INSERT INTO provider_holds (provider, until, reason) VALUES (?, datetime('now', ?), ?)"
        " ON CONFLICT(provider) DO UPDATE SET until = excluded.until, reason = excluded.reason",
        (provider, "+{} seconds".format(settings.provider_hold_seconds), reason),
    )
    waiting = many(conn, "SELECT id, user_id FROM jobs WHERE provider = ? AND status = 'pending'", (provider,))
    for job in waiting:
        changed = conn.execute(
            "UPDATE jobs SET status = 'failed', error = ?, error_kind = 'provider_misconfigured',"
            " lease_expires_at = NULL, phase = NULL, finished_at = datetime('now')"
            " WHERE id = ? AND status = 'pending'",
            (reason, job["id"]),
        ).rowcount
        if changed == 1:
            _refund(conn, job["user_id"])


def _served(conn, provider):
    """Whether a worker has asked for this provider within the window the sweep below uses, and its
    account is not held out for its admin."""
    pinged = one(
        conn,
        "SELECT 1 FROM worker_pings WHERE provider = ? AND last_seen >= datetime('now', ?)",
        (provider, "-{} seconds".format(settings.no_worker_seconds)),
    ) is not None
    return pinged and not _held(conn, provider)


def provider_status():
    """Every provider, whether a worker serves it right now, and what it offers."""
    with db() as conn:
        return {"providers": [{"name": name, "served": _served(conn, name), "features": list(FEATURES[name])}
                              for name in PROVIDERS]}


def provider_load():
    """Per provider: the requests waiting, and what its worker last said of its picture budget. A job
    behind a spent budget just waits (40 pictures in three hours by default), and looks served."""
    with db() as conn:
        pings = {row["provider"]: row for row in many(conn, "SELECT * FROM worker_pings")}
        waiting = {row["provider"]: row["n"] for row in many(
            conn, "SELECT provider, COUNT(*) AS n FROM jobs WHERE status = 'pending' GROUP BY provider")}
    return {name: {"waiting": waiting.get(name, 0),
                   "pictures_last_3h": (pings.get(name) or {}).get("images_3h"),
                   "picture_budget": (pings.get(name) or {}).get("image_budget"),
                   "budget_free_at": (pings.get(name) or {}).get("budget_free_at")} for name in PROVIDERS}


def _sweep_unserved(conn, job_id=None):
    """Fail and refund pending jobs whose provider no worker has asked for.

    Age alone would be wrong: a job queued behind a five minute picture is
    waiting for a worker that exists. What makes a job an orphan is that nobody
    has asked for its provider within the window.
    """
    window = "-{} seconds".format(settings.no_worker_seconds)
    sql = ("SELECT j.id, j.user_id, j.provider FROM jobs j"
           " LEFT JOIN worker_pings w ON w.provider = j.provider"
           " WHERE j.status = 'pending' AND j.created_at < datetime('now', ?)"
           " AND (w.last_seen IS NULL OR w.last_seen < datetime('now', ?))")
    params = [window, window]
    if job_id:
        sql += " AND j.id = ?"
        params.append(job_id)
    for job in many(conn, sql, params):
        changed = conn.execute(
            "UPDATE jobs SET status = 'failed', error = ?, error_kind = 'no_worker',"
            " lease_expires_at = NULL, phase = NULL, finished_at = datetime('now')"
            " WHERE id = ? AND status = 'pending'",
            ("no worker is serving {} right now".format(job["provider"]), job["id"]),
        ).rowcount
        if changed == 1:
            _refund(conn, job["user_id"])


def note_workers(providers, pacing=None):
    """Record that a worker serving these providers is alive right now.

    Claiming is not the only proof of life: a runner deliberately pausing
    between turns, or sitting out a cooldown, is working exactly as intended.
    """
    serves = [p for p in (providers or []) if p in PROVIDERS]
    if not serves:
        return {"noted": []}
    with db() as conn:
        _note_worker(conn, serves, pacing)
    return {"noted": serves}


def claim_next_job(providers=None, pacing=None):
    lease = "+{} seconds".format(settings.job_lease_seconds)
    serves = [p for p in (providers or []) if p in PROVIDERS]
    if not serves:
        # Fail closed: a caller that names no provider it can serve gets no
        # work, rather than every provider's work.
        return None
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            _note_worker(conn, serves, pacing)
            _sweep_stranded(conn)
            _sweep_unserved(conn)
            where = "j.status = 'pending' AND j.provider IN ({})".format(
                ", ".join("?" * len(serves)))
            params = list(serves)
            row = one(
                conn,
                "SELECT j.id, j.provider, j.feature, j.payload, j.attempts,"
                " c.provider_thread_url AS thread_url"
                " FROM jobs j LEFT JOIN conversations c ON c.id = j.conversation_id"
                " WHERE {} ORDER BY j.created_at, j.rowid LIMIT 1".format(where),
                params,
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
            job = one(conn, "SELECT status, attempts, provider FROM jobs WHERE id = ?", (job_id,))
            if not job:
                raise HTTPException(status_code=404, detail="job not found")
            alive = job["status"] == "running" and job["attempts"] == attempt
            if alive:
                conn.execute(
                    "UPDATE jobs SET lease_expires_at = datetime('now', ?) WHERE id = ?",
                    ("+{} seconds".format(settings.job_lease_seconds), job_id),
                )
                # A worker in the middle of a turn stops asking for work, so its
                # heartbeat is the proof it is alive. Without this, one five
                # minute picture made every job queued behind it look unserved.
                _note_worker(conn, [job["provider"]])
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
            cancelled = one(
                conn,
                "SELECT * FROM jobs WHERE id = ? AND status IN ('cancelled', 'failed')",
                (job_id,),
            )
            if cancelled and thread_url:
                # The turn was already on the provider's site when the job was
                # cancelled. A deleted conversation's thread is noted for removal;
                # a live conversation without a thread yet gets this one, so its
                # next turn continues where the cancelled one landed.
                conv = one(conn, "SELECT id, provider_thread_url FROM conversations WHERE id = ?",
                           (cancelled["conversation_id"],)) if cancelled["conversation_id"] else None
                if conv is None:
                    leave_tombstone(conn, cancelled["provider"], thread_url)
                elif not conv["provider_thread_url"]:
                    conn.execute("UPDATE conversations SET provider_thread_url = ? WHERE id = ?",
                                 (thread_url, conv["id"]))
                conn.execute("COMMIT")
                raise HTTPException(
                    status_code=409,
                    detail="job is {}, this attempt may not change it".format(cancelled["status"]))
            job = _live_attempt(conn, job_id, attempt)

            # Remember where the provider put this conversation so the next turn
            # lands in the same place and can build on this one.
            if thread_url and job["conversation_id"]:
                conn.execute(
                    "UPDATE conversations SET provider_thread_url = ? WHERE id = ?",
                    (thread_url, job["conversation_id"]),
                )

            # A turn called done with neither words nor media produced nothing, and nothing must
            # not cost a credit (DECISIONS 2026-09-23): it is a failed turn, refunded below.
            if status == "done" and not (text or "").strip() and not media:
                status, error_kind = "failed", "empty_reply"
                error = "the provider's turn came back with neither words nor media"

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
            if status == "failed" and error_kind == "provider_misconfigured":
                _hold(conn, job["provider"], error)
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
        # The person waiting is the one who notices first, so their own poll is
        # what discovers that nobody is serving this job, or that its keeper died.
        conn.execute("BEGIN IMMEDIATE")
        try:
            _sweep_stranded(conn)
            _sweep_unserved(conn, job_id)
            conn.execute("COMMIT")
        except Exception:
            _rollback(conn)
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
