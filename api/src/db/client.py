import sqlite3
from contextlib import contextmanager
from pathlib import Path

from src.config import settings

SCHEMA_FILE = Path(__file__).with_name("schema.sql")


def connect():
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(settings.db_path), timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=15000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    settings.media_path.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.executescript(SCHEMA_FILE.read_text())
        # CREATE TABLE IF NOT EXISTS cannot widen a table that already exists,
        # and the alternative is asking anyone already running this to throw
        # their conversations away.
        for table, column, definition in (
            ("media", "message_id", "TEXT"),
            ("conversations", "provider_thread_url", "TEXT"),
            ("jobs", "attempts", "INTEGER NOT NULL DEFAULT 0"),
            ("jobs", "lease_expires_at", "TEXT"),
            ("jobs", "cancel_requested", "INTEGER NOT NULL DEFAULT 0"),
            ("jobs", "phase", "TEXT"),
            ("jobs", "error_kind", "TEXT"),
            ("users", "quota_daily", "INTEGER NOT NULL DEFAULT 100"),
            ("users", "last_refill_day", "TEXT"),
            ("worker_pings", "images_3h", "INTEGER"),
            ("worker_pings", "image_budget", "INTEGER"),
            ("worker_pings", "budget_free_at", "TEXT"),
            ("conversations", "account", "TEXT"),
            ("jobs", "account", "TEXT"),
            ("thread_tombstones", "account", "TEXT"),
            ("jobs", "retry_at", "TEXT"),
        ):
            existing = {row["name"] for row in conn.execute("PRAGMA table_info({})".format(table))}
            if column not in existing:
                conn.execute("ALTER TABLE {} ADD COLUMN {} {}".format(table, column, definition))
        # A thread lives on the account that made it (issue #29), and every thread from before
        # accounts was made by the one profile there was, now its provider's default account.
        conn.execute("UPDATE conversations SET account = provider"
                     " WHERE account IS NULL AND provider_thread_url IS NOT NULL")


def one(conn, sql, params=()):
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def many(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]
