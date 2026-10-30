#!/usr/bin/env python3
"""Stress for the ChatGPT picture MCP server: many servers at once against a real api and a mock worker
of this script's own (temp database and media, free ports). No Docker, no account, no provider.

    ~/.venvs/aip-mcp/bin/python tests/stress_mcp.py [--keep]

The api and the worker run under the cloakbrowser venv's python (CLOAKBROWSER_VENV), the MCP servers
under this one. It never touches the real stack. Every scenario ends with the credits accounted for to
the unit, so a charge or a refund lost under load shows. Prints N/N PASSED.
"""

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import anyio
from mcp import Client, StdioServerParameters
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp_server" / "chatgpt_images.py"
INVITE, WORKER_TOKEN = "stress-invite", "stress-worker-token"
QUOTA = 1000
results = []


def record(name, ok, detail=""):
    results.append(ok)
    print("[{}] {}  {}".format("PASS" if ok else "FAIL", name, detail), flush=True)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Stack:
    def __init__(self, work):
        self.work, self.media = work, work / "media"
        (work / "db").mkdir()
        self.media.mkdir()
        venv = Path(os.environ.get("CLOAKBROWSER_VENV", str(Path.home() / "cloakbrowser-env")))
        self.python = str(venv / "bin" / "python")
        self.api_port, self.worker_port = free_port(), free_port()
        self.api = "http://127.0.0.1:{}".format(self.api_port)
        self.db_path = work / "db" / "app.db"
        self.api_proc = self.worker_proc = None
        self.runs = 0

    def spawn(self, cwd, port, env, name):
        self.runs += 1
        full = dict(os.environ, PYTHONPATH=str(cwd), PYTHONUNBUFFERED="1", **env)
        log = open(self.work / "{}-{}.log".format(name, self.runs), "wb")
        return subprocess.Popen([self.python, "-m", "uvicorn", "src.main:app", "--host", "127.0.0.1",
                                 "--port", str(port)], cwd=str(cwd), env=full, stdout=log, stderr=subprocess.STDOUT)

    def wait(self, url, seconds=40):
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=2):
                    return True
            except Exception:
                time.sleep(0.2)
        return False

    def start_api(self):
        self.api_proc = self.spawn(ROOT / "api", self.api_port, {
            "DB_PATH": str(self.db_path), "MEDIA_PATH": str(self.media), "JWT_SECRET": "stress-secret",
            "INVITE_CODE": INVITE, "WORKER_TOKEN": WORKER_TOKEN, "DEFAULT_QUOTA": str(QUOTA),
            "JOB_LEASE_SECONDS": "6", "NO_WORKER_SECONDS": "25"}, "api")
        return self.wait(self.api + "/health")

    def start_worker(self, delay="0.2", budget="100000"):
        # The default image budget, 40 in three hours, would hold the load scenarios (measured: 40 of 100
        # done, the rest queued); it has a scenario of its own.
        self.worker_proc = self.spawn(ROOT / "worker", self.worker_port, {
            "API_URL": self.api, "WORKER_TOKEN": WORKER_TOKEN, "PROVIDER_MODE": "mock", "MEDIA_PATH": str(self.media),
            "SESSIONS_PATH": str(self.work / "sessions"), "PROVIDERS": "chatgpt,grok,gemini", "MIN_GAP_SECONDS": "0",
            "COOLDOWN_BASE_SECONDS": "1", "MOCK_DELAY_SECONDS": delay, "IMAGE_BUDGET_3H": budget,
            "LIBRARY_CLEANUP_AT": ""}, "worker")
        return self.wait("http://127.0.0.1:{}/health".format(self.worker_port))

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


def http(method, url, body=None, token=None, timeout=60):
    request = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
    if token:
        request.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        return exc.code, None


def form(fields):
    boundary = uuid.uuid4().hex
    body = b"".join('--{}\r\nContent-Disposition: form-data; name="{}"\r\n\r\n{}\r\n'.format(boundary, k, v).encode()
                    for k, v in fields.items()) + "--{}--\r\n".format(boundary).encode()
    return body, "multipart/form-data; boundary=" + boundary


def send_raw(stack, key, prompt):
    body, ctype = form({"prompt": prompt})
    request = urllib.request.Request(stack.api + "/v1/images", data=body, method="POST",
                                     headers={"Authorization": "Bearer " + key, "Content-Type": ctype})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, None


class Person:
    def __init__(self, stack, label):
        self.stack, self.email = stack, "{}-{}@stress.example.com".format(label, uuid.uuid4().hex[:8])
        http("POST", stack.api + "/auth/register", {"email": self.email, "password": "stress-password-1",
                                                    "name": label, "invite_code": INVITE})
        self.token = http("POST", stack.api + "/auth/login", {"email": self.email,
                                                              "password": "stress-password-1"})[1]["token"]
        self.id = http("GET", stack.api + "/auth/me", token=self.token)[1]["id"]

    def key(self, name="stress key"):
        return http("POST", self.stack.api + "/auth/api-keys", {"name": name}, token=self.token)[1]["key"]

    def credits(self):
        return http("GET", self.stack.api + "/auth/me", token=self.token)[1]["quota_remaining"]

    def set_credits(self, value):
        with sqlite3.connect(self.stack.db_path) as conn:
            conn.execute("UPDATE users SET quota_remaining = ? WHERE id = ?", (value, self.id))


def server(stack, key):
    return StdioServerParameters(command=sys.executable, args=[str(SERVER)],
                                 env={"AIP_API_URL": stack.api, "AIP_API_KEY": key, "AIP_POLL_SECONDS": "0.3"})


def jobs_of(stack, person):
    return {row[0]: row[1] for row in stack.sql("SELECT id, status FROM jobs WHERE user_id = ?", (person.id,))}


def still_live(stack, person):
    return [i for i, s in jobs_of(stack, person).items() if s not in ("done", "failed", "cancelled")]


async def one_set(stack, key, prompts, folder, wait=300):
    async with Client(server(stack, key)) as client:
        return await client.call_tool("generate_images", {"prompts": prompts, "save_dir": str(folder),
                                                          "wait_seconds": wait}, read_timeout_seconds=wait + 60)


async def many_sets(stack, work):
    """Five keys of three people, twenty prompts each, all at once."""
    people = [Person(stack, "many{}".format(n)) for n in range(3)]
    owners = [people[0], people[0], people[1], people[1], people[2]]
    keys = [owner.key("key {}".format(n)) for n, owner in enumerate(owners)]
    prompts = {n: ["key{} prompt{} {}".format(n, p, uuid.uuid4().hex[:6]) for p in range(20)] for n in range(5)}
    answers = {}
    began = time.time()

    async def run(n):
        answers[n] = await one_set(stack, keys[n], prompts[n], work / "many" / str(n))

    async with anyio.create_task_group() as group:
        for n in range(5):
            group.start_soon(run, n)
    took = time.time() - began

    fates = {n: [i.get("status") for i in (a.structured_content or {}).get("requests") or []]
             for n, a in answers.items()}
    record("five keys, twenty prompts each at once: every request ends done, and every tool call answers",
           all(not a.is_error for a in answers.values()) and all(f == ["done"] * 20 for f in fates.values()),
           "100 requests in {:.0f}s; {}".format(took, {n: sum(1 for s in f if s != "done") for n, f in fates.items()}))

    wrong, files, previews = [], 0, 0
    for n, answer in answers.items():
        previews += sum(1 for b in answer.content if getattr(b, "type", "") == "image")
        for item in (answer.structured_content or {}).get("requests") or []:
            for picture in item.get("pictures") or []:
                files += 1
                kept = json.loads(Path(picture["record"]).read_text(encoding="utf-8"))
                if kept.get("prompt") != item["prompt"] or item["prompt"] not in kept.get("text", ""):
                    wrong.append((n, item["prompt"], kept.get("text", "")[:60]))
                with Image.open(picture["path"]) as shown:
                    shown.verify()
    record("each of the 100 pictures is its own prompt's, saved whole, with its preview: no crossed answers",
           not wrong and files == 100 and previews == 100, "files {} previews {} crossed {}".format(files, previews, wrong[:3]))

    threads = {}
    for n, answer in answers.items():
        found = set()
        for item in (answer.structured_content or {}).get("requests") or []:
            for picture in item.get("pictures") or []:
                kept = json.loads(Path(picture["record"]).read_text(encoding="utf-8"))
                found.update(re.findall(r"\[thread=([^\]]+)\]", kept.get("text", "")))
        threads[n] = found
    all_threads = [t for found in threads.values() for t in found]
    record("each key keeps one thread, and no two keys share one, even of one person",
           all(len(found) == 1 for found in threads.values()) and len(set(all_threads)) == 5, repr(threads))
    marks = ", ".join("?" * len(people))
    conversations = [r[0] for r in stack.sql(
        "SELECT COUNT(*) FROM api_key_conversations a JOIN api_keys k ON k.id = a.key_id"
        " WHERE k.user_id IN ({})".format(marks), tuple(p.id for p in people))]
    record("each key has one conversation row", conversations == [5], repr(conversations))
    spent = {owner.email[:5]: owner.credits() for owner in people}
    record("the credits are exact: 40, 40 and 20 taken",
           [p.credits() for p in people] == [QUOTA - 40, QUOTA - 40, QUOTA - 20], repr(spent))


def first_requests_race(stack):
    """Twenty first requests of one new key at the same moment must open one conversation."""
    person = Person(stack, "race")
    key = person.key()
    with concurrent.futures.ThreadPoolExecutor(20) as pool:
        got = list(pool.map(lambda n: send_raw(stack, key, "race {}".format(n))[0], range(20)))
    deadline = time.time() + 60
    while still_live(stack, person) and time.time() < deadline:
        time.sleep(0.3)
    conversations = stack.sql("SELECT COUNT(DISTINCT conversation_id) FROM jobs WHERE user_id = ?", (person.id,))[0][0]
    rows = stack.sql("SELECT COUNT(*) FROM conversations WHERE user_id = ?", (person.id,))[0][0]
    record("twenty first requests of one key at once open one conversation, with no error",
           got == [202] * 20 and conversations == 1 and rows == 1,
           "answers {} job conversations {} rows {}".format(sorted(set(got)), conversations, rows))


def credit_race(stack):
    """Five credits, twenty requests at once: exactly five go, and the balance never goes below nothing."""
    person = Person(stack, "credit")
    key = person.key()
    person.set_credits(5)
    with concurrent.futures.ThreadPoolExecutor(20) as pool:
        got = list(pool.map(lambda n: send_raw(stack, key, "credit {}".format(n))[0], range(20)))
    deadline = time.time() + 60
    while still_live(stack, person) and time.time() < deadline:
        time.sleep(0.3)
    done = sum(1 for s in jobs_of(stack, person).values() if s == "done")
    record("five credits and twenty requests at once: five taken, fifteen refused 402, the balance at nothing",
           got.count(202) == 5 and got.count(402) == 15 and done == 5 and person.credits() == 0,
           "202 {} 402 {} other {} done {} credits {}".format(
               got.count(202), got.count(402), [g for g in got if g not in (202, 402)], done, person.credits()))


async def set_runs_out_of_credit(stack, work):
    person = Person(stack, "short")
    key = person.key()
    person.set_credits(7)
    answer = await one_set(stack, key, ["short {}".format(n) for n in range(20)], work / "short")
    items = (answer.structured_content or {}).get("requests") or []
    fates = [i.get("status") for i in items]
    record("a set of twenty with seven credits: seven done, the eighth refused, twelve not sent, nothing charged wrong",
           not answer.is_error and fates == ["done"] * 7 + ["refused"] + ["not sent"] * 12 and person.credits() == 0,
           "error {} fates {} credits {}".format(answer.is_error, fates, person.credits()))


async def cancels_under_load(stack, work):
    """Every other request of a set is cancelled while the set runs."""
    person = Person(stack, "cancel")
    key = person.key()
    before = person.credits()
    sent = [send_raw(stack, key, "cancel me {}".format(n))[1]["id"] for n in range(12)]

    async def cancel_some():
        async with Client(server(stack, key)) as client:
            async with anyio.create_task_group() as group:
                for request_id in sent[::2]:
                    group.start_soon(client.call_tool, "cancel_image", {"request_id": request_id})
    await cancel_some()
    deadline = time.time() + 90
    while still_live(stack, person) and time.time() < deadline:
        await anyio.sleep(0.3)
    fates = jobs_of(stack, person)
    cancelled = sum(1 for s in fates.values() if s == "cancelled")
    done = sum(1 for s in fates.values() if s == "done")
    record("twelve sent and six cancelled at once while they run: credits exact, nothing left running",
           not still_live(stack, person) and cancelled + done == 12 and person.credits() == before - done,
           "cancelled {} done {} credits {} -> {}".format(cancelled, done, before, person.credits()))


async def worker_dies_mid_set(stack, work):
    person = Person(stack, "killed")
    key = person.key()
    before = person.credits()
    prompts = ["killed {}".format(n) for n in range(10)]
    answers = {}

    async def run():
        answers["set"] = await one_set(stack, key, prompts, work / "killed", wait=200)

    async with anyio.create_task_group() as group:
        group.start_soon(run)
        deadline = time.time() + 60
        while time.time() < deadline and sum(1 for s in jobs_of(stack, person).values() if s == "done") < 2:
            await anyio.sleep(0.2)
        stack.kill(stack.worker_proc)
        await anyio.sleep(3)
        await anyio.to_thread.run_sync(stack.start_worker)
    answer = answers["set"]
    items = (answer.structured_content or {}).get("requests") or []
    fates = [i.get("status") for i in items]
    done = fates.count("done")
    missing = [i["prompt"] for i in items if i.get("status") == "done" and not i.get("pictures")]
    record("the worker killed mid-set and back: the tool answers, no prompt left running, credits exact",
           not answer.is_error and len(items) == 10 and not still_live(stack, person) and not missing
           and person.credits() == before - sum(1 for s in jobs_of(stack, person).values() if s == "done"),
           "error {} said {!r} fates {} credits {} -> {}".format(
               answer.is_error, "" if not answer.is_error else answer.content[0].text[:120], fates, before, person.credits()))
    return done


async def api_restarts_mid_set(stack, work):
    """The api restarts while a set waits: a code reload on the real stack does just this."""
    person = Person(stack, "restart")
    key = person.key()
    before = person.credits()
    prompts = ["restart {}".format(n) for n in range(10)]
    answers = {}

    async def run():
        answers["set"] = await one_set(stack, key, prompts, work / "restart", wait=200)

    async with anyio.create_task_group() as group:
        group.start_soon(run)
        deadline = time.time() + 60
        while time.time() < deadline and sum(1 for s in jobs_of(stack, person).values() if s == "done") < 2:
            await anyio.sleep(0.2)
        stack.kill(stack.api_proc)
        await anyio.sleep(2)
        await anyio.to_thread.run_sync(stack.start_api)
    answer = answers["set"]
    items = (answer.structured_content or {}).get("requests") or []
    fates = [i.get("status") for i in items]
    record("the api restarted mid-set: the tool keeps waiting and answers every prompt, none lost",
           not answer.is_error and fates == ["done"] * 10 and person.credits() == before - 10,
           "error {} said {!r} fates {} credits {} -> {}".format(
               answer.is_error, answer.content[0].text[:140] if answer.is_error else "", fates, before, person.credits()))


async def api_restarts_mid_picture(stack, work):
    person = Person(stack, "restart1")
    key = person.key()
    answers = {}

    async def run():
        async with Client(server(stack, key)) as client:
            answers["one"] = await client.call_tool("generate_image", {"prompt": "one through a restart",
                                                                       "save_dir": str(work / "restart1")},
                                                    read_timeout_seconds=120)

    async with anyio.create_task_group() as group:
        group.start_soon(run)
        # Once the request is in: before that, a refused connection rightly is the tool's error.
        deadline = time.time() + 30
        while time.time() < deadline and not jobs_of(stack, person):
            await anyio.sleep(0.05)
        stack.kill(stack.api_proc)
        await anyio.sleep(2)
        await anyio.to_thread.run_sync(stack.start_api)
    answer = answers["one"]
    record("the api restarted during one picture: the tool keeps waiting and saves it",
           not answer.is_error and (answer.structured_content or {}).get("status") == "done",
           "error {} said {!r}".format(answer.is_error, answer.content[0].text[:140] if answer.content else ""))


async def big_references(stack, work):
    """Three requests at once, each with four references of 2.4 MB: every picture in its place."""
    person = Person(stack, "big")
    key = person.key()
    folder = work / "big-refs"
    folder.mkdir()
    paths, digests = {}, {}
    for r in range(3):
        for n in range(4):
            blob = Image.effect_noise((1100, 720), 90).convert("RGB")
            path = folder / "r{}-{}.png".format(r, n)
            blob.save(path, "PNG")
            paths.setdefault(r, []).append(str(path))
            digests.setdefault(r, []).append(hashlib.sha256(path.read_bytes()).hexdigest()[:16])
    sizes = [Path(p).stat().st_size for p in paths[0]]
    answers = {}

    async def run(r):
        async with Client(server(stack, key)) as client:
            answers[r] = await client.call_tool("generate_image", {"prompt": "four together {}".format(r),
                                                                   "reference_paths": paths[r],
                                                                   "save_dir": str(work / "big-out")},
                                                read_timeout_seconds=120)

    async with anyio.create_task_group() as group:
        for r in range(3):
            group.start_soon(run, r)
    good = []
    for r, answer in answers.items():
        text = (answer.structured_content or {}).get("text") or ""
        good.append(not answer.is_error and re.findall(r"sha256 (\w+)", text) == digests[r])
    record("three requests with four large references each at once: each hands over its own, in order",
           all(good) and len(good) == 3,
           "sizes {} ok {} first said {!r}".format(sizes, good, answers[0].content[0].text[:100]))


async def no_worker(stack, work):
    person = Person(stack, "alone")
    key = person.key()
    before = person.credits()
    stack.kill(stack.worker_proc)
    deadline = time.time() + 60
    async with Client(server(stack, key)) as client:
        while time.time() < deadline:
            status = await client.call_tool("account_status", {})
            if (status.structured_content or {}).get("chatgpt_served") is False:
                break
            await anyio.sleep(1)
        refused = await client.call_tool("generate_image", {"prompt": "nobody home"}, read_timeout_seconds=30)
    await anyio.to_thread.run_sync(stack.start_worker)
    record("with no worker, account_status says so and a picture is refused uncharged, saying why",
           (status.structured_content or {}).get("chatgpt_served") is False and refused.is_error
           and "503" in refused.content[0].text and person.credits() == before,
           "served {} said {!r} credits {} -> {}".format(
               (status.structured_content or {}).get("chatgpt_served"), refused.content[0].text[:110], before, person.credits()))


async def image_budget(stack, work):
    """The worker's image budget spent (40 in three hours by default): what the caller then sees."""
    person = Person(stack, "budget")
    key = person.key()
    before = person.credits()
    stack.kill(stack.worker_proc)
    await anyio.to_thread.run_sync(lambda: stack.start_worker(budget="3"))
    answer = await one_set(stack, key, ["budget {}".format(n) for n in range(5)], work / "budget", wait=25)
    items = (answer.structured_content or {}).get("requests") or []
    fates = [i.get("status") for i in items]
    message = (answer.structured_content or {}).get("message") or ""
    print("  budget: fates {}; said {!r}".format(fates, message[-220:]), flush=True)
    async with Client(server(stack, key)) as client:
        told = await client.call_tool("account_status", {})
    said = told.structured_content or {}
    record("past the worker's image budget the tool does not hang: the pictures within it are done, the rest "
           "say they wait, with their ids, and credits are taken only for what was sent",
           not answer.is_error and fates.count("done") == 3 and fates.count("done") + sum(
               1 for s in fates if s in ("queued", "running")) == 5
           and "get_image" in message and person.credits() == before - 5,
           "fates {} credits {} -> {}".format(fates, before, person.credits()))
    record("account_status says the budget is spent, until when, and how many wait",
           said.get("pictures_last_3h") == 3 and said.get("picture_budget") == 3 and said.get("budget_free_at")
           and said.get("waiting") == 2 and "budget is spent" in (said.get("message") or ""),
           repr(said.get("message")))
    # The waiting ones are cancelled, or they would sit behind the budget for three hours.
    async with Client(server(stack, key)) as client:
        for item in items:
            if item.get("status") in ("queued", "running"):
                await client.call_tool("cancel_image", {"request_id": item["request_id"]})
    stack.kill(stack.worker_proc)
    await anyio.to_thread.run_sync(stack.start_worker)


async def scenarios(stack, work):
    await image_budget(stack, work)
    await many_sets(stack, work)
    await anyio.to_thread.run_sync(first_requests_race, stack)
    await anyio.to_thread.run_sync(credit_race, stack)
    await set_runs_out_of_credit(stack, work)
    await cancels_under_load(stack, work)
    await big_references(stack, work)
    await worker_dies_mid_set(stack, work)
    await api_restarts_mid_set(stack, work)
    await api_restarts_mid_picture(stack, work)
    await no_worker(stack, work)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="keep the temp folder and its logs")
    args = parser.parse_args()
    work = Path(tempfile.mkdtemp(prefix="stress-mcp-", dir=str(Path.home() / ".cache")))
    stack = Stack(work)
    try:
        if not stack.start_api() or not stack.start_worker():
            record("the stack starts", False, str(work))
        else:
            Person(stack, "first")  # The first account is the admin; no scenario depends on being it.
            time.sleep(2)
            anyio.run(scenarios, stack, work)
    finally:
        stack.stop()
        if args.keep:
            print("kept", work)
        else:
            shutil.rmtree(work, ignore_errors=True)
    passed = sum(1 for ok in results if ok)
    print("{}/{} PASSED".format(passed, len(results)))
    return 0 if results and passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
