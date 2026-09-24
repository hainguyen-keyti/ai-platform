import uuid

from fastapi import HTTPException

from src.db.client import db, one

# A claim the worker never settled goes back to the queue after this long.
RECLAIM_AFTER = "-10 minutes"
MAX_ATTEMPTS = 3


def _rollback(conn):
    try:
        conn.execute("ROLLBACK")
    except Exception:
        pass


def leave_tombstone(conn, provider: str, thread_url: str):
    """Inside the caller's transaction: note a thread the worker must remove."""
    conn.execute(
        "INSERT INTO thread_tombstones (id, provider, thread_url) VALUES (?, ?, ?)",
        (uuid.uuid4().hex, provider, thread_url),
    )


def claim_tombstone():
    """Hand the worker one thread to remove, oldest first, at most once per attempt."""
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                "UPDATE thread_tombstones SET claimed_at = NULL"
                " WHERE deleted_at IS NULL AND claimed_at IS NOT NULL"
                " AND claimed_at < datetime('now', ?)",
                (RECLAIM_AFTER,),
            )
            stone = one(
                conn,
                "SELECT id, provider, thread_url FROM thread_tombstones"
                " WHERE deleted_at IS NULL AND claimed_at IS NULL AND attempts < ?"
                " ORDER BY created_at, rowid LIMIT 1",
                (MAX_ATTEMPTS,),
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
