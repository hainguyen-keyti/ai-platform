import hmac
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response

from src.config import settings
from src.db.client import db, one
from src.models import LoginRequest, RegisterRequest
from src.security import current_user, hash_password, issue_token, revoke_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


def _public(user: dict) -> dict:
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "role": user["role"],
        "quota_remaining": user["quota_remaining"],
        "quota_daily": user.get("quota_daily"),
        "created_at": user["created_at"],
    }


@router.post("/register", status_code=201)
def register(body: RegisterRequest):
    if not hmac.compare_digest(body.invite_code, settings.invite_code):
        raise HTTPException(status_code=403, detail="invalid invite code")

    email = body.email.lower()
    with db() as conn:
        if one(conn, "SELECT id FROM users WHERE email = ?", (email,)):
            raise HTTPException(status_code=409, detail="email already registered")
        # The first account to exist owns the instance.
        first = one(conn, "SELECT COUNT(*) AS n FROM users")["n"] == 0
        user_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO users (id, email, password_hash, name, role, quota_remaining, quota_daily)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                email,
                hash_password(body.password),
                body.name,
                "admin" if first else "user",
                settings.default_quota,
                settings.default_quota,
            ),
        )
        user = one(conn, "SELECT * FROM users WHERE id = ?", (user_id,))
    return _public(user)


@router.post("/login")
def login(body: LoginRequest):
    with db() as conn:
        user = one(conn, "SELECT * FROM users WHERE email = ?", (body.email.lower(),))
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="wrong email or password")
    token, expires = issue_token(user["id"])
    return {"token": token, "expires_at": expires.isoformat(), "user": _public(user)}


@router.post("/logout", status_code=204)
def logout(user: dict = Depends(current_user)):
    revoke_token(user["token"])
    return Response(status_code=204)


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return _public(user)
