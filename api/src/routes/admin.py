from fastapi import APIRouter, Depends, HTTPException, Query

from src.db.client import db, many, one
from src.models import QuotaUpdate
from src.security import current_user, require_admin

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users")
def list_users(user: dict = Depends(current_user)):
    require_admin(user)
    with db() as conn:
        rows = many(
            conn,
            "SELECT id, email, name, role, quota_remaining, quota_daily, created_at FROM users"
            " ORDER BY created_at, rowid",
        )
    return {"items": rows}


@router.get("/usage")
def usage(days: int = Query(default=30, ge=1, le=365), user: dict = Depends(current_user)):
    """Who spent what, read from the jobs that already record every charge and refund."""
    require_admin(user)
    window = "-{} days".format(days)
    with db() as conn:
        rows = many(
            conn,
            "SELECT u.id, u.email, u.name, u.role, u.quota_remaining, u.quota_daily,"
            " COUNT(j.id) AS jobs_total,"
            " SUM(CASE WHEN j.status = 'done' THEN 1 ELSE 0 END) AS done,"
            " SUM(CASE WHEN j.status = 'failed' THEN 1 ELSE 0 END) AS failed,"
            " SUM(CASE WHEN j.status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled,"
            " SUM(CASE WHEN j.status IN ('pending', 'running') THEN 1 ELSE 0 END) AS open,"
            " MAX(j.created_at) AS last_job_at"
            " FROM users u LEFT JOIN jobs j ON j.user_id = u.id AND j.created_at >= datetime('now', ?)"
            " GROUP BY u.id ORDER BY jobs_total DESC, u.created_at, u.rowid",
            (window,),
        )
        images = {r["user_id"]: r["n"] for r in many(
            conn,
            "SELECT user_id, COUNT(*) AS n FROM media WHERE type = 'image'"
            " AND created_at >= datetime('now', ?) GROUP BY user_id",
            (window,),
        )}
    for row in rows:
        row["images"] = images.get(row["id"], 0)
        for key in ("done", "failed", "cancelled", "open"):
            row[key] = row[key] or 0
    return {"days": days, "items": rows}


@router.put("/users/{user_id}/quota")
def set_quota(user_id: str, body: QuotaUpdate, user: dict = Depends(current_user)):
    require_admin(user)
    with db() as conn:
        target = one(conn, "SELECT id FROM users WHERE id = ?", (user_id,))
        if not target:
            raise HTTPException(status_code=404, detail="user not found")
        conn.execute(
            "UPDATE users SET quota_remaining = ? WHERE id = ?", (body.quota_remaining, user_id)
        )
        if body.quota_daily is not None:
            conn.execute("UPDATE users SET quota_daily = ? WHERE id = ?", (body.quota_daily, user_id))
        updated = one(
            conn,
            "SELECT id, email, quota_remaining, quota_daily FROM users WHERE id = ?",
            (user_id,),
        )
    return updated
