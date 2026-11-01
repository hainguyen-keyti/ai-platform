#!/usr/bin/env python3
"""Several accounts of one provider, through the real api and the real worker in mock mode (issue #29).

    ~/cloakbrowser-env/bin/python tests/test_provider_accounts.py

An api of its own on a temporary database and a mock worker with two ChatGPT accounts; nothing real is touched.
Prints N/N PASSED.
"""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVITE, WORKER_TOKEN = "accounts-invite", "accounts-worker"
A, B = "chatgpt", "chatgpt-b"
WINDOW = 6
results = []


def record(name, ok, detail=""):
    results.append(bool(ok))
    print("[{}] {}  {}".format("PASS" if ok else "FAIL", name, str(detail)[:300]), flush=True)


def free_port():
    import socket
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class Stack:
    def __init__(self, work):
        self.work, self.api_port, self.worker_port = work, free_port(), free_port()
        self.api = "http://127.0.0.1:{}".format(self.api_port)
        self.db_path = work / "db" / "app.db"
        self.db_path.parent.mkdir()
        self.api_proc = self.worker_proc = None
        self.runs = 0

    def spawn(self, cwd, port, env, name):
        self.runs += 1
        log = open(self.work / "{}-{}.log".format(name, self.runs), "wb")
        return subprocess.Popen([sys.executable, "-m", "uvicorn", "src.main:app", "--host", "127.0.0.1", "--port", str(port)],
                                cwd=str(cwd), env=dict(os.environ, PYTHONPATH=str(cwd), PYTHONUNBUFFERED="1", **env),
                                stdout=log, stderr=subprocess.STDOUT)

    @staticmethod
    def wait(url):
        deadline = time.time() + 40
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=2):
                    return True
            except Exception:
                time.sleep(0.2)
        return False

    def start_api(self):
        self.api_proc = self.spawn(ROOT / "api", self.api_port, {
            "DB_PATH": str(self.db_path), "MEDIA_PATH": str(self.work / "media"), "JWT_SECRET": "accounts-secret",
            "INVITE_CODE": INVITE, "WORKER_TOKEN": WORKER_TOKEN, "DEFAULT_QUOTA": "1000",
            "NO_WORKER_SECONDS": str(WINDOW)}, "api")
        return self.wait(self.api + "/health")

    def start_worker(self, accounts="{},{}".format(A, B), **env):
        settings = {"API_URL": self.api, "WORKER_TOKEN": WORKER_TOKEN, "PROVIDER_MODE": "mock",
                    "MEDIA_PATH": str(self.work / "media"), "SESSIONS_PATH": str(self.work / "sessions"),
                    "PROVIDERS": "chatgpt", "ACCOUNTS__CHATGPT": accounts, "MIN_GAP_SECONDS": "0",
                    "COOLDOWN_BASE_SECONDS": "1", "MOCK_DELAY_SECONDS": "1.2", "IMAGE_BUDGET_3H": "100000",
                    "LIBRARY_CLEANUP_AT": "", "POLL_INTERVAL": "0.1"}
        settings.update(env)
        self.worker_proc = self.spawn(ROOT / "worker", self.worker_port, settings, "worker")
        ok = self.wait("http://127.0.0.1:{}/health".format(self.worker_port))
        time.sleep(0.5)
        return ok

    def health(self):
        with urllib.request.urlopen("http://127.0.0.1:{}/health".format(self.worker_port), timeout=5) as response:
            return json.loads(response.read())

    @staticmethod
    def kill(proc):
        if proc and proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)

    def stop(self):
        for proc in (self.worker_proc, self.api_proc):
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()

    def sql(self, query, params=()):
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute(query, params).fetchall()


def http(method, url, body=None, token=None):
    request = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
    if token:
        request.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, json.loads(raw) if raw else None


def send(stack, key, prompt="a square", **fields):
    boundary = uuid.uuid4().hex
    fields["prompt"] = prompt
    body = b"".join('--{}\r\nContent-Disposition: form-data; name="{}"\r\n\r\n{}\r\n'.format(boundary, k, v).encode()
                    for k, v in fields.items()) + "--{}--\r\n".format(boundary).encode()
    request = urllib.request.Request(stack.api + "/v1/images", data=body, method="POST", headers={
        "Authorization": "Bearer " + key, "Content-Type": "multipart/form-data; boundary=" + boundary})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def job_row(stack, rid):
    rows = stack.sql("SELECT status, account, conversation_id, started_at, finished_at FROM jobs WHERE id = ?", (rid,))
    return rows[0] if rows else (None, None, None, None, None)


def settled(stack, ids, seconds=40):
    deadline = time.time() + seconds
    while time.time() < deadline:
        states = [job_row(stack, rid)[0] for rid in ids]
        if all(state in ("done", "failed", "cancelled") for state in states):
            return states
        time.sleep(0.1)
    return [job_row(stack, rid)[0] for rid in ids]


def scenario_rotation(stack, key, other):
    a = send(stack, key, session="one")[1]["id"]
    b = send(stack, other, session="one")[1]["id"]
    deadline, both = time.time() + 15, set()
    while time.time() < deadline and len(both) < 2:
        running = stack.sql("SELECT account FROM jobs WHERE status = 'running' AND id IN (?, ?)", (a, b))
        both |= {row[0] for row in running} if len(running) == 2 else set()
        time.sleep(0.02)
    settled(stack, [a, b])
    record("two conversations run at once, one on each account", both == {A, B}, both)

    first = send(stack, key, session="kept")[1]["id"]
    follow = [send(stack, key, session="kept")[1]["id"] for _ in range(3)]
    settled(stack, [first] + follow)
    rows = [job_row(stack, rid) for rid in [first] + follow]
    threads = stack.sql("SELECT provider_thread_url, account FROM conversations WHERE id = ?", (rows[0][2],))
    record("follow-ups sent before the first turn ended stay on its account, in its one conversation",
           len({r[1] for r in rows}) == 1 and rows[0][1] in (A, B) and len({r[2] for r in rows}) == 1
           and all(r[0] == "done" for r in rows) and threads[0][1] == rows[0][1], rows)

    onward = send(stack, key, continue_from=first)[1]["id"]
    settled(stack, [onward])
    record("continue_from stays on the account too", job_row(stack, onward)[1] == rows[0][1], job_row(stack, onward))

    many_ids = [send(stack, key, session="load-{}".format(n))[1]["id"] for n in range(8)]
    states = settled(stack, many_ids)
    used = [job_row(stack, rid)[1] for rid in many_ids]
    record("a load spreads over both accounts", all(s == "done" for s in states) and used.count(A) >= 2 and used.count(B) >= 2,
           "{} on {}, {} on {}".format(used.count(A), A, used.count(B), B))
    # The mock names the browser that really ran the turn in its thread, as a real thread is its account's alone.
    threads = [(job_row(stack, rid)[1], stack.sql("SELECT provider_thread_url FROM conversations WHERE id = ?", (job_row(stack, rid)[2],))[0][0])
               for rid in many_ids]
    record("a job runs on the browser of the account that claimed it",
           all(("on-b-" in thread) == (account == B) for account, thread in threads), threads[:4])
    return rows[0][1]


def scenario_privacy(stack, key, token, admin_token):
    rid = send(stack, key, session="shown")[1]["id"]
    settled(stack, [rid])
    conversation = job_row(stack, rid)[2]
    seen = [http("GET", stack.api + "/v1/images/" + rid, token=key), http("GET", stack.api + "/v1/providers", token=key),
            http("GET", stack.api + "/v1/sessions", token=key), http("GET", stack.api + "/jobs/" + rid, token=token),
            http("GET", stack.api + "/conversations/" + conversation, token=token), http("GET", stack.api + "/conversations", token=token)]
    leaks = [i for i, (status, body) in enumerate(seen) if status != 200 or "account" in json.dumps(body) or B in json.dumps(body)]
    record("no answer a person reads names an account", not leaks, "answers {} leak".format(leaks))
    status, listed = http("GET", stack.api + "/admin/accounts", token=admin_token)
    names = sorted(row["account"] for row in (listed or {}).get("items") or [])
    record("the admin sees each account and what is on it", status == 200 and names == sorted([A, B])
           and all(row["jobs_done"] >= 1 for row in listed["items"]), listed)
    record("anyone else does not", http("GET", stack.api + "/admin/accounts", token=token)[0] == 403)


def scenario_tombstone(stack, key, token):
    # Three on one account and none on the other: an account that takes another's would show at once.
    with sqlite3.connect(stack.db_path) as conn:
        user = conn.execute("SELECT id FROM users WHERE email LIKE 'user@%'").fetchone()[0]
        for n in range(3):
            conn.execute("INSERT INTO conversations (id, user_id, provider, title, provider_thread_url, account) VALUES"
                         " (?, ?, 'chatgpt', 't', ?, ?)", ("doomed-{}".format(n), user, "https://chatgpt.com/c/doomed-{}".format(n), B))
    before = {name: runner["threads_deleted"] for name, runner in stack.health()["runners"].items()}
    statuses = [http("DELETE", stack.api + "/conversations/doomed-{}".format(n), token=token)[0] for n in range(3)]
    deadline = time.time() + 60
    while time.time() < deadline and stack.sql("SELECT 1 FROM thread_tombstones WHERE deleted_at IS NULL"):
        time.sleep(0.3)
    after = {name: runner["threads_deleted"] for name, runner in stack.health()["runners"].items()}
    record("a deleted conversation's thread is deleted by the account that holds it",
           all(s in (200, 204) for s in statuses) and after[B] == before[B] + 3 and after[A] == before[A],
           "{}: {} then {}".format(statuses, before, after))


def scenario_hold(stack, key, token, admin):
    pinned = send(stack, key, session="on-b")[1]["id"]
    settled(stack, [pinned])
    account = job_row(stack, pinned)[1]
    keeper = A if account == B else B
    until = "2999-01-01 00:00:00"
    with sqlite3.connect(stack.db_path) as conn:
        conn.execute("INSERT OR REPLACE INTO provider_holds (provider, until, reason) VALUES (?, ?, 'the test')", (account, until))
    code, body = send(stack, key, session="on-b")
    text = json.dumps(body)
    record("a session on a held account is refused clearly, with its credit, not naming the account",
           code == 503 and "start a new conversation or session" in text and B not in text, (code, body))

    fresh = [send(stack, key, session="fresh-{}".format(n))[1]["id"] for n in range(3)]
    settled(stack, fresh)
    record("the other account goes on with everything new", all(job_row(stack, r)[1] == keeper and job_row(stack, r)[0] == "done" for r in fresh),
           [job_row(stack, r)[:2] for r in fresh])

    served = next(p for p in http("GET", stack.api + "/v1/providers", token=key)[1]["providers"] if p["name"] == "chatgpt")
    record("the provider is still served", served["served"] is True, served)
    time.sleep(1)
    only = http("GET", stack.api + "/admin/accounts", token=admin)[1]["items"]
    budgets = {row["account"]: row["image_budget"] for row in only}
    record("a held account's budget is not counted as room", served["picture_budget"] == budgets[keeper],
           "total {} budgets {}".format(served["picture_budget"], budgets))

    with sqlite3.connect(stack.db_path) as conn:
        conn.execute("INSERT OR REPLACE INTO provider_holds (provider, until, reason) VALUES (?, ?, 'the test')", (keeper, until))
    code, body = send(stack, key, session="fresh-all-held")
    record("with every account held the provider is refused as before", code == 503 and "needs its admin" in json.dumps(body), (code, body))
    with sqlite3.connect(stack.db_path) as conn:
        conn.execute("DELETE FROM provider_holds")
    return account


def scenario_default_thread_moves(stack, key):
    rid = send(stack, key)[1]["id"]
    settled(stack, [rid])
    _, account, conversation, _, _ = job_row(stack, rid)
    keeper = A if account == B else B
    with sqlite3.connect(stack.db_path) as conn:
        conn.execute("INSERT OR REPLACE INTO provider_holds (provider, until, reason) VALUES (?, '2999-01-01 00:00:00', 'the test')", (account,))
    code, body = send(stack, key)
    moved = body.get("id")
    settled(stack, [moved] if moved else [])
    row = job_row(stack, moved)
    record("a key's thread of the day moves to a new conversation on another account", code == 202 and row[1] == keeper and row[2] != conversation and row[0] == "done",
           (code, row))
    with sqlite3.connect(stack.db_path) as conn:
        conn.execute("DELETE FROM provider_holds")


def scenario_account_needs_admin(stack, key):
    """The hold the api takes itself, from an account's own failed turn: other accounts go on."""
    rid = send(stack, key, session="misconfigured")[1]["id"]
    settled(stack, [rid])
    _, account, conversation, _, _ = job_row(stack, rid)
    keeper = A if account == B else B
    waiting = "job-waiting-on-it"
    with sqlite3.connect(stack.db_path) as conn:
        user = conn.execute("SELECT user_id FROM jobs WHERE id = ?", (rid,)).fetchone()[0]
        # Held already, so its runner cannot take the waiting job in the moment before the failure comes in.
        conn.execute("INSERT OR REPLACE INTO provider_holds (provider, until, reason) VALUES (?, '2999-01-01 00:00:00', 'the test')", (account,))
        conn.execute("INSERT INTO jobs (id, user_id, conversation_id, provider, feature, payload, status, attempts, account)"
                     " VALUES ('job-failing', ?, ?, 'chatgpt', 'image', '{\"prompt\": \"x\"}', 'running', 1, ?)", (user, conversation, account))
        conn.execute("INSERT INTO jobs (id, user_id, conversation_id, provider, feature, payload, status) VALUES (?, ?, ?, 'chatgpt',"
                     " 'image', '{\"prompt\": \"x\"}', 'pending')", (waiting, user, conversation))
    other = send(stack, key, session="still-served")[1]["id"]
    request = urllib.request.Request(stack.api + "/internal/jobs/job-failing/result", method="POST", headers={
        "Content-Type": "application/json", "X-Worker-Token": WORKER_TOKEN}, data=json.dumps({
            "status": "failed", "attempt": 1, "text": "", "media": [], "error": "memory on",
            "error_kind": "provider_misconfigured"}).encode())
    with urllib.request.urlopen(request, timeout=10) as response:
        posted = response.status
    settled(stack, [other])
    held = stack.sql("SELECT provider FROM provider_holds")
    record("an account needing its admin is held alone, and the requests waiting on it fail",
           posted == 200 and held == [(account,)] and job_row(stack, waiting)[0] == "failed", (posted, held, job_row(stack, waiting)))
    record("the other account goes on", job_row(stack, other)[0] == "done" and job_row(stack, other)[1] == keeper, job_row(stack, other))
    with sqlite3.connect(stack.db_path) as conn:
        conn.execute("DELETE FROM provider_holds")


def scenario_account_at_limit(stack, key):
    """A provider's limit holds the account for as long as the provider said, and the others go on."""
    rid = send(stack, key, session="at-limit")[1]["id"]
    settled(stack, [rid])
    _, account, conversation, _, _ = job_row(stack, rid)
    keeper = A if account == B else B
    with sqlite3.connect(stack.db_path) as conn:
        user = conn.execute("SELECT user_id FROM jobs WHERE id = ?", (rid,)).fetchone()[0]
        conn.execute("INSERT OR REPLACE INTO provider_holds (provider, until, reason) VALUES (?, '2999-01-01 00:00:00', 'the test')", (account,))
        conn.execute("INSERT INTO jobs (id, user_id, conversation_id, provider, feature, payload, status, attempts, account)"
                     " VALUES ('job-limited', ?, ?, 'chatgpt', 'image', '{\"prompt\": \"x\"}', 'running', 1, ?)", (user, conversation, account))
        before = conn.execute("SELECT quota_remaining FROM users WHERE id = ?", (user,)).fetchone()[0]
    request = urllib.request.Request(stack.api + "/internal/jobs/job-limited/result", method="POST", headers={
        "Content-Type": "application/json", "X-Worker-Token": WORKER_TOKEN}, data=json.dumps({
            "status": "failed", "attempt": 1, "text": "", "media": [], "error": "at its limit",
            "error_kind": "provider_limit", "hold_seconds": 39600}).encode())
    with urllib.request.urlopen(request, timeout=10) as response:
        posted = response.status
    left = stack.sql("SELECT (julianday(until) - julianday('now')) * 86400 FROM provider_holds WHERE provider = ?", (account,))
    after = stack.sql("SELECT quota_remaining FROM users WHERE id = ?", (user,))[0][0]
    record("an account at its limit is held for as long as the site said, and the credit comes back",
           posted == 200 and left and 39500 < left[0][0] <= 39600 and after == before + 1, (posted, left, before, after))
    fresh = send(stack, key, session="after-limit")[1]["id"]
    settled(stack, [fresh])
    record("the other account takes what comes next", job_row(stack, fresh)[:2] == ("done", keeper), job_row(stack, fresh))
    code, body = send(stack, key, session="at-limit")
    record("a session on the account at its limit is refused clearly", code == 503 and "start a new conversation or session" in json.dumps(body), (code, body))
    with sqlite3.connect(stack.db_path) as conn:
        conn.execute("DELETE FROM provider_holds")


def scenario_gone_account(stack, key, account):
    rid = send(stack, key, session="on-gone")[1]["id"]
    settled(stack, [rid])
    gone = job_row(stack, rid)[1]
    keep = A if gone == B else B
    stack.kill(stack.worker_proc)
    stack.start_worker(accounts=keep)
    # Sent while the api still counts the account as there; it stays queued, as nobody takes it now.
    queued = send(stack, key, session="on-gone")[1]["id"]
    # The api keeps a floor under its window, so the time passes in the database.
    with sqlite3.connect(stack.db_path) as conn:
        conn.execute("UPDATE provider_accounts SET last_seen = datetime('now', '-1 hour') WHERE account = ?", (gone,))
        conn.execute("UPDATE jobs SET created_at = datetime('now', '-1 hour') WHERE id = ?", (queued,))
    before = stack.sql("SELECT quota_remaining FROM users WHERE email LIKE 'user@%'")[0][0]
    state = http("GET", stack.api + "/v1/images/" + queued, token=key)[1]
    after = stack.sql("SELECT quota_remaining FROM users WHERE email LIKE 'user@%'")[0][0]
    record("a queued request on an account no worker serves any more fails and gives its credit back",
           state.get("status") == "failed" and "not being served" in (state.get("error") or "") and after == before + 1,
           "{} {!r} credits {} then {}".format(state.get("status"), state.get("error"), before, after))
    code, body = send(stack, key, session="on-gone")
    record("a session on an account no worker serves any more is refused, while another account serves",
           code == 503 and "start a new conversation or session" in json.dumps(body), (code, body))
    fresh = send(stack, key, session="after-gone")[1]["id"]
    settled(stack, [fresh])
    record("and new work goes to the account that is there", job_row(stack, fresh)[:2] == ("done", keep), job_row(stack, fresh))
    return queued


def scenario_budgets(stack, key):
    stack.kill(stack.worker_proc)
    stack.start_worker(IMAGE_BUDGET_3H="2", MOCK_DELAY_SECONDS="0.1")
    ids = [send(stack, key, session="budget-{}".format(n))[1]["id"] for n in range(7)]
    deadline = time.time() + 30
    while time.time() < deadline and sum(job_row(stack, rid)[0] == "done" for rid in ids) < 4:
        time.sleep(0.2)
    time.sleep(3)
    states = [job_row(stack, rid) for rid in ids]
    done = [row[1] for row in states if row[0] == "done"]
    waiting = [row for row in states if row[0] == "pending"]
    record("each account stops at its own budget and the rest wait", done.count(A) == 2 and done.count(B) == 2 and len(waiting) == 3,
           "done {} waiting {}".format(done, len(waiting)))
    said = next(p for p in http("GET", stack.api + "/v1/providers", token=key)[1]["providers"] if p["name"] == "chatgpt")
    record("/v1/providers says the totals", said["pictures_last_3h"] == 4 and said["picture_budget"] == 4 and said["waiting"] == 3
           and said["budget_free_at"], said)
    for rid in ids:
        http("POST", stack.api + "/v1/images/{}/cancel".format(rid), token=key)

    stack.kill(stack.worker_proc)
    # The budgets above are in memory only here: no PACING_PATH, so this worker starts at zero.
    stack.start_worker(IMAGE_TOTAL_3H="3", MOCK_DELAY_SECONDS="0.1")
    ids = [send(stack, key, session="total-{}".format(n))[1]["id"] for n in range(6)]
    deadline = time.time() + 30
    while time.time() < deadline and sum(job_row(stack, rid)[0] == "done" for rid in ids) < 3:
        time.sleep(0.2)
    time.sleep(3)
    states = [job_row(stack, rid)[0] for rid in ids]
    # Two accounts can each be mid-turn when the third picture lands, so the cap may be passed by one.
    record("the cap across accounts stops them all", states.count("done") in (3, 4) and states.count("pending") in (2, 3),
           states)
    for rid in ids:
        http("POST", stack.api + "/v1/images/{}/cancel".format(rid), token=key)


def scenario_old_threads(stack):
    with sqlite3.connect(stack.db_path) as conn:
        user = conn.execute("SELECT id FROM users LIMIT 1").fetchone()[0]
        conn.execute("INSERT INTO conversations (id, user_id, provider, title, provider_thread_url) VALUES ('old-with', ?, 'chatgpt', 't', 'https://chatgpt.com/c/old')", (user,))
        conn.execute("INSERT INTO conversations (id, user_id, provider, title) VALUES ('old-without', ?, 'grok', 't')", (user,))
    stack.kill(stack.api_proc)
    stack.start_api()
    rows = dict(stack.sql("SELECT id, account FROM conversations WHERE id IN ('old-with', 'old-without')"))
    record("a thread from before accounts belongs to the default account, a conversation with none to no account yet",
           rows == {"old-with": "chatgpt", "old-without": None}, rows)


def main():
    work = Path(tempfile.mkdtemp(prefix="provider-accounts-", dir=str(Path.home() / ".cache")))
    stack = Stack(work)
    try:
        if not stack.start_api() or not stack.start_worker():
            print("the stack did not start; logs in", work)
            return 1
        http("POST", stack.api + "/auth/register", {"email": "admin@accounts-test.com", "password": "a-long-enough-password-1", "name": "a", "invite_code": INVITE})
        admin = http("POST", stack.api + "/auth/login", {"email": "admin@accounts-test.com", "password": "a-long-enough-password-1"})[1]["token"]
        http("POST", stack.api + "/auth/register", {"email": "user@accounts-test.com", "password": "a-long-enough-password-1", "name": "u", "invite_code": INVITE})
        token = http("POST", stack.api + "/auth/login", {"email": "user@accounts-test.com", "password": "a-long-enough-password-1"})[1]["token"]
        key = http("POST", stack.api + "/auth/api-keys", {"name": "one"}, token=token)[1]["key"]
        other = http("POST", stack.api + "/auth/api-keys", {"name": "two"}, token=token)[1]["key"]

        health = stack.health()
        record("the worker has a runner for each account", sorted(health["runners"]) == sorted([A, B])
               and sorted(health["providers"]) == sorted([A, B]) and health["providers"][B]["provider"] == "chatgpt", sorted(health["runners"]))
        account = scenario_rotation(stack, key, other)
        scenario_privacy(stack, key, token, admin)
        scenario_tombstone(stack, key, token)
        scenario_hold(stack, key, token, admin)
        scenario_default_thread_moves(stack, key)
        scenario_account_needs_admin(stack, key)
        scenario_account_at_limit(stack, key)
        scenario_gone_account(stack, key, account)
        scenario_budgets(stack, key)
        scenario_old_threads(stack)
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
