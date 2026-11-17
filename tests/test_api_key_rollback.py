#!/usr/bin/env python3
"""Making an api key that fails after SQLite has rolled back on its own raises the real error (#33).

    ~/cloakbrowser-env/bin/python tests/test_api_key_rollback.py

A full disk or an I/O error ends SQLite's transaction by itself; the route's own ROLLBACK must
not then replace that error with "no transaction is active". Prints N/2 PASSED.
"""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

scratch = Path(tempfile.mkdtemp(prefix="api-key-rollback-"))
os.environ.update({
    "DB_PATH": str(scratch / "app.db"),
    "MEDIA_PATH": str(scratch / "media"),
    "JWT_SECRET": "rollback-test",
    "INVITE_CODE": "rollback-test",
    "WORKER_TOKEN": "rollback-test",
})

from src.db.client import db, init_db  # noqa: E402
from src.models import ApiKeyCreate  # noqa: E402
from src.routes import auth  # noqa: E402

results = []


def record(name, ok, detail):
    results.append(ok)
    print("[{}] {}  {}".format("PASS" if ok else "FAIL", name, detail), flush=True)


def main():
    init_db()
    with db() as conn:
        conn.execute("INSERT INTO users (id, email, password_hash, role, quota_remaining)"
                     " VALUES ('u1', 'a@example.com', 'x', 'user', 1)")

    real_one = auth.one

    def one_after_sqlite_gave_up(conn, sql, params=()):
        if sql.startswith("SELECT {} FROM api_keys".format(auth.KEY_FIELDS)):
            conn.execute("ROLLBACK")  # what SQLite does by itself on a full disk or an I/O error
            raise sqlite3.OperationalError("disk I/O error")
        return real_one(conn, sql, params)

    auth.one = one_after_sqlite_gave_up
    try:
        auth.create_api_key(ApiKeyCreate(name="k"), {"id": "u1"})
        raised = None
    except Exception as exc:
        raised = exc
    finally:
        auth.one = real_one

    record("the failure that ended the transaction is the error raised",
           isinstance(raised, sqlite3.OperationalError) and str(raised) == "disk I/O error",
           "{}: {}".format(type(raised).__name__, raised))
    with db() as conn:
        kept = conn.execute("SELECT COUNT(*) FROM api_keys").fetchone()[0]
    record("no key is kept", kept == 0, "{} key row(s)".format(kept))

    print("{}/{} PASSED".format(sum(results), len(results)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
