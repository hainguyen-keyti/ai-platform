from fastapi import APIRouter, Depends, HTTPException

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
            "SELECT id, email, name, role, quota_remaining, created_at FROM users"
            " ORDER BY created_at, rowid",
        )
    return {"items": rows}


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
        updated = one(
            conn,
            "SELECT id, email, quota_remaining FROM users WHERE id = ?",
            (user_id,),
        )
    return updated
