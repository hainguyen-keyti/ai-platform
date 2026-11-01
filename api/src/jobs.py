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
            if _all_held(conn, provider):
                raise HTTPException(
                    status_code=503,
                    detail="{} is unavailable right now: its account needs its admin; try again later".format(
                        provider),
                )
            # A thread opens only on the account that made it (issue #29): a conversation on an account
            # that cannot serve is refused rather than left waiting. Say so without naming the account.
            pinned = one(conn, "SELECT account FROM conversations WHERE id = ?", (conversation_id,)) if conversation_id else None
            if pinned and not account_can_serve(conn, provider, pinned["account"]):
                raise HTTPException(
                    status_code=503,
                    detail="the {} account holding this conversation cannot serve it right now; try again "
                           "later, or start a new conversation or session".format(provider),
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


def _note_worker(conn, providers, pacing=None, account=None):
    for name in providers:
        conn.execute(
            "INSERT INTO worker_pings (provider, last_seen) VALUES (?, datetime('now'))"
            " ON CONFLICT(provider) DO UPDATE SET last_seen = datetime('now')",
            (name,),
        )
        asking = account or name
        conn.execute(
            "INSERT INTO provider_accounts (account, provider, last_seen) VALUES (?, ?, datetime('now'))"
            " ON CONFLICT(account) DO UPDATE SET last_seen = datetime('now'), provider = excluded.provider",
            (asking, name),
        )
        if pacing:
            free_in = pacing.get("budget_free_in") or 0
            conn.execute(
                "UPDATE provider_accounts SET images_3h = ?, image_budget = ?,"
                " budget_free_at = CASE WHEN ? > 0 THEN datetime('now', ?) END WHERE account = ?",
                (pacing["images_last_3h"], pacing["image_budget"], free_in, "+{} seconds".format(int(free_in)), asking),
            )


def _held(conn, account):
    """Whether this account is held out because it needs its admin."""
    return one(
        conn, "SELECT 1 FROM provider_holds WHERE provider = ? AND until > datetime('now')", (account,)
    ) is not None


def _accounts_seen(conn, provider):
    """The accounts of this provider a worker has asked with, within the window the sweep below uses."""
    return [row["account"] for row in many(
        conn, "SELECT account FROM provider_accounts WHERE provider = ? AND last_seen >= datetime('now', ?)",
        (provider, "-{} seconds".format(settings.no_worker_seconds)))]


def _all_held(conn, provider):
    """Whether accounts of this provider are held and none is left to serve it."""
    seen = _accounts_seen(conn, provider)
    return any(_held(conn, name) for name in seen + [provider]) and all(_held(conn, name) for name in seen)


def account_can_serve(conn, provider, account):
    """Whether a conversation on this account can run now. One on no account yet can, on any. One whose
    account nobody asks with can only be refused while another account is there to start a new one."""
    if not account:
        return True
    if _held(conn, account):
        return False
    seen = _accounts_seen(conn, provider)
    return account in seen or not seen


def _hold(conn, account, provider, reason, seconds=None):
    """Inside the caller's transaction: hold out an account that needs its admin.

    Every turn on it would fail the same way until it is fixed, so the jobs already waiting for it are
    failed now, each refunded once, instead of one after another: those of conversations on it, and
    with no other account left to serve, all of the provider's.
    """
    conn.execute(
        "INSERT INTO provider_holds (provider, until, reason) VALUES (?, datetime('now', ?), ?)"
        " ON CONFLICT(provider) DO UPDATE SET until = excluded.until, reason = excluded.reason",
        (account, "+{} seconds".format(seconds or settings.provider_hold_seconds), reason),
    )
    if _all_held(conn, provider):
        waiting = many(conn, "SELECT id, user_id FROM jobs WHERE provider = ? AND status = 'pending'", (provider,))
    else:
        waiting = many(conn, "SELECT j.id, j.user_id FROM jobs j JOIN conversations c ON c.id = j.conversation_id"
                             " WHERE j.provider = ? AND j.status = 'pending' AND c.account = ?", (provider, account))
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
    """Whether a worker has asked for this provider within the window the sweep below uses, and not
    every account of it is held out for its admin."""
    pinged = one(
        conn,
        "SELECT 1 FROM worker_pings WHERE provider = ? AND last_seen >= datetime('now', ?)",
        (provider, "-{} seconds".format(settings.no_worker_seconds)),
    ) is not None
    return pinged and not _all_held(conn, provider)


def provider_status():
    """Every provider, whether a worker serves it right now, and what it offers."""
    with db() as conn:
        return {"providers": [{"name": name, "served": _served(conn, name), "features": list(FEATURES[name])}
                              for name in PROVIDERS]}


def provider_load():
    """Per provider: the requests waiting, and what its accounts last said of their picture budgets, in
    total. A job behind a spent budget just waits (40 pictures in three hours by default), and looks
    served; the budget is free again when the first account's is."""
    with db() as conn:
        accounts = {}
        for row in many(conn, "SELECT * FROM provider_accounts WHERE last_seen >= datetime('now', ?)",
                        ("-{} seconds".format(settings.no_worker_seconds),)):
            # A held account takes no picture, so its budget is no room to tell anyone about.
            if not _held(conn, row["account"]):
                accounts.setdefault(row["provider"], []).append(row)
        waiting = {row["provider"]: row["n"] for row in many(
            conn, "SELECT provider, COUNT(*) AS n FROM jobs WHERE status = 'pending' GROUP BY provider")}

    def total(rows, column):
        said = [row[column] for row in rows if row[column] is not None]
        return sum(said) if said else None

    return {name: {"waiting": waiting.get(name, 0),
                   "pictures_last_3h": total(accounts.get(name, []), "images_3h"),
                   "picture_budget": total(accounts.get(name, []), "image_budget"),
                   "budget_free_at": (min(row["budget_free_at"] for row in accounts[name])
                                      if accounts.get(name) and all(row["budget_free_at"] for row in accounts[name])
                                      else None)} for name in PROVIDERS}


def budget_free_at(conversation_id, provider):
    """When a queued request's wait for a spent picture budget ends, or None if it is not waiting for one:
    its conversation's account (issue #29), whose budget /v1/providers' totals cannot show while another
    account has room; or, on no account yet, the first of the accounts that could take it, all spent."""
    with db() as conn:
        pinned = one(conn, "SELECT account FROM conversations WHERE id = ?", (conversation_id,))
        names = [pinned["account"]] if pinned and pinned["account"] else [
            name for name in _accounts_seen(conn, provider) if not _held(conn, name)]
        if not names:
            return None
        said = many(conn, "SELECT budget_free_at FROM provider_accounts WHERE account IN ({})".format(
            ", ".join("?" * len(names))), names)
    free = [row["budget_free_at"] for row in said]
    return min(free) if free and all(free) else None


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
    # A conversation's thread opens on its account alone: with that account gone, nobody will take it,
    # whoever else serves the provider.
    sql = ("SELECT j.id, j.user_id, j.provider FROM jobs j JOIN conversations c ON c.id = j.conversation_id"
           " LEFT JOIN provider_accounts a ON a.account = c.account"
           " WHERE j.status = 'pending' AND c.account IS NOT NULL AND j.created_at < datetime('now', ?)"
           " AND (a.last_seen IS NULL OR a.last_seen < datetime('now', ?))")
    params = [window, window]
    if job_id:
        sql += " AND j.id = ?"
        params.append(job_id)
    for job in many(conn, sql, params):
        changed = conn.execute(
            "UPDATE jobs SET status = 'failed', error = ?, error_kind = 'no_worker',"
            " lease_expires_at = NULL, phase = NULL, finished_at = datetime('now')"
            " WHERE id = ? AND status = 'pending'",
            ("the {} account holding this conversation is not being served right now".format(job["provider"]), job["id"]),
        ).rowcount
        if changed == 1:
            _refund(conn, job["user_id"])


def note_workers(providers, pacing=None, account=None):
    """Record that a worker serving these providers is alive right now.

    Claiming is not the only proof of life: a runner deliberately pausing
    between turns, or sitting out a cooldown, is working exactly as intended.
    """
    serves = [p for p in (providers or []) if p in PROVIDERS]
    if not serves:
        return {"noted": []}
    with db() as conn:
        _note_worker(conn, serves, pacing, account)
    return {"noted": serves}


def claim_next_job(providers=None, pacing=None, account=None):
    """The oldest job this account can take: of a provider it serves, and on no account yet or on this
    one (issue #29). Claiming pins a conversation to the account, so a follow-up queued before the first
    turn has made its thread still lands on it. An account with room is what rotates the work."""
    lease = "+{} seconds".format(settings.job_lease_seconds)
    serves = [p for p in (providers or []) if p in PROVIDERS]
    if not serves:
        # Fail closed: a caller that names no provider it can serve gets no
        # work, rather than every provider's work.
        return None
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            asking = account or serves[0]
            _note_worker(conn, serves, pacing, asking)
            _sweep_stranded(conn)
            _sweep_unserved(conn)
            where = "j.status = 'pending' AND j.provider IN ({}) AND (c.account IS NULL OR c.account = ?)".format(
                ", ".join("?" * len(serves)))
            params = list(serves) + [asking]
            row = None if _held(conn, asking) else one(
                conn,
                "SELECT j.id, j.provider, j.feature, j.payload, j.attempts, j.conversation_id,"
                " c.provider_thread_url AS thread_url"
                " FROM jobs j LEFT JOIN conversations c ON c.id = j.conversation_id"
                " WHERE {} ORDER BY j.created_at, j.rowid LIMIT 1".format(where),
                params,
            )
            if row:
                row["attempts"] += 1
                conn.execute(
                    "UPDATE jobs SET status = 'running', attempts = ?, phase = 'claimed', account = ?,"
                    " started_at = COALESCE(started_at, datetime('now')),"
                    " lease_expires_at = datetime('now', ?) WHERE id = ?",
                    (row["attempts"], asking, lease, row["id"]),
                )
                conn.execute("UPDATE conversations SET account = ? WHERE id = ? AND account IS NULL",
                             (asking, row.pop("conversation_id")))
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
            job = one(conn, "SELECT status, attempts, provider, account FROM jobs WHERE id = ?", (job_id,))
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
                _note_worker(conn, [job["provider"]], account=job["account"])
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


def record_result(job_id, attempt, status, text, media, error, error_kind=None, thread_url=None, hold_seconds=None):
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
                    leave_tombstone(conn, cancelled["provider"], thread_url, cancelled["account"])
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
            # A picture request answered in words alone made no picture, and no picture must not cost a credit
            # either (2026-10-31: "Please upload the previous picture..."). The words are its reason.
            elif status == "done" and job["feature"] == "image" and not media:
                status, error_kind = "failed", "no_picture"
                error = "the provider made no picture and said: {}".format(" ".join(text.split())[:300])

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
            # An account at its provider's limit is left alone until the limit resets: an account that
            # answers at once takes the next job at once, and would fail nearly every one (2026-11-01).
            if status == "failed" and error_kind in ("provider_misconfigured", "provider_limit"):
                _hold(conn, job["account"] or job["provider"], job["provider"], error, hold_seconds)
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
