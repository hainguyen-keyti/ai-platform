#!/usr/bin/env python3
"""A new picture conversation goes to the preferred account while it can take it, and to another only when it cannot.

    ~/cloakbrowser-env/bin/python tests/test_preferred_accounts.py

2026-11-08: the MCP's two sessions had started on a Free account, which met its picture limit after
five pictures and held them for 23 hours while the Plus account sat idle. An api of its own on a
temporary database and a mock worker with two ChatGPT accounts, the first preferred; nothing real is
touched. Prints N/N PASSED.
"""

import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_provider_accounts import A, B, INVITE, WINDOW, WORKER_TOKEN, Stack, http, job_row, send, settled  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
results = []


def record(name, ok, detail=""):
    results.append(bool(ok))
    print("[{}] {}  {}".format("PASS" if ok else "FAIL", name, str(detail)[:300]), flush=True)


class PreferredStack(Stack):
    def start_api(self):
        self.api_proc = self.spawn(ROOT / "api", self.api_port, {
            "DB_PATH": str(self.db_path), "MEDIA_PATH": str(self.work / "media"), "JWT_SECRET": "preferred-secret",
            "INVITE_CODE": INVITE, "WORKER_TOKEN": WORKER_TOKEN, "DEFAULT_QUOTA": "1000",
            "NO_WORKER_SECONDS": str(WINDOW), "PREFERRED_IMAGE_ACCOUNTS": A}, "api")
        return self.wait(self.api + "/health")


def accounts_of(stack, ids):
    return [job_row(stack, rid)[1] for rid in ids]


def scenario_preferred_first(stack, key):
    ids = [send(stack, key, session="first-{}".format(n))[1]["id"] for n in range(4)]
    states = settled(stack, ids, 60)
    took = accounts_of(stack, ids)
    record("new picture sessions all go to the preferred account while it can take them, though the other is idle",
           states == ["done"] * 4 and took == [A] * 4, (states, took))


def scenario_preferred_held(stack, key):
    with sqlite3.connect(stack.db_path) as conn:
        conn.execute("INSERT OR REPLACE INTO provider_holds (provider, until, reason) VALUES (?, '2999-01-01 00:00:00', 'the test')", (A,))
    rid = send(stack, key, session="while-held")[1]["id"]
    settled(stack, [rid], 30)
    record("with the preferred account held, a new session goes to the other", job_row(stack, rid)[:2] == ("done", B),
           job_row(stack, rid))
    with sqlite3.connect(stack.db_path) as conn:
        conn.execute("DELETE FROM provider_holds")
    return rid


def scenario_pinned_stays(stack, key):
    rid = send(stack, key, session="while-held")[1]["id"]
    settled(stack, [rid], 30)
    record("a session already on the other account stays there", job_row(stack, rid)[:2] == ("done", B), job_row(stack, rid))


def scenario_budget_spent(stack, key):
    # What the worker reports of a spent picture budget; set after the worker's own report, and the next
    # report (every claim) would put it back, so the worker is stopped while it holds.
    import json
    import urllib.request

    def claim(asking):
        request = urllib.request.Request(stack.api + "/internal/jobs/claim", method="POST", headers={
            "Content-Type": "application/json", "X-Worker-Token": WORKER_TOKEN},
            data=json.dumps({"providers": ["chatgpt"], "account": asking}).encode())
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read()
            return json.loads(body)["id"] if body.strip() else None

    stack.kill(stack.worker_proc)

    def preferred_alive(spent):
        # Alive as its own claims would show it; its budget as its worker last reported it.
        with sqlite3.connect(stack.db_path) as conn:
            conn.execute("UPDATE provider_accounts SET last_seen = datetime('now'), budget_free_at = {} WHERE account = ?".format(
                "datetime('now', '+3 hours')" if spent else "NULL"), (A,))

    fresh = send(stack, key, session="budget-back")[1]["id"]
    preferred_alive(spent=False)
    record("while the preferred account is alive and has room, the other is given no new session",
           claim(B) is None and job_row(stack, fresh)[0] == "pending", job_row(stack, fresh))
    preferred_alive(spent=True)
    record("with the preferred account's picture budget spent, the other takes a new session",
           claim(B) == fresh, job_row(stack, fresh))


def main():
    work = Path(tempfile.mkdtemp(prefix="preferred-accounts-", dir=str(Path.home() / ".cache")))
    stack = PreferredStack(work)
    try:
        if not stack.start_api() or not stack.start_worker():
            print("the stack did not start; logs in", work)
            return 1
        http("POST", stack.api + "/auth/register", {"email": "user@preferred-test.com", "password": "a-long-enough-password-1", "name": "u", "invite_code": INVITE})
        token = http("POST", stack.api + "/auth/login", {"email": "user@preferred-test.com", "password": "a-long-enough-password-1"})[1]["token"]
        key = http("POST", stack.api + "/auth/api-keys", {"name": "one"}, token=token)[1]["key"]
        scenario_preferred_first(stack, key)
        scenario_preferred_held(stack, key)
        scenario_pinned_stays(stack, key)
        scenario_budget_spent(stack, key)
    finally:
        stack.stop()
    passed = sum(results)
    print("{}/{} PASSED".format(passed, len(results)))
    if passed == len(results):
        shutil.rmtree(work, ignore_errors=True)
    else:
        print("logs in", work)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
