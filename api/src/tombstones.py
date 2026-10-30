import uuid

from fastapi import HTTPException

from src.db.client import db, many, one


def known_threads(provider, thread_urls):
    """Which of these thread addresses the platform stores for this provider: a live conversation's, or
    a deleted one's tombstone. The nightly Library cleanup (#27) touches nothing else on the account."""
    if not thread_urls:
        return []
    marks = ", ".join("?" * len(thread_urls))
    with db() as conn:
        rows = many(conn, "SELECT provider_thread_url AS url FROM conversations WHERE provider = ?"
                          " AND provider_thread_url IN ({0}) UNION SELECT thread_url AS url FROM thread_tombstones"
                          " WHERE provider = ? AND thread_url IN ({0})".format(marks),
                    (provider, *thread_urls, provider, *thread_urls))
    return [row["url"] for row in rows]


# A claim the worker never settled goes back to the queue after this long.
RECLAIM_AFTER = "-10 minutes"
MAX_ATTEMPTS = 3


def _rollback(conn):
    try:
        conn.execute("ROLLBACK")
    except Exception:
        pass


def leave_tombstone(conn, provider: str, thread_url: str):
    """Inside the caller's transaction: note a thread the worker must remove, once per thread."""
    pending = one(
        conn,
        "SELECT id FROM thread_tombstones WHERE thread_url = ? AND deleted_at IS NULL",
        (thread_url,),
    )
    if pending:
        return
    conn.execute(
        "INSERT INTO thread_tombstones (id, provider, thread_url) VALUES (?, ?, ?)",
        (uuid.uuid4().hex, provider, thread_url),
    )


def claim_tombstone(providers=None):
    """Hand the worker one thread to remove, oldest first, at most once per attempt.

    A worker is only offered threads of the providers it serves: it is the one
    holding that provider's browser session.
    """
    serves = [p for p in (providers or []) if isinstance(p, str)]
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                "UPDATE thread_tombstones SET claimed_at = NULL"
                " WHERE deleted_at IS NULL AND claimed_at IS NOT NULL"
                " AND claimed_at < datetime('now', ?)",
                (RECLAIM_AFTER,),
            )
            where = "deleted_at IS NULL AND claimed_at IS NULL AND attempts < ?"
            params = [MAX_ATTEMPTS]
            if serves:
                where += " AND provider IN ({})".format(", ".join("?" * len(serves)))
                params += serves
            stone = one(
                conn,
                "SELECT id, provider, thread_url FROM thread_tombstones"
                " WHERE {} ORDER BY created_at, rowid LIMIT 1".format(where),
                params,
            )
            if stone:
                conn.execute(
                    "UPDATE thread_tombstones SET claimed_at = datetime('now'),"
                    " attempts = attempts + 1 WHERE id = ?",
                    (stone["id"],),
                )
            conn.execute("COMMIT")
        except Exception:
            _rollback(conn)
            raise
    return stone


def settle_tombstone(stone_id: str, ok: bool, error):
    """Mark the thread gone, or record the failure.

    A failed attempt keeps its claim, stamped now, so the reclaim window is a
    rest between attempts: a logged-out session cannot burn through every
    pending tombstone in one idle minute.
    """
    with db() as conn:
        if ok:
            changed = conn.execute(
                "UPDATE thread_tombstones SET deleted_at = datetime('now'), error = NULL"
                " WHERE id = ? AND deleted_at IS NULL",
                (stone_id,),
            ).rowcount
        else:
            changed = conn.execute(
                "UPDATE thread_tombstones SET claimed_at = datetime('now'), error = ?"
                " WHERE id = ? AND deleted_at IS NULL",
                ((error or "")[:500], stone_id),
            ).rowcount
    if changed != 1:
        raise HTTPException(status_code=404, detail="tombstone not found or already settled")
    return {"ok": ok}
