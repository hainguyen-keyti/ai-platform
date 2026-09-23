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
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(media)")}
        if "message_id" not in columns:
            conn.execute("ALTER TABLE media ADD COLUMN message_id TEXT")


def one(conn, sql, params=()):
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def many(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]
