#!/usr/bin/env python3
"""Acceptance gate for the AI platform.

One command, own ports, own temp database and media directory, PASS/FAIL table,
non-zero exit on failure, cleans up after itself.

    python acceptance.py           mock providers, ~10s, safe to rerun
    python acceptance.py --real    drives the real ChatGPT browser session

Only the provider boundary is faked in mock mode. The API, the database, the job
queue, the worker poll loop and media storage all run for real either way.

Standard library only, so it runs under any python3; the services themselves are
launched with the cloakbrowser venv.
"""

import argparse
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

CHECKS = (
    "api health",
    "register (invite code)",
    "login returns jwt",
    "auth rejects bad token",
    "chat job completes",
    "image job produces file",
    "video script job returns text",
    "media listing scoped to user",
    "thread reused within a conversation",
    "threads never cross conversations",
    "non image deliverable is kept",
    "non image deliverable is kept when asked in vietnamese",
    "a follow-up turn packages what the first one made",
    "a conversation's media downloads as one zip",
    "a job settles exactly once",
    "a provider error fails the job and refunds",
    "a stranded job is reclaimed",
    "a running job can be cancelled",
    "memory on refuses the turn and refunds",
    "health reports the provider's memory setting",
    "health shows code version and pacing",
    "the provider's error banner is recognised by shape",
)

# Phrases the mock provider reacts to, so failure modes can be exercised on purpose.
SLOW_PHRASE = "take your time"
BROKEN_PHRASE = "pretend the provider broke"
MEMORY_PHRASE = "pretend memory is on"

THREAD_MARKER = re.compile(r"\[thread=([^\]]+)\]")


class Check:
    def __init__(self, name):
        self.name = name
        self.ok = False
        self.skipped = False
        self.detail = "not reached"

    def passed(self, detail=""):
        self.ok = True
        self.detail = detail

    def failed(self, detail):
        self.ok = False
        self.detail = detail

    def skip(self, detail):
        # A check that cannot be exercised in this mode says so, out loud, and
        # is counted neither as a pass nor a failure.
        self.ok = False
        self.skipped = True
        self.detail = detail


def http(method, url, body=None, token=None, timeout=30, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    for name, value in (headers or {}).items():
        req.add_header(name, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            parsed = json.loads(raw) if raw.strip() else None
        except ValueError:
            parsed = raw
        return exc.code, parsed
    except Exception as exc:
        return 0, "{}: {}".format(type(exc).__name__, exc)


def http_bytes(url, token, timeout=30):
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except Exception as exc:
        return 0, "{}: {}".format(type(exc).__name__, exc).encode()


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_healthy(url, timeout):
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        status, body = http("GET", url, timeout=3)
        if status == 200:
            return True, ""
        last = "status {} body {}".format(status, body)
        time.sleep(0.3)
    return False, last or "timeout"


def poll_job(api, job_id, token, timeout):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        status, body = http("GET", "{}/jobs/{}".format(api, job_id), token=token)
        if status != 200:
            return None, "job fetch returned {} {}".format(status, body)
        last = body
        if body.get("status") == "done":
            return body, ""
        if body.get("status") == "failed":
            return None, "job failed: {}".format(body.get("error"))
        time.sleep(0.4)
    return None, "job still {} after {}s".format((last or {}).get("status"), timeout)


def venv_python():
    venv = Path(os.environ.get("CLOAKBROWSER_VENV", str(Path.home() / "cloakbrowser-env")))
    python = venv / "bin" / "python"
    if not python.exists():
        sys.exit("cloakbrowser venv not found at {}; set CLOAKBROWSER_VENV".format(venv))
    return str(python)


def ensure_deps(python):
    probe = subprocess.run(
        [python, "-c", "import fastapi, uvicorn, jwt, bcrypt, httpx, email_validator"],
        capture_output=True,
    )
    if probe.returncode == 0:
        return
    print("installing service dependencies into the venv (one time)...")
    for req in ("api/requirements.txt", "worker/requirements.txt"):
        subprocess.run(
            [python, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", str(ROOT / req)],
            check=True,
        )


def start_service(python, cwd, port, env_extra, log_path):
    env = os.environ.copy()
    env.update(env_extra)
    env["PYTHONPATH"] = str(cwd)
    env["PYTHONUNBUFFERED"] = "1"
    log = open(log_path, "wb")
    proc = subprocess.Popen(
        [python, "-m", "uvicorn", "src.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(cwd),
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    return proc, log


def stop(proc, log):
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    if log:
        log.close()


def tail(path, lines=15):
    try:
        content = Path(path).read_text(errors="replace").strip().splitlines()
    except OSError:
        return "(no log)"
    return "\n".join("      | " + line for line in content[-lines:]) or "      | (empty)"


def run_checks(api, media_dir, real, invite_code, worker_token, worker_health, restart_worker,
               python):
    # Must exceed the provider's own ceiling (REPLY_TIMEOUT is 300s) plus the
    # first-use browser launch, otherwise the gate reports a timeout that only
    # the gate caused.
    job_timeout = 420 if real else 30
    checks = [Check(n) for n in CHECKS]
    c = dict(zip([x.name for x in checks], checks))
    stamp = str(int(time.time() * 1000))
    # A plain domain: email-validator rejects reserved suffixes such as .local.
    user_a = "acc-a-{}@aiplatform-acceptance.com".format(stamp)
    user_b = "acc-b-{}@aiplatform-acceptance.com".format(stamp)
    password = "acceptance-pw-123"
    token = None
    media_id = None

    status, body = http("GET", api + "/health")
    if status == 200 and isinstance(body, dict) and body.get("status") == "ok":
        c["api health"].passed("status 200")
    else:
        c["api health"].failed("status {} body {}".format(status, body))
        return checks

    bad, _ = http("POST", api + "/auth/register",
                  {"email": user_a, "password": password, "name": "A", "invite_code": "definitely-wrong"})
    good, gbody = http("POST", api + "/auth/register",
                       {"email": user_a, "password": password, "name": "A", "invite_code": invite_code})
    if bad == 403 and good == 201:
        c["register (invite code)"].passed("wrong invite 403, valid invite 201")
    else:
        c["register (invite code)"].failed("wrong invite {} valid invite {} body {}".format(bad, good, gbody))
        return checks

    status, body = http("POST", api + "/auth/login", {"email": user_a, "password": password})
    if status == 200 and isinstance(body, dict) and body.get("token"):
        token = body["token"]
        me_status, me = http("GET", api + "/auth/me", token=token)
        if me_status == 200 and me.get("email") == user_a:
            c["login returns jwt"].passed("token accepted by /auth/me")
        else:
            c["login returns jwt"].failed("/auth/me returned {} {}".format(me_status, me))
            return checks
    else:
        c["login returns jwt"].failed("status {} body {}".format(status, body))
        return checks

    bad_status, _ = http("GET", api + "/auth/me", token="not-a-real-token")
    none_status, _ = http("GET", api + "/auth/me")
    if bad_status == 401 and none_status == 401:
        c["auth rejects bad token"].passed("garbage 401, missing 401")
    else:
        c["auth rejects bad token"].failed("garbage {} missing {}".format(bad_status, none_status))

    status, body = http("POST", api + "/chat",
                        {"provider": "chatgpt", "message": "Reply with the single word: pong"},
                        token=token)
    if status == 202 and body.get("job_id"):
        job, err = poll_job(api, body["job_id"], token, job_timeout)
        text = ((job or {}).get("result") or {}).get("text") or ""
        if job and text.strip():
            c["chat job completes"].passed("{} chars of reply".format(len(text)))
        else:
            c["chat job completes"].failed(err or "empty reply")
    else:
        c["chat job completes"].failed("status {} body {}".format(status, body))

    status, body = http("POST", api + "/image/generate",
                        {"provider": "chatgpt", "prompt": "a plain red circle on white"},
                        token=token)
    if status == 202 and body.get("job_id"):
        job, err = poll_job(api, body["job_id"], token, job_timeout)
        ids = ((job or {}).get("result") or {}).get("media") or []
        if job and ids:
            media_id = ids[0]
            mstatus, mbody = http("GET", "{}/media/{}".format(api, media_id), token=token)
            filename = (mbody or {}).get("filename") if mstatus == 200 else None
            path = Path(media_dir) / filename if filename else None
            size = path.stat().st_size if path and path.exists() else 0
            if size > 0:
                c["image job produces file"].passed("{} bytes at {}".format(size, filename))
            else:
                c["image job produces file"].failed("no file on disk for media {} ({})".format(media_id, filename))
        else:
            c["image job produces file"].failed(err or "no media returned")
    else:
        c["image job produces file"].failed("status {} body {}".format(status, body))

    if media_id:
        status, body = http("POST", api + "/video/script",
                            {"provider": "chatgpt", "media_id": media_id, "duration": 5},
                            token=token)
        if status == 202 and body.get("job_id"):
            job, err = poll_job(api, body["job_id"], token, job_timeout)
            text = ((job or {}).get("result") or {}).get("text") or ""
            if job and text.strip():
                c["video script job returns text"].passed("{} chars of script".format(len(text)))
            else:
                c["video script job returns text"].failed(err or "empty script")
        else:
            c["video script job returns text"].failed("status {} body {}".format(status, body))
    else:
        c["video script job returns text"].failed("skipped, no media id from the image check")

    status, mine = http("GET", api + "/media", token=token)
    mine_total = (mine or {}).get("total") if status == 200 else None
    http("POST", api + "/auth/register",
         {"email": user_b, "password": password, "name": "B", "invite_code": invite_code})
    bstatus, blogin = http("POST", api + "/auth/login", {"email": user_b, "password": password})
    btoken = (blogin or {}).get("token") if bstatus == 200 else None
    ostatus, theirs = http("GET", api + "/media", token=btoken)
    their_total = (theirs or {}).get("total") if ostatus == 200 else None
    leak = 404
    if media_id and btoken:
        leak, _ = http("GET", "{}/media/{}".format(api, media_id), token=btoken)
    if mine_total and mine_total >= 1 and their_total == 0 and leak == 404:
        c["media listing scoped to user"].passed(
            "owner sees {}, other user sees 0, cross fetch 404".format(mine_total))
    else:
        c["media listing scoped to user"].failed(
            "owner {} other {} cross fetch {}".format(mine_total, their_total, leak))

    def chat_once(message, conversation_id=None):
        status, body = http("POST", api + "/chat",
                            {"provider": "chatgpt", "message": message,
                             "conversation_id": conversation_id}, token=token)
        if status != 202 or not (body or {}).get("job_id"):
            return None, "status {} body {}".format(status, body), None
        job, err = poll_job(api, body["job_id"], token, job_timeout)
        return job, err, body["conversation_id"]

    def thread_of(job):
        found = THREAD_MARKER.search(((job or {}).get("result") or {}).get("text") or "")
        return found.group(1) if found else None

    if real:
        # Against the real provider the thread is a chatgpt.com url the client
        # never sees, so continuity is measured the only way that matters: does
        # the model still know what it was told a turn ago.
        secret = "teal-{}".format(stamp[-5:])
        _, err_a, conv = chat_once(
            "Remember this word for later: {}. Reply with just: ok".format(secret))
        back, err_b, _ = chat_once(
            "What word did I ask you to remember? Reply with that word and nothing else.", conv)
        recalled = ((back or {}).get("result") or {}).get("text") or ""
        if secret in recalled:
            c["thread reused within a conversation"].passed("the model recalled {}".format(secret))
        else:
            c["thread reused within a conversation"].failed(
                "asked for {}, got {!r} {}".format(secret, recalled[:80], err_a or err_b or ""))

        fresh, err_c, _ = chat_once(
            "What word did I ask you to remember? Reply with that word and nothing else.")
        leaked = ((fresh or {}).get("result") or {}).get("text") or ""
        if secret not in leaked:
            c["threads never cross conversations"].passed(
                "a new conversation does not know {}".format(secret))
        else:
            c["threads never cross conversations"].failed(
                "a new conversation knew {}: {!r} {}".format(secret, leaked[:80], err_c or ""))
    else:
        first, err_a, conv = chat_once("first turn, opening a thread")
        second, err_b, _ = chat_once("second turn, same thread", conv) if conv else (None, err_a, None)
        t1, t2 = thread_of(first), thread_of(second)
        if t1 and t2 and t1 == t2:
            c["thread reused within a conversation"].passed("both turns on {}".format(t1[:28]))
        else:
            c["thread reused within a conversation"].failed(
                "first {} second {} {}".format(t1 or "no thread reported",
                                               t2 or "no thread reported", err_a or err_b or ""))

        other, err_c, _ = chat_once("a turn that belongs to a different conversation")
        t3 = thread_of(other)
        if t1 and t3 and t1 != t3:
            c["threads never cross conversations"].passed("{} and {}".format(t1[:16], t3[:16]))
        else:
            c["threads never cross conversations"].failed(
                "conversation one {} conversation two {} {}".format(
                    t1 or "no thread reported", t3 or "no thread reported", err_c or ""))

    def check_zip(check_name, message, conversation_id=None):
        done, err, _ = chat_once(message, conversation_id)
        result = (done or {}).get("result") or {}
        # A file can arrive alongside a picture, so look for the one that is a file.
        for media_id in result.get("media") or []:
            mstatus, meta = http("GET", "{}/media/{}".format(api, media_id), token=token)
            if mstatus != 200 or (meta or {}).get("type") == "image":
                continue
            fstatus, blob = http_bytes("{}/media/{}/file".format(api, media_id), token)
            if fstatus == 200 and blob[:2] == b"PK":
                try:
                    names = zipfile.ZipFile(io.BytesIO(blob)).namelist()
                except zipfile.BadZipFile:
                    names = []
                if names:
                    c[check_name].passed("{} bytes, type {}, entries {}".format(
                        len(blob), meta.get("type"), names[:4]))
                    return
            c[check_name].failed("media {} fetched {} first bytes {!r}".format(
                meta.get("type"), fstatus, blob[:4] if isinstance(blob, bytes) else blob))
            return
        c[check_name].failed(
            err or "nothing but pictures came back: {}".format(
                (result.get("text") or "")[:120] or "no reply"))

    check_zip("non image deliverable is kept",
              "build me a zip file holding a.txt and b.txt")
    # The same request in the language the user actually types in. The button
    # ChatGPT offers is labelled in that language, and matching on the English
    # word let a real request through unnoticed.
    check_zip("non image deliverable is kept when asked in vietnamese",
              "Tạo cho tôi một file zip chứa hai file text tên a.txt và b.txt")

    # The journey a real user took, which passed every check above while being
    # broken: make something, then in the same conversation ask for it packaged.
    # Its download button was labelled neither in English nor with a file name.
    drawn, draw_err, conv_pack = chat_once("vẽ cho tôi một hình vuông màu xanh")
    if not conv_pack:
        c["a follow-up turn packages what the first one made"].failed(
            draw_err or "the first turn produced no conversation")
    else:
        check_zip("a follow-up turn packages what the first one made",
                  "gói tấm hình vừa rồi lại thành một file zip cho tôi tải về", conv_pack)

    # Everything a conversation produced is already on our disk, so packaging it
    # is the platform's job, not a request to the model (measured: one turn asking
    # for ten pictures and a zip produced a zip in 1 of 4 runs).
    if conv_pack:
        cstatus, cbody = http("GET", "{}/conversations/{}".format(api, conv_pack), token=token)
        held = sum(len(m.get("media") or []) for m in (cbody or {}).get("messages") or []) \
            + len((cbody or {}).get("orphan_media") or [])
        zstatus, zblob = http_bytes("{}/conversations/{}/media.zip".format(api, conv_pack), token)
        names = []
        if zstatus == 200 and isinstance(zblob, bytes) and zblob[:2] == b"PK":
            try:
                names = zipfile.ZipFile(io.BytesIO(zblob)).namelist()
            except zipfile.BadZipFile:
                names = []
        other, _ = http_bytes("{}/conversations/{}/media.zip".format(api, conv_pack), btoken) \
            if btoken else (0, b"")
        if held >= 2 and len(names) == held and other == 404:
            c["a conversation's media downloads as one zip"].passed(
                "{} media, {} entries {}, other user {}".format(held, len(names), names[:3], other))
        else:
            c["a conversation's media downloads as one zip"].failed(
                "conversation holds {} media, zip {} with {} entries {}, other user {}".format(
                    held, zstatus, len(names), names[:3], other))
    else:
        c["a conversation's media downloads as one zip"].failed("no conversation to package")

    # ---- reliability: quota conservation, leases, cancel, health ----

    def quota_now():
        return (http("GET", api + "/auth/me", token=token)[1] or {}).get("quota_remaining")

    def job_state(job_id):
        return http("GET", "{}/jobs/{}".format(api, job_id), token=token)[1] or {}

    def wait_state(job_id, wanted, timeout):
        deadline = time.time() + timeout
        last = {}
        while time.time() < deadline:
            last = job_state(job_id)
            if last.get("status") in wanted:
                return last
            time.sleep(0.4)
        return last

    def start_job(message):
        status, body = http("POST", api + "/chat",
                            {"provider": "chatgpt", "message": message}, token=token)
        return body.get("job_id") if status == 202 and body else None

    worker_headers = {"X-Worker-Token": worker_token}

    # A result carrying the wrong attempt number must be refused outright, not
    # merged, or a reclaimed job could be finished twice.
    q0 = quota_now()
    job_id = start_job(SLOW_PHRASE + ": ping")
    seen = wait_state(job_id, ("running",), 10) if job_id else {}
    forged_status, _ = http("POST", "{}/internal/jobs/{}/result".format(api, job_id),
                            {"status": "done", "text": "forged by a stale attempt",
                             "media": [], "attempt": 99},
                            headers=worker_headers) if job_id else (0, None)
    final = wait_state(job_id, ("done", "failed"), job_timeout) if job_id else {}
    text = (final.get("result") or {}).get("text") or ""
    if (seen.get("status") == "running" and forged_status == 409
            and final.get("status") == "done" and "forged" not in text
            and quota_now() == q0 - 1):
        c["a job settles exactly once"].passed(
            "stale attempt refused with 409, real result kept, charged once")
    else:
        c["a job settles exactly once"].failed(
            "seen running {} forged post {} final {} text {!r} quota {} -> {}".format(
                seen.get("status"), forged_status, final.get("status"), text[:30], q0, quota_now()))

    # The two checks below inject faults: a provider that breaks on command and
    # a worker killed mid-job. Only the mock breaks on command, and killing the
    # browser worker mid-turn burns a real turn to prove a provider-agnostic
    # lease. In real mode they are skipped, and say so.
    q0 = quota_now()
    if real:
        c["a provider error fails the job and refunds"].skip(
            "needs a provider that fails on command; covered in mock mode")
        final = {}
    else:
        job_id = start_job(BROKEN_PHRASE + " for this one message")
        final = wait_state(job_id, ("done", "failed"), job_timeout) if job_id else {}
        if (final.get("status") == "failed" and final.get("error_kind") == "provider_error"
                and quota_now() == q0):
            c["a provider error fails the job and refunds"].passed(
                "failed as provider_error, credit returned")
        else:
            c["a provider error fails the job and refunds"].failed(
                "status {} kind {} quota {} -> {} error {!r}".format(
                    final.get("status"), final.get("error_kind"), q0, quota_now(),
                    (final.get("error") or "")[:60]))

    q0 = quota_now()
    job_id = None if real else start_job(SLOW_PHRASE + ": survive a dead worker")
    seen = wait_state(job_id, ("running",), 10) if job_id else {}
    if real:
        c["a stranded job is reclaimed"].skip(
            "kills the worker mid-turn; the lease is provider-agnostic and covered in mock mode")
    elif seen.get("status") != "running":
        c["a stranded job is reclaimed"].failed(
            "job never observed running (status {}); is the slow phrase honoured?".format(
                seen.get("status")))
    else:
        restarted = restart_worker()
        final = wait_state(job_id, ("done", "failed"), 60)
        if (restarted and final.get("status") == "done"
                and (final.get("attempts") or 0) >= 2 and quota_now() == q0 - 1):
            c["a stranded job is reclaimed"].passed(
                "finished on attempt {} after the first worker was killed".format(final.get("attempts")))
        else:
            c["a stranded job is reclaimed"].failed(
                "worker restarted {} final {} attempts {} quota {} -> {}".format(
                    restarted, final.get("status"), final.get("attempts"), q0, quota_now()))

    q0 = quota_now()
    job_id = start_job(SLOW_PHRASE + ": cancel me")
    seen = wait_state(job_id, ("running",), 10) if job_id else {}
    cancel_status, _ = http("POST", "{}/jobs/{}/cancel".format(api, job_id), token=token) \
        if job_id else (0, None)
    final = wait_state(job_id, ("cancelled", "done", "failed"), 20) if job_id else {}
    if (cancel_status == 200 and final.get("status") == "cancelled"
            and not ((final.get("result") or {}).get("media")) and quota_now() == q0):
        c["a running job can be cancelled"].passed(
            "cancelled while {}, credit returned".format(seen.get("status")))
    else:
        c["a running job can be cancelled"].failed(
            "cancel {} final {} quota {} -> {}".format(
                cancel_status, final.get("status"), q0, quota_now()))

    # The leak measured on 2026-09-23 needed one thing: the shared account's
    # memory switched on. The worker must look before it speaks. Only the mock
    # can pretend the switch is on; against the real account the setting is read
    # for real, and the check after this one asserts what was read.
    def memory_in_health():
        hstatus, health = http("GET", worker_health)
        return hstatus, ((health or {}).get("providers") or {}).get("chatgpt", {}).get("memory")

    q0 = quota_now()
    if real:
        c["memory on refuses the turn and refunds"].skip(
            "needs a provider that can pretend memory is on; covered in mock mode")
    else:
        job_id = start_job(MEMORY_PHRASE + " for this one message")
        final = wait_state(job_id, ("done", "failed"), job_timeout) if job_id else {}
        _, memory = memory_in_health()
        if (final.get("status") == "failed" and final.get("error_kind") == "provider_misconfigured"
                and quota_now() == q0 and memory == "on"):
            c["memory on refuses the turn and refunds"].passed(
                "failed as provider_misconfigured, credit returned, health shows memory on")
        else:
            c["memory on refuses the turn and refunds"].failed(
                "status {} kind {} quota {} -> {} health memory {!r}".format(
                    final.get("status"), final.get("error_kind"), q0, quota_now(), memory))
        # A served turn afterwards, so the reading below is of a provider that
        # looked again, not of the pretend switch.
        job_id = start_job("a plain turn after the memory check")
        wait_state(job_id, ("done", "failed"), job_timeout) if job_id else {}

    hstatus, memory = memory_in_health()
    if memory == "off":
        c["health reports the provider's memory setting"].passed("memory {}".format(memory))
    else:
        c["health reports the provider's memory setting"].failed(
            "health memory {!r}, status {}".format(memory, hstatus))

    hstatus, health = http("GET", worker_health)
    health = health or {}
    provider_state = (health.get("providers") or {}).get("chatgpt") or {}
    if (hstatus == 200 and health.get("code_sha")
            and "cooldown_until" in provider_state and isinstance(health.get("pacing"), dict)):
        c["health shows code version and pacing"].passed(
            "sha {} pacing {}".format(str(health.get("code_sha"))[:8], sorted(health["pacing"])))
    else:
        c["health shows code version and pacing"].failed(
            "status {} keys {} provider keys {}".format(
                hstatus, sorted(health)[:8], sorted(provider_state)))

    # The banner's shape was captured from the real site into a fixture, so the
    # detector is checked in both modes without a real failure to provoke.
    signature = subprocess.run(
        [python, str(ROOT / "tests" / "test_dom_signatures.py")],
        capture_output=True, text=True, cwd=str(ROOT))
    lines = [l for l in ((signature.stdout or "") + (signature.stderr or "")).splitlines() if l.strip()]
    summary = next((l for l in reversed(lines) if "PASSED" in l), "")
    if signature.returncode == 0 and summary.startswith("2/2"):
        c["the provider's error banner is recognised by shape"].passed(summary)
    else:
        c["the provider's error banner is recognised by shape"].failed(
            "exit {} {}".format(signature.returncode, (summary or (lines[-1] if lines else ""))[:110]))

    return checks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", action="store_true",
                        help="drive real providers through cloakbrowser instead of mocks")
    parser.add_argument("--keep", action="store_true",
                        help="keep the temp workspace and print its path")
    args = parser.parse_args()

    python = venv_python()
    ensure_deps(python)

    workspace = Path(tempfile.mkdtemp(prefix="ai-platform-acceptance-"))
    db_dir = workspace / "db"
    media_dir = workspace / "media"
    sessions_dir = ROOT / "storage" / "sessions"
    for d in (db_dir, media_dir):
        d.mkdir(parents=True, exist_ok=True)

    api_port = free_port()
    worker_port = free_port()
    api_base = "http://127.0.0.1:{}".format(api_port)
    invite_code = "acceptance-invite"
    worker_token = "acceptance-worker-token"

    api_proc = api_log = worker_proc = worker_log = None
    checks = []
    boot_error = None

    try:
        api_proc, api_log = start_service(
            python, ROOT / "api", api_port,
            {
                "DB_PATH": str(db_dir / "app.db"),
                "MEDIA_PATH": str(media_dir),
                "JWT_SECRET": "acceptance-jwt-secret",
                "INVITE_CODE": invite_code,
                "WORKER_TOKEN": worker_token,
                # Short lease so a killed worker's job is reclaimed within the run.
                "JOB_LEASE_SECONDS": "2",
                "JOB_MAX_ATTEMPTS": "3",
            },
            workspace / "api.log",
        )
        ok, detail = wait_healthy(api_base + "/health", 25)
        if not ok:
            boot_error = "api never became healthy ({})\n{}".format(detail, tail(workspace / "api.log"))
            raise RuntimeError(boot_error)

        worker_env = {
            "API_URL": api_base,
            "WORKER_TOKEN": worker_token,
            "PROVIDER_MODE": "real" if args.real else "mock",
            "MEDIA_PATH": str(media_dir),
            "SESSIONS_PATH": str(sessions_dir),
            # Mock: the forced provider error opens a cooldown; keep it short so
            # the checks after it are not held behind a pause. Real: the gate
            # must not fire turns faster than a person would. Running thirteen
            # real turns back to back earned a 429 that bounced thread pages to
            # the root and failed every second turn; pace it like the worker.
            "COOLDOWN_BASE_SECONDS": "10" if args.real else "1",
            "MIN_GAP_SECONDS": "6" if args.real else "0",
        }
        worker_health = "http://127.0.0.1:{}/health".format(worker_port)
        worker_proc, worker_log = start_service(
            python, ROOT / "worker", worker_port, worker_env, workspace / "worker.log")
        ok, detail = wait_healthy(worker_health, 40)
        if not ok:
            boot_error = "worker never became healthy ({})\n{}".format(detail, tail(workspace / "worker.log"))
            raise RuntimeError(boot_error)

        def restart_worker():
            """Kill the worker mid-job so its lease can expire, then bring a fresh one up."""
            nonlocal worker_proc, worker_log
            if worker_proc.poll() is None:
                worker_proc.kill()
                worker_proc.wait(timeout=10)
            worker_log.close()
            worker_proc, worker_log = start_service(
                python, ROOT / "worker", worker_port, worker_env, workspace / "worker-2.log")
            return wait_healthy(worker_health, 40)[0]

        checks = run_checks(api_base, media_dir, args.real, invite_code,
                            worker_token, worker_health, restart_worker, python)

    except RuntimeError:
        pass
    except KeyboardInterrupt:
        boot_error = "interrupted"
    finally:
        stop(worker_proc, worker_log)
        stop(api_proc, api_log)

    if not checks:
        checks = []
        for n in CHECKS:
            ch = Check(n)
            ch.failed("stack did not start")
            checks.append(ch)

    width = max(len(c.name) for c in checks)
    print()
    print("mode: {}".format("real providers" if args.real else "mock providers"))
    print()
    for c in checks:
        tag = "SKIP" if c.skipped else ("PASS" if c.ok else "FAIL")
        print("[{}] {}  {}".format(tag, c.name.ljust(width), c.detail))
    passed = sum(1 for c in checks if c.ok)
    skipped = sum(1 for c in checks if c.skipped)
    counted = len(checks) - skipped
    print("=" * (width + 12))
    if skipped:
        print("{}/{} PASSED, {} skipped in this mode".format(passed, counted, skipped))
    else:
        print("{}/{} PASSED".format(passed, counted))
    if boot_error:
        print()
        print("boot error:")
        print(boot_error)

    if args.keep:
        print("\nworkspace kept at {}".format(workspace))
    else:
        shutil.rmtree(workspace, ignore_errors=True)

    return 0 if passed == counted else 1


if __name__ == "__main__":
    sys.exit(main())
