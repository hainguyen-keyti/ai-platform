import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Header, HTTPException

from src.config import settings
from src.db.client import db, one
from src.quota import refill_if_due


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode()


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode(), hashed.encode())
    except ValueError:
        return False


def issue_token(user_id: str):
    expires = datetime.now(timezone.utc) + timedelta(hours=settings.token_ttl_hours)
    token = jwt.encode(
        {"sub": user_id, "exp": expires, "jti": uuid.uuid4().hex},
        settings.jwt_secret,
        algorithm="HS256",
    )
    with db() as conn:
        conn.execute(
            "INSERT INTO sessions (id, user_id, token, expires_at) VALUES (?, ?, ?, ?)",
            (uuid.uuid4().hex, user_id, token, expires.isoformat()),
        )
    return token, expires


def revoke_token(token: str):
    with db() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def _bearer(authorization: str) -> str:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="missing bearer token")
    return token.strip()


def current_user(authorization: str = Header(default="")) -> dict:
    token = _bearer(authorization)
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="invalid token")
    with db() as conn:
        if not one(conn, "SELECT id FROM sessions WHERE token = ?", (token,)):
            raise HTTPException(status_code=401, detail="session revoked")
        user = one(conn, "SELECT * FROM users WHERE id = ?", (payload.get("sub"),))
        if user:
            # Every authenticated request passes here, so a new day is noticed
            # on the first one, whatever it asks for.
            user = refill_if_due(conn, user)
    if not user:
        raise HTTPException(status_code=401, detail="unknown user")
    user["token"] = token
    return user


API_KEY_PREFIX = "aip_"


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def new_api_key() -> str:
    return API_KEY_PREFIX + secrets.token_urlsafe(32)


def api_key_user(authorization: str = Header(default="")) -> dict:
    """The owner of a live API key. Only /v1 depends on this; every other route takes a login JWT,
    which an API key never decodes as."""
    key = _bearer(authorization)
    if not key.startswith(API_KEY_PREFIX):
        raise HTTPException(status_code=401, detail="an api key is required")
    with db() as conn:
        found = one(conn, "SELECT id, user_id FROM api_keys WHERE key_hash = ? AND revoked_at IS NULL",
                    (hash_api_key(key),))
        if not found:
            raise HTTPException(status_code=401, detail="unknown or revoked api key")
        # Once a minute at most: a program asking every few seconds is not a write each time.
        conn.execute("UPDATE api_keys SET last_used_at = datetime('now') WHERE id = ?"
                     " AND (last_used_at IS NULL OR last_used_at < datetime('now', '-1 minute'))", (found["id"],))
        user = one(conn, "SELECT * FROM users WHERE id = ?", (found["user_id"],))
        if user:
            user = refill_if_due(conn, user)
    if not user:
        raise HTTPException(status_code=401, detail="unknown user")
    return user


def require_admin(user: dict) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    return user


def require_worker(x_worker_token: str = Header(default="")):
    if not x_worker_token or not hmac.compare_digest(x_worker_token, settings.worker_token):
        raise HTTPException(status_code=401, detail="bad worker token")
    return True
