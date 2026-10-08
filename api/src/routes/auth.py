import hmac
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response

from src.config import settings
from src.db.client import db, many, one
from src.models import ApiKeyCreate, LoginRequest, RegisterRequest
from src.security import (current_user, hash_api_key, hash_password, issue_token, new_api_key,
                          revoke_token, verify_password)

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


MAX_LIVE_KEYS = 10
KEY_FIELDS = "id, name, prefix, created_at, last_used_at"


# Keys are managed with a login only: a key never reaches these routes, so it cannot mint another.
@router.post("/api-keys", status_code=201)
def create_api_key(body: ApiKeyCreate, user: dict = Depends(current_user)):
    key, key_id = new_api_key(), uuid.uuid4().hex
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            live = one(conn, "SELECT COUNT(*) AS n FROM api_keys WHERE user_id = ? AND revoked_at IS NULL",
                       (user["id"],))["n"]
            if live >= MAX_LIVE_KEYS:
                raise HTTPException(status_code=409,
                                    detail="at most {} live api keys; revoke one first".format(MAX_LIVE_KEYS))
            conn.execute(
                "INSERT INTO api_keys (id, user_id, name, prefix, key_hash) VALUES (?, ?, ?, ?, ?)",
                (key_id, user["id"], body.name.strip(), key[:12], hash_api_key(key)),
            )
            made = one(conn, "SELECT {} FROM api_keys WHERE id = ?".format(KEY_FIELDS), (key_id,))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return dict(made, key=key)


@router.get("/api-keys")
def list_api_keys(user: dict = Depends(current_user)):
    with db() as conn:
        items = many(conn, "SELECT {} FROM api_keys WHERE user_id = ? AND revoked_at IS NULL"
                           " ORDER BY created_at DESC, rowid DESC".format(KEY_FIELDS), (user["id"],))
    return {"items": items}


@router.delete("/api-keys/{key_id}", status_code=204)
def revoke_api_key(key_id: str, user: dict = Depends(current_user)):
    with db() as conn:
        revoked = conn.execute(
            "UPDATE api_keys SET revoked_at = datetime('now')"
            " WHERE id = ? AND user_id = ? AND revoked_at IS NULL", (key_id, user["id"])).rowcount
    if not revoked:
        raise HTTPException(status_code=404, detail="api key not found")
    return Response(status_code=204)
