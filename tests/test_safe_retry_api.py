#!/usr/bin/env python3
"""The api's side of issue #31: a turn safe to try again goes back to the queue, an account behind a check is held.

    ~/cloakbrowser-env/bin/python tests/test_safe_retry_api.py

An api of its own on a temporary database and a mock worker with two ChatGPT accounts; nothing real is touched.
The worker's side is in test_safe_retry.py. Prints N/N PASSED.
"""

import json
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_provider_accounts import A, B, INVITE, WINDOW, WORKER_TOKEN, Stack, http, job_row, send, settled  # noqa: E402

RETRY = 3
results = []


def record(name, ok, detail=""):
    results.append(bool(ok))
    print("[{}] {}  {}".format("PASS" if ok else "FAIL", name, str(detail)[:300]), flush=True)


class RetryStack(Stack):
    def start_api(self):
        self.api_proc = self.spawn(Path(__file__).resolve().parents[1] / "api", self.api_port, {
            "DB_PATH": str(self.db_path), "MEDIA_PATH": str(self.work / "media"), "JWT_SECRET": "retry-secret",
            "INVITE_CODE": INVITE, "WORKER_TOKEN": WORKER_TOKEN, "DEFAULT_QUOTA": "1000",
            "NO_WORKER_SECONDS": str(WINDOW), "JOB_RETRY_SECONDS": str(RETRY),
            "PROVIDER_BLOCKED_HOLD_SECONDS": "1800"}, "api")
        return self.wait(self.api + "/health")


def post_result(stack, job_id, attempt, **body):
    body = dict({"status": "failed", "attempt": attempt, "text": "", "media": [], "error": "page did not load",
                 "error_kind": "provider_error"}, **body)
    request = urllib.request.Request(stack.api + "/internal/jobs/{}/result".format(job_id), method="POST", headers={
        "Content-Type": "application/json", "X-Worker-Token": WORKER_TOKEN}, data=json.dumps(body).encode())
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status


def running_job(stack, user, job_id, attempts, account, thread=None):
    """A conversation pinned to an account (with a thread or not yet), and a job of it a worker holds right now."""
    conversation = "conv-" + job_id
    with sqlite3.connect(stack.db_path) as conn:
        conn.execute("INSERT INTO conversations (id, user_id, provider, provider_thread_url, account) VALUES (?, ?, 'chatgpt', ?, ?)",
                     (conversation, user, thread, account))
        conn.execute("INSERT INTO jobs (id, user_id, conversation_id, provider, feature, payload, status, attempts, account)"
                     " VALUES (?, ?, ?, 'chatgpt', 'image', '{\"prompt\": \"x\"}', 'running', ?, ?)",
                     (job_id, user, conversation, attempts, account))
    return conversation


def quota(stack, user):
    return stack.sql("SELECT quota_remaining FROM users WHERE id = ?", (user,))[0][0]


def row(stack, job_id):
    return stack.sql("SELECT status, error, error_kind, phase, attempts,"
                     " CAST((julianday(retry_at) - julianday('now')) * 86400 AS INTEGER) FROM jobs WHERE id = ?", (job_id,))[0]


def scenario_first_turn(stack, user):
    conversation = running_job(stack, user, "job-first", 1, A)
    before = quota(stack, user)
    posted = post_result(stack, "job-first", 1, retry_safe=True)
    status, error, kind, phase, attempts, wait = row(stack, "job-first")
    record("a turn safe to try again goes back to the queue, with no error to read and its reason in the phase",
           posted == 200 and status == "pending" and error is None and kind is None and "retry" in (phase or "")
           and "page did not load" in phase, (posted, status, error, kind, phase))
    record("it waits before anyone takes it", wait is not None and 0 < wait <= RETRY, wait)
    record("its credit is kept while it waits", quota(stack, user) == before, (before, quota(stack, user)))
    pinned = stack.sql("SELECT account FROM conversations WHERE id = ?", (conversation,))[0][0]
    record("a conversation with no thread yet is let go of its account, so either account may take it", pinned is None, pinned)
    time.sleep(RETRY / 2.0)
    record("nobody takes it before its wait is over", job_row(stack, "job-first")[0] == "pending", job_row(stack, "job-first"))
    final = settled(stack, ["job-first"], 30)
    record("after the wait a worker takes it again, as its second attempt, and it is done",
           final == ["done"] and row(stack, "job-first")[4] == 2, (final, row(stack, "job-first")))


def scenario_follow_up(stack, user):
    conversation = running_job(stack, user, "job-follow", 1, B, thread="https://chatgpt.com/c/kept")
    post_result(stack, "job-follow", 1, retry_safe=True)
    pinned = stack.sql("SELECT account FROM conversations WHERE id = ?", (conversation,))[0][0]
    record("a conversation that has its thread stays on its account", row(stack, "job-follow")[0] == "pending" and pinned == B,
           (row(stack, "job-follow"), pinned))
    settled(stack, ["job-follow"], 30)


def scenario_last_attempt(stack, user):
    running_job(stack, user, "job-last", 3, A)
    before = quota(stack, user)
    post_result(stack, "job-last", 3, retry_safe=True)
    status, error, kind = row(stack, "job-last")[:3]
    record("the last attempt fails for good, with its reason, and the credit comes back",
           status == "failed" and error == "page did not load" and kind == "provider_error" and quota(stack, user) == before + 1,
           (status, error, kind, before, quota(stack, user)))


def scenario_not_safe(stack, user):
    running_job(stack, user, "job-sent", 1, A)
    before = quota(stack, user)
    post_result(stack, "job-sent", 1, error="no answer after the send")
    record("a turn that may have reached the provider is not tried again; it fails and the credit comes back",
           row(stack, "job-sent")[0] == "failed" and quota(stack, user) == before + 1, (row(stack, "job-sent"), before, quota(stack, user)))


def scenario_blocked(stack, user):
    running_job(stack, user, "job-blocked", 1, B)
    before = quota(stack, user)
    post_result(stack, "job-blocked", 1, error="chatgpt stayed behind a Cloudflare check", error_kind="provider_blocked")
    left = stack.sql("SELECT (julianday(until) - julianday('now')) * 86400 FROM provider_holds WHERE provider = ?", (B,))
    record("an account behind a check is held for half an hour, and the job fails with its credit back",
           row(stack, "job-blocked")[0] == "failed" and left and 1790 < left[0][0] <= 1800 and quota(stack, user) == before + 1,
           (row(stack, "job-blocked"), left, before, quota(stack, user)))
    with sqlite3.connect(stack.db_path) as conn:
        conn.execute("DELETE FROM provider_holds")


def main():
    work = Path(tempfile.mkdtemp(prefix="safe-retry-api-", dir=str(Path.home() / ".cache")))
    stack = RetryStack(work)
    try:
        if not stack.start_api() or not stack.start_worker():
            print("the stack did not start; logs in", work)
            return 1
        http("POST", stack.api + "/auth/register", {"email": "user@retry-test.com", "password": "a-long-enough-password-1", "name": "u", "invite_code": INVITE})
        token = http("POST", stack.api + "/auth/login", {"email": "user@retry-test.com", "password": "a-long-enough-password-1"})[1]["token"]
        key = http("POST", stack.api + "/auth/api-keys", {"name": "one"}, token=token)[1]["key"]
        first = send(stack, key, session="warm")[1]["id"]
        settled(stack, [first])
        user = stack.sql("SELECT user_id FROM jobs WHERE id = ?", (first,))[0][0]
        scenario_first_turn(stack, user)
        scenario_follow_up(stack, user)
        scenario_last_attempt(stack, user)
        scenario_not_safe(stack, user)
        scenario_blocked(stack, user)
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
