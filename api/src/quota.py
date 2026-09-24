from datetime import datetime, timedelta, timezone

from src.config import settings
from src.db.client import one


def today() -> str:
    now = datetime.now(timezone.utc) + timedelta(seconds=settings.clock_offset_seconds)
    return now.date().isoformat()


def refill_if_due(conn, user: dict) -> dict:
    """Bring the balance back up to the user's daily cap on the first request of a new day.

    MAX keeps a balance an admin raised above the cap, and two requests racing
    on the same day both write the same day and the same MAX, so nothing stacks.
    """
    day = today()
    if user.get("last_refill_day") == day:
        return user
    conn.execute(
        "UPDATE users SET quota_remaining = MAX(quota_remaining, quota_daily), last_refill_day = ?"
        " WHERE id = ? AND (last_refill_day IS NULL OR last_refill_day <> ?)",
        (day, user["id"], day),
    )
    return one(conn, "SELECT * FROM users WHERE id = ?", (user["id"],)) or user
