#!/usr/bin/env python3
"""The tombstone queue's promises, on a throwaway database.

    ~/cloakbrowser-env/bin/python tests/test_tombstones.py

One worker gets a thread to delete once per attempt; a settled tombstone stays
settled; a failed attempt comes back only after the reclaim window; three
misses end it. Checked here directly because through the running stack a single
worker would look correct even if the same tombstone were handed out twice.
Prints N/5 PASSED.
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

scratch = Path(tempfile.mkdtemp(prefix="tombstones-"))
os.environ.update({
    "DB_PATH": str(scratch / "app.db"),
    "MEDIA_PATH": str(scratch / "media"),
    "JWT_SECRET": "tombstone-test",
    "INVITE_CODE": "tombstone-test",
    "WORKER_TOKEN": "tombstone-test",
})

from fastapi import HTTPException  # noqa: E402

from src import tombstones  # noqa: E402
from src.db.client import db, init_db  # noqa: E402

results = []


def record(name, ok, detail):
    results.append(ok)
    print("[{}] {}  {}".format("PASS" if ok else "FAIL", name, detail), flush=True)


def age_claim(stone_id, minutes):
    with db() as conn:
        conn.execute(
            "UPDATE thread_tombstones SET claimed_at = datetime('now', ?) WHERE id = ?",
            ("-{} minutes".format(minutes), stone_id),
        )


def attempts_of(stone_id):
    with db() as conn:
        return conn.execute(
            "SELECT attempts FROM thread_tombstones WHERE id = ?", (stone_id,)).fetchone()[0]


def main():
    init_db()
    with db() as conn:
        tombstones.leave_tombstone(conn, "chatgpt", "https://chatgpt.com/c/first")

    first = tombstones.claim_tombstone()
    second = tombstones.claim_tombstone()
    record("a claimed tombstone is not handed out again",
           first is not None and second is None,
           "first claim {}, second claim {}".format(first and first["thread_url"], second))

    tombstones.settle_tombstone(first["id"], False, "provider said 429")
    third = tombstones.claim_tombstone()
    record("a failed attempt waits for the reclaim window", third is None,
           "claim right after the failure returned {}".format(third))

    age_claim(first["id"], 11)
    fourth = tombstones.claim_tombstone()
    record("after the window it comes back as a second attempt",
           fourth is not None and fourth["id"] == first["id"] and attempts_of(first["id"]) == 2,
           "claim {} attempts {}".format(fourth and fourth["id"][:8], attempts_of(first["id"])))

    tombstones.settle_tombstone(first["id"], False, "provider said 429 again")
    age_claim(first["id"], 11)
    fifth = tombstones.claim_tombstone()
    tombstones.settle_tombstone(first["id"], False, "provider said 429 a third time")
    age_claim(first["id"], 11)
    sixth = tombstones.claim_tombstone()
    record("three misses end it", fifth is not None and sixth is None and attempts_of(first["id"]) == 3,
           "third attempt handed out {}, fourth claim {}, attempts {}".format(
               fifth is not None, sixth, attempts_of(first["id"])))

    with db() as conn:
        tombstones.leave_tombstone(conn, "chatgpt", "https://chatgpt.com/c/second")
    stone = tombstones.claim_tombstone()
    tombstones.settle_tombstone(stone["id"], True, None)
    try:
        tombstones.settle_tombstone(stone["id"], True, None)
        again = "accepted"
    except HTTPException as exc:
        again = exc.status_code
    record("a settled tombstone stays settled", again == 404 and tombstones.claim_tombstone() is None,
           "second settle -> {}, next claim {}".format(again, None))

    passed = sum(1 for ok in results if ok)
    print("{}/{} PASSED".format(passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
