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
    "a conversation can be renamed and found by search",
    "non image deliverable is kept",
    "non image deliverable is kept when asked in vietnamese",
    "a follow-up turn packages what the first one made",
    "a conversation's media downloads as one zip",
    "deleting a conversation removes its media files and the provider thread",
    "deleting a conversation cancels its running job and refunds",
    "a tombstone is handed out once per attempt",
    "a job settles exactly once",
    "a provider error fails the job and refunds",
    "a stranded job is reclaimed",
    "a running job can be cancelled",
    "quota refills once a day up to the cap",
    "admin sees usage per user, others do not",
    "each provider gets its own runner",
    "one provider's cooldown does not hold the other",
    "a job nobody serves is failed and refunded",
    "the api says which providers a worker serves",
    "a turn nobody serves is refused at once and uncharged",
    "a conversation keeps to one provider",
    "a job queued behind a long turn is not failed as unserved",
    "memory on refuses the turn and refunds",
    "health reports the provider's memory setting",
    "health shows code version and pacing",
    "the provider's error banner is recognised by shape",
    "grok settles on words or a picture, never on an empty turn",
)

# Checks a real provider cannot be asked to do, by name, with the reason the
# gate prints. Grok's account is on the free tier and allows seven turns a day,
# so the provider-agnostic reliability checks are left to mock mode rather than
# spending the day's budget proving the queue twice.
REAL_SKIPS = {
    "grok": {
        "video script job returns text":
            "grok's first driver serves chat and image only",
        "non image deliverable is kept":
            "asks the provider to build a file; unmeasured on grok",
        "non image deliverable is kept when asked in vietnamese":
            "asks the provider to build a file; unmeasured on grok",
        "a follow-up turn packages what the first one made":
            "asks the provider to build a file; unmeasured on grok",
        "a conversation's media downloads as one zip":
            "needs two media in one conversation, two of the day's seven turns",
        "deleting a conversation cancels its running job and refunds":
            "provider-agnostic, covered in mock mode; costs a turn",
        "a job settles exactly once":
            "provider-agnostic, covered in mock mode; costs a turn",
        "a running job can be cancelled":
            "provider-agnostic, covered in mock mode; costs a turn",
        "quota refills once a day up to the cap":
            "provider-agnostic, covered in mock mode; costs a turn",
        "the provider's error banner is recognised by shape":
            "the fixtures are chatgpt's own markup",
    },
    # Gemini's account has room (its usage page read 0% on 2026-09-27), so unlike grok it runs
    # the provider-agnostic checks too; only what was never measured on it is skipped.
    "gemini": {
        "non image deliverable is kept":
            "asks the provider to build a file; unmeasured on gemini",
        "non image deliverable is kept when asked in vietnamese":
            "asks the provider to build a file; unmeasured on gemini",
        "a follow-up turn packages what the first one made":
            "asks the provider to build a file; unmeasured on gemini",
        "a conversation's media downloads as one zip":
            "its second media is the packaging turn's file, skipped on gemini",
        "the provider's error banner is recognised by shape":
            "the fixtures are chatgpt's own markup; gemini's failure is read from StreamGenerate",
    },
}

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
        if self.skipped:
            return
        self.ok = True
        self.detail = detail

    def failed(self, detail):
        if self.skipped:
            return
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


def run_checks(api, media_dir, real, invite_code, worker_token, worker_health, worker_ctl,
               python, restart_api, provider="chatgpt"):
    # Must exceed the provider's own ceiling (REPLY_TIMEOUT is 300s) plus the
    # first-use browser launch, otherwise the gate reports a timeout that only
    # the gate caused.
    job_timeout = 420 if real else 30
    checks = [Check(n) for n in CHECKS]
    c = dict(zip([x.name for x in checks], checks))
    restart_worker = worker_ctl["restart"]
    # The provider this run is not speaking to, used wherever a check needs a
    # second one: a cooldown that must not spread, a worker that serves someone
    # else, a conversation that must refuse a stranger's turn.
    other_provider = "grok" if provider != "grok" else "chatgpt"

    def wanted(*names):
        """False when this mode already skipped the check, so its turns are never spent."""
        return not any(c[n].skipped for n in names)
    # A provider that cannot be asked for something says so once, here, and the
    # check below it sees an already-skipped entry and leaves it alone.
    if real:
        for name, reason in (REAL_SKIPS.get(provider) or {}).items():
            if name in c:
                c[name].skip(reason)
    stamp = str(int(time.time() * 1000))
    # A plain domain: email-validator rejects reserved suffixes such as .local.
    user_a = "acc-a-{}@aiplatform-acceptance.com".format(stamp)
    user_b = "acc-b-{}@aiplatform-acceptance.com".format(stamp)
    password = "acceptance-pw-123"
    token = None
    media_id = None

    # The banner's shape was captured from the real site into fixtures, so the
    # detector is checked in both modes without a real failure to provoke. It
    # runs first, before any job has made the real worker open its browser, so
    # its own short-lived browser never overlaps the worker's session.
    try:
        signature = subprocess.run(
            [python, str(ROOT / "tests" / "test_dom_signatures.py")],
            capture_output=True, text=True, cwd=str(ROOT), timeout=180)
        code, output = signature.returncode, (signature.stdout or "") + (signature.stderr or "")
    except subprocess.TimeoutExpired:
        code, output = -1, "timed out after 180s"
    lines = [l for l in output.splitlines() if l.strip()]
    summary = next((l for l in reversed(lines) if "PASSED" in l), "")
    counts = re.match(r"(\d+)/(\d+) PASSED", summary)
    if code == 0 and counts and counts.group(1) == counts.group(2) and int(counts.group(2)) >= 7:
        c["the provider's error banner is recognised by shape"].passed(summary)
    else:
        c["the provider's error banner is recognised by shape"].failed(
            "exit {} {}".format(code, (summary or (lines[-1] if lines else ""))[:110]))

    settle = subprocess.run([python, str(ROOT / "tests" / "test_grok_settle.py")],
                            capture_output=True, text=True, cwd=str(ROOT))
    lines = [l for l in ((settle.stdout or "") + (settle.stderr or "")).splitlines() if l.strip()]
    summary = next((l for l in reversed(lines) if "PASSED" in l), "")
    if settle.returncode == 0 and summary.startswith("8/8"):
        c["grok settles on words or a picture, never on an empty turn"].passed(summary)
    else:
        c["grok settles on words or a picture, never on an empty turn"].failed(
            "exit {} {}".format(settle.returncode, (summary or (lines[-1] if lines else ""))[:110]))

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
                        {"provider": provider, "message": "Reply with the single word: pong"},
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
                        {"provider": provider, "prompt": "a plain red circle on white"},
                        token=token)
    image_conv = (body or {}).get("conversation_id") if status == 202 else None
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

    if media_id and wanted("video script job returns text"):
        status, body = http("POST", api + "/video/script",
                            {"provider": provider, "media_id": media_id, "duration": 5},
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
    elif wanted("video script job returns text"):
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
                            {"provider": provider, "message": message,
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

    # A conversation the team can find again: renamed, then searched by its new
    # title and by a word inside one of its messages, and invisible to anyone else.
    def search(query, tok):
        s, body = http("GET", "{}/conversations?q={}".format(api, query), token=tok)
        return [x["id"] for x in ((body or {}).get("items") or [])] if s == 200 else None

    new_title = "renamed-{}".format(stamp[-6:])
    inside = "Remember" if real else "opening"
    if conv:
        rstatus, rbody = http("PATCH", "{}/conversations/{}".format(api, conv),
                              {"title": new_title}, token=token)
        by_title, by_word, theirs = search(new_title, token), search(inside, token), search(inside, btoken)
        foreign, _ = http("PATCH", "{}/conversations/{}".format(api, conv),
                          {"title": "hijacked"}, token=btoken)
        if (rstatus == 200 and (rbody or {}).get("title") == new_title
                and conv in (by_title or []) and conv in (by_word or [])
                and theirs == [] and foreign == 404):
            c["a conversation can be renamed and found by search"].passed(
                "renamed, found by title and by {!r}, other user sees 0 and gets 404".format(inside))
        else:
            c["a conversation can be renamed and found by search"].failed(
                "rename {} title {!r}, by title {}, by word {}, other user sees {}, foreign rename {}".format(
                    rstatus, (rbody or {}).get("title") if isinstance(rbody, dict) else rbody,
                    by_title, by_word, theirs, foreign))
    else:
        c["a conversation can be renamed and found by search"].failed("no conversation to rename")

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

    if wanted("non image deliverable is kept"):
        check_zip("non image deliverable is kept",
                  "build me a zip file holding a.txt and b.txt")
    # The same request in the language the user actually types in. The button
    # ChatGPT offers is labelled in that language, and matching on the English
    # word let a real request through unnoticed.
    if wanted("non image deliverable is kept when asked in vietnamese"):
        check_zip("non image deliverable is kept when asked in vietnamese",
                  "Tạo cho tôi một file zip chứa hai file text tên a.txt và b.txt")

    # The journey a real user took, which passed every check above while being
    # broken: make something, then in the same conversation ask for it packaged.
    # Its download button was labelled neither in English nor with a file name.
    conv_pack = None
    if wanted("a follow-up turn packages what the first one made"):
        drawn, draw_err, conv_pack = chat_once("vẽ cho tôi một hình vuông màu xanh")
    if not conv_pack and wanted("a follow-up turn packages what the first one made"):
        c["a follow-up turn packages what the first one made"].failed(
            draw_err or "the first turn produced no conversation")
    elif conv_pack:
        check_zip("a follow-up turn packages what the first one made",
                  "gói tấm hình vừa rồi lại thành một file zip cho tôi tải về", conv_pack)

    # Everything a conversation produced is already on our disk, so packaging it
    # is the platform's job, not a request to the model (measured: one turn asking
    # for ten pictures and a zip produced a zip in 1 of 4 runs).
    def zip_names(url):
        status, blob = http_bytes(url, token)
        if status == 200 and isinstance(blob, bytes) and blob[:2] == b"PK":
            try:
                return status, zipfile.ZipFile(io.BytesIO(blob)).namelist()
            except zipfile.BadZipFile:
                return status, []
        return status, []

    if conv_pack and wanted("a conversation's media downloads as one zip"):
        cstatus, cbody = http("GET", "{}/conversations/{}".format(api, conv_pack), token=token)
        messages = (cbody or {}).get("messages") or []
        held = sum(len(m.get("media") or []) for m in messages) \
            + len((cbody or {}).get("orphan_media") or [])
        zip_url = "{}/conversations/{}/media.zip".format(api, conv_pack)
        zstatus, names = zip_names(zip_url)
        other, _ = http_bytes(zip_url, btoken) if btoken else (0, b"")
        # One message's worth: the turn that produced the file, and nothing else.
        with_file = [m for m in messages
                     if any(x.get("type") == "file" for x in m.get("media") or [])]
        mstatus, mnames = zip_names("{}?message_id={}".format(zip_url, with_file[-1]["id"])) \
            if with_file else (0, [])
        unknown, _ = http_bytes("{}?message_id={}".format(zip_url, "0" * 32), token)
        if (held >= 2 and len(names) == held and other == 404 and with_file
                and len(mnames) == len(with_file[-1]["media"]) and unknown == 404):
            c["a conversation's media downloads as one zip"].passed(
                "{} media, {} entries {}, one message {} entr{}, unknown message 404, other user 404".format(
                    held, len(names), names[:3], len(mnames), "y" if len(mnames) == 1 else "ies"))
        else:
            c["a conversation's media downloads as one zip"].failed(
                "conversation holds {} media, zip {} with {} entries {}, other user {}, "
                "one message {} with {} entries, unknown message {}".format(
                    held, zstatus, len(names), names[:3], other, mstatus, len(mnames), unknown))
    elif wanted("a conversation's media downloads as one zip"):
        c["a conversation's media downloads as one zip"].failed("no conversation to package")

    def quota_now():
        return (http("GET", api + "/auth/me", token=token)[1] or {}).get("quota_remaining")

    def threads_deleted():
        _, health = http("GET", worker_health)
        return (health or {}).get("threads_deleted") or 0

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

    def start_job(message, as_provider=None):
        status, body = http("POST", api + "/chat",
                            {"provider": as_provider or provider, "message": message}, token=token)
        return body.get("job_id") if status == 202 and body else None

    # Deleting a conversation takes its media with it, on disk and in the api,
    # and hands the provider thread to the worker to remove from the shared
    # account's Library. It never touches the credit balance.
    # Whichever conversation holds media: the packaging one, or the image job's
    # own conversation when this provider was not asked to build files.
    to_delete = conv_pack or image_conv
    if to_delete:
        conv_pack = to_delete
        cstatus, cbody = http("GET", "{}/conversations/{}".format(api, conv_pack), token=token)
        items = [x for m in (cbody or {}).get("messages") or [] for x in (m.get("media") or [])] \
            + list((cbody or {}).get("orphan_media") or [])
        media_ids = [x["id"] for x in items]
        filenames = [x["filename"] for x in items]
        deleted_before = threads_deleted()
        q_before = quota_now()
        # Someone else's DELETE must bounce and change nothing before the owner's own.
        foreign_delete, _ = http("DELETE", "{}/conversations/{}".format(api, conv_pack), token=btoken) \
            if btoken else (0, None)
        still_mine = (http("GET", "{}/conversations/{}".format(api, conv_pack), token=token)[0] == 200
                      and all(http("GET", "{}/media/{}".format(api, m), token=token)[0] == 200
                              for m in media_ids))
        dstatus, _ = http("DELETE", "{}/conversations/{}".format(api, conv_pack), token=token)
        conv_gone = http("GET", "{}/conversations/{}".format(api, conv_pack), token=token)[0] == 404
        media_gone = all(http("GET", "{}/media/{}".format(api, m), token=token)[0] == 404 for m in media_ids)
        files_gone = not any((Path(media_dir) / f).exists() for f in filenames)
        # The worker removes the thread when it is next idle, after its pacing
        # gap and its tombstone interval: measured at 16s on a quiet host.
        deadline = time.time() + 60
        deleted_after = deleted_before
        while time.time() < deadline and deleted_after < deleted_before + 1:
            time.sleep(1)
            deleted_after = threads_deleted()
        if (foreign_delete == 404 and still_mine and dstatus == 204 and conv_gone and media_gone
                and files_gone and media_ids and quota_now() == q_before
                and deleted_after >= deleted_before + 1):
            c["deleting a conversation removes its media files and the provider thread"].passed(
                "other user 404 and nothing moved; owner 204; {} media rows and files gone; "
                "provider threads deleted {} -> {}; quota unchanged".format(
                    len(media_ids), deleted_before, deleted_after))
        else:
            c["deleting a conversation removes its media files and the provider thread"].failed(
                "other user {} still mine {}, delete {}, conversation gone {}, {} media gone {}, "
                "files gone {}, quota {} -> {}, threads deleted {} -> {}".format(
                    foreign_delete, still_mine, dstatus, conv_gone, len(media_ids), media_gone,
                    files_gone, q_before, quota_now(), deleted_before, deleted_after))
    else:
        c["deleting a conversation removes its media files and the provider thread"].failed(
            "no conversation to delete")

    # Deleting a conversation whose job is still running ends the job and gives
    # the credit back; the worker's late result is refused, so nothing of the
    # deleted conversation is written afterwards: no row, and no file either.
    # A picture is asked for so that there would be something to write.
    # The thread that turn had already opened on the provider's site is removed
    # too, once the worker reports where it landed.
    q0 = quota_now()
    files_before = set(os.listdir(media_dir))
    deleted_before = threads_deleted()
    status, body = http("POST", api + "/chat",
                        {"provider": provider,
                         "message": SLOW_PHRASE + ": draw a picture, then delete me while running"},
                        token=token) \
        if wanted("deleting a conversation cancels its running job and refunds") else (0, {})
    doomed_job = (body or {}).get("job_id") if status == 202 else None
    doomed_conv = (body or {}).get("conversation_id") if status == 202 else None
    seen = wait_state(doomed_job, ("running", "done", "failed"), 20) if doomed_job else {}
    dstatus, _ = http("DELETE", "{}/conversations/{}".format(api, doomed_conv), token=token) \
        if doomed_conv else (0, None)
    final = wait_state(doomed_job, ("cancelled", "done", "failed"), job_timeout) if doomed_job else {}
    # The mock's slow picture finishes anyway and is refused; wait for that
    # refusal so the file it had saved has been removed before looking. The
    # real provider stops mid-turn and posts nothing to refuse.
    refused_before = (http("GET", worker_health)[1] or {}).get("results_refused") or 0
    deadline = time.time() + 20
    while time.time() < deadline:
        if ((http("GET", worker_health)[1] or {}).get("results_refused") or 0) > refused_before:
            break
        time.sleep(1)
    time.sleep(1.5)
    files_after = set(os.listdir(media_dir))
    deadline = time.time() + 45
    deleted_after = deleted_before
    while time.time() < deadline and deleted_after < deleted_before + 1:
        time.sleep(1)
        deleted_after = threads_deleted()
    if (seen.get("status") == "running" and dstatus == 204 and final.get("status") == "cancelled"
            and not ((final.get("result") or {}).get("media")) and quota_now() == q0
            and files_after == files_before and deleted_after >= deleted_before + 1):
        c["deleting a conversation cancels its running job and refunds"].passed(
            "job cancelled by the delete, credit returned, no media row or file written, "
            "the turn's own thread deleted {} -> {}".format(deleted_before, deleted_after))
    else:
        c["deleting a conversation cancels its running job and refunds"].failed(
            "seen {} delete {} final {} media {} quota {} -> {} new files {} threads deleted {} -> {}".format(
                seen.get("status"), dstatus, final.get("status"),
                (final.get("result") or {}).get("media"), q0, quota_now(),
                sorted(files_after - files_before)[:3], deleted_before, deleted_after))

    # The tombstone queue's promises, checked on a throwaway database rather than
    # through a racing worker: once per attempt, settled stays settled, a failed
    # attempt waits, three misses end it.
    try:
        stones = subprocess.run([python, str(ROOT / "tests" / "test_tombstones.py")],
                                capture_output=True, text=True, cwd=str(ROOT), timeout=120)
        code, output = stones.returncode, (stones.stdout or "") + (stones.stderr or "")
    except subprocess.TimeoutExpired:
        code, output = -1, "timed out after 120s"
    lines = [l for l in output.splitlines() if l.strip()]
    summary = next((l for l in reversed(lines) if "PASSED" in l), "")
    if code == 0 and summary.startswith("5/5"):
        c["a tombstone is handed out once per attempt"].passed(summary)
    else:
        c["a tombstone is handed out once per attempt"].failed(
            "exit {} {}".format(code, (summary or (lines[-1] if lines else ""))[:110]))

    # ---- reliability: quota conservation, leases, cancel, health ----

    worker_headers = {"X-Worker-Token": worker_token}

    # A result carrying the wrong attempt number must be refused outright, not
    # merged, or a reclaimed job could be finished twice.
    q0 = quota_now()
    job_id = start_job(SLOW_PHRASE + ": ping") if wanted("a job settles exactly once") else None
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
    job_id = start_job(SLOW_PHRASE + ": cancel me") if wanted("a running job can be cancelled") else None
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

    # A day passes (the api is restarted with its clock moved forward): the
    # balance comes back to the cap once, does not stack on a second look, and a
    # job afterwards spends from the refilled cap.
    # The cap is the user's own quota_daily, read back rather than assumed, so a
    # DEFAULT_QUOTA in the caller's shell cannot fail this for the wrong reason.
    # A run that crosses 00:00 UTC refills once on its own; that would show here.
    if not wanted("quota refills once a day up to the cap"):
        me, cap = {}, None
    else:
        me = http("GET", api + "/auth/me", token=token)[1] or {}
        cap = me.get("quota_daily")
    q_spent = quota_now()
    restarted = restart_api({"CLOCK_OFFSET_SECONDS": "86400"}) if cap else False
    q_first, q_second = quota_now(), quota_now()
    job_id = start_job("a plain turn after the day changed") if cap else None
    wait_state(job_id, ("done", "failed"), job_timeout) if job_id else {}
    q_after_job, q_again = quota_now(), quota_now()
    if (restarted and cap and q_spent is not None and q_spent < cap and q_first == cap
            and q_second == cap and q_after_job == cap - 1 and q_again == cap - 1):
        c["quota refills once a day up to the cap"].passed(
            "{} -> {} after the day changed, held at {}, {} after one job".format(
                q_spent, cap, cap, cap - 1))
    else:
        c["quota refills once a day up to the cap"].failed(
            "api restarted {}, cap {}, quota {} -> {} then {}, after a job {} then {}".format(
                restarted, cap, q_spent, q_first, q_second, q_after_job, q_again))

    # The first account owns the instance and sees who spent what; usage is read
    # from the jobs that already record every charge and refund.
    ustatus, usage = http("GET", api + "/admin/usage", token=token)
    rows = {r.get("email"): r for r in ((usage or {}).get("items") or [])} if ustatus == 200 else {}
    mine, theirs_row = rows.get(user_a) or {}, rows.get(user_b)
    consistent = bool(mine) and mine.get("jobs_total") == sum(
        mine.get(k) or 0 for k in ("done", "failed", "cancelled", "open"))
    forbidden, _ = http("GET", api + "/admin/usage", token=btoken)
    # images counts pictures still kept, so a run that deletes the conversation
    # holding them reports zero: the number is printed, never gated on.
    if (ustatus == 200 and consistent and (mine.get("jobs_total") or 0) >= 5
            and theirs_row is not None and forbidden == 403):
        c["admin sees usage per user, others do not"].passed(
            "{} jobs ({} done, {} failed, {} cancelled), {} images still kept, other user 403".format(
                mine.get("jobs_total"), mine.get("done"), mine.get("failed"), mine.get("cancelled"),
                mine.get("images")))
    else:
        c["admin sees usage per user, others do not"].failed(
            "status {} admin row {} other row present {} other user {}".format(
                ustatus, {k: mine.get(k) for k in ("jobs_total", "done", "failed", "cancelled", "open", "images")},
                theirs_row is not None, forbidden))

    # ---- serving more than one provider ----

    # One runner per provider, each with its own browser: two stealth browsers
    # cannot be launched from one thread, so a second provider on the single
    # runner would break on its first job.
    if real:
        c["each provider gets its own runner"].skip(
            "real mode runs one provider at a time; two browsers are exercised in mock mode")
        c["one provider's cooldown does not hold the other"].skip(
            "needs two providers configured; real mode runs one at a time")
    else:
        _, health = http("GET", worker_health)
        health = health or {}
        runners = health.get("runners") or {}
        configured = sorted(health.get("providers") or {})
        owners = sorted({(r or {}).get("thread") for r in runners.values() if isinstance(r, dict)})
        if (len(configured) >= 2 and sorted(runners) == configured
                and all((r or {}).get("alive") for r in runners.values())
                and len(owners) == len(runners)):
            c["each provider gets its own runner"].passed(
                "{} providers, {} runners on distinct threads {}".format(
                    len(configured), len(runners), owners))
        else:
            c["each provider gets its own runner"].failed(
                "providers {} runners {}".format(
                    configured, {k: (v or {}).get("thread") for k, v in runners.items()} or "none"))

        # A provider on cooldown must hold only itself. hold_seconds() used to
        # return the longest wait of any provider, which parks every runner.
        held = restart_worker({"COOLDOWN_BASE_SECONDS": "45"})
        broken = start_job(BROKEN_PHRASE + " so this provider goes on cooldown")
        wait_state(broken, ("failed",), job_timeout) if broken else {}
        free_job = start_job("a turn for the provider that is not on cooldown",
                             as_provider=other_provider)
        moved = wait_state(free_job, ("running", "done"), 20) if free_job else {}
        if held and moved.get("status") in ("running", "done"):
            c["one provider's cooldown does not hold the other"].passed(
                "{} on a 45s cooldown, {} still {} within 20s".format(
                    provider, other_provider, moved.get("status")))
        else:
            c["one provider's cooldown does not hold the other"].failed(
                "worker restarted {}, {} job was {} after 20s".format(
                    held, other_provider, moved.get("status")))
        restart_worker()

    # A job nobody serves must not wait forever. With the worker off, every job
    # used to sit pending while the user watched a typing bubble.
    q0 = quota_now()
    if real:
        # One real account at a time: the worker simply goes away.
        moved = worker_ctl["stop"]()
        how = "with the worker off"
    else:
        # Harder, and what a second provider makes possible: a worker that is
        # alive and asking for work, but not for this provider's work. A claim
        # that ignored the provider filter would run the job anyway.
        moved = worker_ctl["restart"]({"PROVIDERS": other_provider})
        how = "while the worker served only {}".format(other_provider)
    orphan = start_job("nobody is serving this one")
    final = wait_state(orphan, ("failed", "done", "cancelled"), 90) if orphan else {}
    # Read now: the refund lands with the failure, and the turns below must not blur it.
    q_orphan = quota_now()
    # A conversation of the provider the worker still serves, for the 409 probe below (mock only:
    # in real mode no other provider is ever served).
    other_conv = None
    if not real:
        ostatus, obody = http("POST", api + "/chat",
                              {"provider": other_provider, "message": "a conversation of the served one"},
                              token=token)
        other_conv = (obody or {}).get("conversation_id") if ostatus == 202 else None
    # The orphan failing proves nobody has asked for this provider for the whole window. The api
    # must say so, and refuse the next turn at once instead of charging it and making it wait.
    lstatus, listing = http("GET", api + "/providers", token=token)
    served = {p.get("name"): p.get("served") for p in ((listing or {}).get("providers") or [])
              if isinstance(p, dict)}
    q_before_refusal = quota_now()
    asked_at = time.time()
    rstatus, _ = http("POST", api + "/chat",
                      {"provider": provider, "message": "nobody is serving this one either"}, token=token)
    refused_in = time.time() - asked_at
    q_after_refusal = quota_now()
    # Every kind of turn is refused the same way, and never ahead of a check that already refuses
    # (the review of aff8012): a missing conversation, another provider's conversation, a missing
    # picture. None of them may cost a credit, and the list itself is not for anonymous callers.
    # The video probe needs a picture still there: where no file is asked for (grok), the delete
    # check above removed the run's only one, and a missing picture rightly answers 404 first.
    live_picture = media_id and http("GET", "{}/media/{}".format(api, media_id), token=token)[0] == 200
    kinds = {
        "image": http("POST", api + "/image/generate",
                      {"provider": provider, "prompt": "a picture nobody will draw"}, token=token)[0],
        "video": (http("POST", api + "/video/script", {"provider": provider, "media_id": media_id},
                       token=token)[0] if live_picture else None),
        "missing conversation": http("POST", api + "/chat",
                                     {"provider": provider, "message": "into nothing",
                                      "conversation_id": "no-such-conversation"}, token=token)[0],
        "missing picture": http("POST", api + "/video/script",
                                {"provider": provider, "media_id": "no-such-media"}, token=token)[0],
    }
    if other_conv:
        kinds["another provider's conversation"] = http(
            "POST", api + "/chat", {"provider": provider, "message": "into the other one",
                                    "conversation_id": other_conv}, token=token)[0]
    q_after_kinds = quota_now()
    anonymous_list = http("GET", api + "/providers")[0]
    worker_ctl["restart"]()
    if (moved and final.get("status") == "failed"
            and final.get("error_kind") == "no_worker" and q_orphan == q0):
        c["a job nobody serves is failed and refunded"].passed(
            "failed as no_worker {}, credit returned".format(how))
    else:
        c["a job nobody serves is failed and refunded"].failed(
            "worker moved {} status {} kind {} quota {} -> {}".format(
                moved, final.get("status"), final.get("error_kind"), q0, q_orphan))
    if (lstatus == 200 and served.get(provider) is False
            and (real or served.get(other_provider) is True) and anonymous_list == 401):
        c["the api says which providers a worker serves"].passed(
            "{} not served {}{}; anonymous 401".format(
                provider, how, "" if real else ", {} served".format(other_provider)))
    else:
        c["the api says which providers a worker serves"].failed(
            "status {} served {} anonymous {}".format(lstatus, served, anonymous_list))
    in_order = (kinds["missing conversation"] == 404 and kinds["missing picture"] == 404
                and (real or kinds.get("another provider's conversation") == 409))
    if (rstatus == 503 and q_after_refusal == q_before_refusal and refused_in < 5
            and kinds["image"] == 503 and kinds["video"] in (503, None) and in_order
            and q_after_kinds == q_after_refusal):
        c["a turn nobody serves is refused at once and uncharged"].passed(
            "chat 503 in {:.1f}s, image {}, video {}; 404/409 still first {}; quota {} -> {}".format(
                refused_in, kinds["image"], kinds["video"],
                {k: v for k, v in kinds.items() if k not in ("image", "video")},
                q_before_refusal, q_after_kinds))
    else:
        c["a turn nobody serves is refused at once and uncharged"].failed(
            "chat {} in {:.1f}s, then {}, quota {} -> {} -> {}".format(
                rstatus, refused_in, kinds, q_before_refusal, q_after_refusal, q_after_kinds))

    # A conversation holds one provider's thread. Sending another provider's turn
    # into it would hand that provider a url from a site it is not logged into,
    # and the delete would post the tombstone to the wrong runner. Refused before
    # anything is created, so it costs neither a credit nor a provider turn.
    if conv:
        q0 = quota_now()
        refusals = [
            http("POST", api + "/chat",
                 {"provider": other_provider, "message": "a turn from the wrong provider",
                  "conversation_id": conv}, token=token)[0],
            http("POST", api + "/image/generate",
                 {"provider": other_provider, "prompt": "a circle", "conversation_id": conv},
                 token=token)[0],
        ]
        if media_id:
            refusals.append(http("POST", api + "/video/script",
                                 {"provider": other_provider, "media_id": media_id,
                                  "conversation_id": conv}, token=token)[0])
        same, _ = http("GET", "{}/conversations/{}".format(api, conv), token=token)
        if all(status == 409 for status in refusals) and quota_now() == q0 and same == 200:
            c["a conversation keeps to one provider"].passed(
                "{} refused on {} entry point(s) with 409, credit untouched".format(
                    other_provider, len(refusals)))
        else:
            c["a conversation keeps to one provider"].failed(
                "statuses {} quota {} -> {} conversation readable {}".format(
                    refusals, q0, quota_now(), same))
    else:
        c["a conversation keeps to one provider"].failed("no conversation to guard")

    # A worker in the middle of a long turn stops asking for work; its heartbeat
    # is the only proof it is alive. Without that proof the job queued behind it
    # is failed as unserved while the worker is perfectly healthy.
    if real:
        c["a job queued behind a long turn is not failed as unserved"].skip(
            "needs a turn longer than the unserved window; the mock can be told to take one")
    else:
        slow_worker = restart_worker({"MOCK_DELAY_SECONDS": "45"})
        first = start_job("a long turn that keeps the worker busy")
        running = wait_state(first, ("running",), 20) if first else {}
        queued = start_job("the turn waiting behind it")
        done_first = wait_state(first, ("done", "failed"), 120) if first else {}
        done_queued = wait_state(queued, ("done", "failed"), 180) if queued else {}
        restart_worker()
        if (slow_worker and running.get("status") == "running"
                and done_first.get("status") == "done" and done_queued.get("status") == "done"):
            c["a job queued behind a long turn is not failed as unserved"].passed(
                "a 45s turn ran while the job behind it waited and then finished")
        else:
            c["a job queued behind a long turn is not failed as unserved"].failed(
                "worker restarted {} first {} then {} queued {} kind {}".format(
                    slow_worker, running.get("status"), done_first.get("status"),
                    done_queued.get("status"), done_queued.get("error_kind")))

    # The leak measured on 2026-09-23 needed one thing: the shared account's
    # memory switched on. The worker must look before it speaks. Only the mock
    # can pretend the switch is on; against the real account the setting is read
    # for real, and the check after this one asserts what was read.
    def memory_in_health():
        hstatus, health = http("GET", worker_health)
        return hstatus, ((health or {}).get("providers") or {}).get(provider, {}).get("memory")

    q0 = quota_now()
    if real:
        c["memory on refuses the turn and refunds"].skip(
            "needs a provider that can pretend memory is on; covered in mock mode")
        # The no-worker check above left a worker that has never sent a turn, and
        # a worker that has not looked reports no reading at all.
        if wanted("health reports the provider's memory setting"):
            job_id = start_job("a plain turn after the worker came back")
            wait_state(job_id, ("done", "failed"), job_timeout) if job_id else {}
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
    provider_state = (health.get("providers") or {}).get(provider) or {}
    if (hstatus == 200 and health.get("code_sha")
            and "cooldown_until" in provider_state and isinstance(health.get("pacing"), dict)):
        c["health shows code version and pacing"].passed(
            "sha {} pacing {}".format(str(health.get("code_sha"))[:8], sorted(health["pacing"])))
    else:
        c["health shows code version and pacing"].failed(
            "status {} keys {} provider keys {}".format(
                hstatus, sorted(health)[:8], sorted(provider_state)))

    return checks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", action="store_true",
                        help="drive real providers through cloakbrowser instead of mocks")
    parser.add_argument("--provider", default="chatgpt", choices=("chatgpt", "grok", "gemini"),
                        help="which provider the job checks speak to (default chatgpt)")
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

    api_env = {
        "DB_PATH": str(db_dir / "app.db"),
        "MEDIA_PATH": str(media_dir),
        "JWT_SECRET": "acceptance-jwt-secret",
        "INVITE_CODE": invite_code,
        "WORKER_TOKEN": worker_token,
        # Short lease so a killed worker's job is reclaimed within the run.
        "JOB_LEASE_SECONDS": "2",
        "JOB_MAX_ATTEMPTS": "3",
        # A job nobody claims is failed and refunded this soon, so the check for
        # it does not have to wait out a production timeout.
        # Comfortably above the gate's own pacing gap, so a worker pausing
        # between turns is never mistaken for a dead one.
        "NO_WORKER_SECONDS": "20",
    }

    try:
        api_proc, api_log = start_service(python, ROOT / "api", api_port, api_env, workspace / "api.log")
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
            # Real mode drives one account, and one browser, at a time. Mock mode
            # serves two so the two-provider machinery is exercised every run.
            "PROVIDERS": args.provider if args.real else "chatgpt,grok,gemini",
            # Measured 2026-09-24: the free grok account answers a short burst
            # and then asks for about nine minutes, so a real grok run paces
            # itself far wider than a chatgpt one.
            "MIN_GAP_SECONDS__GROK": "150" if args.real else "0",
            "COOLDOWN_BASE_SECONDS__GROK": "600" if args.real else "1",
        }
        worker_health = "http://127.0.0.1:{}/health".format(worker_port)
        worker_proc, worker_log = start_service(
            python, ROOT / "worker", worker_port, worker_env, workspace / "worker.log")
        ok, detail = wait_healthy(worker_health, 40)
        if not ok:
            boot_error = "worker never became healthy ({})\n{}".format(detail, tail(workspace / "worker.log"))
            raise RuntimeError(boot_error)

        worker_logs = {"n": 1}

        def start_worker(extra_env=None):
            nonlocal worker_proc, worker_log
            worker_logs["n"] += 1
            env = dict(worker_env)
            env.update(extra_env or {})
            worker_proc, worker_log = start_service(
                python, ROOT / "worker", worker_port, env,
                workspace / "worker-{}.log".format(worker_logs["n"]))
            return wait_healthy(worker_health, 40)[0]

        def stop_worker():
            """Kill the worker outright; a job claimed by it loses its keeper."""
            nonlocal worker_proc
            if worker_proc.poll() is None:
                worker_proc.kill()
                worker_proc.wait(timeout=10)
            worker_log.close()
            deadline = time.time() + 15
            while time.time() < deadline:
                if http("GET", worker_health, timeout=2)[0] != 200:
                    return True
                time.sleep(0.5)
            return False

        def restart_worker(extra_env=None):
            """Kill the worker mid-job so its lease can expire, then bring a fresh one up."""
            stop_worker()
            return start_worker(extra_env)

        worker_ctl = {"restart": restart_worker, "stop": stop_worker, "start": start_worker}

        def restart_api(extra_env):
            """Bring the api back with extra settings, on the same database and port."""
            nonlocal api_proc, api_log
            stop(api_proc, api_log)
            env = dict(api_env)
            env.update(extra_env)
            api_proc, api_log = start_service(python, ROOT / "api", api_port, env, workspace / "api-2.log")
            return wait_healthy(api_base + "/health", 25)[0]

        checks = run_checks(api_base, media_dir, args.real, invite_code,
                            worker_token, worker_health, worker_ctl, python, restart_api,
                            args.provider)

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
    print("mode: {} providers, speaking to {}".format(
        "real" if args.real else "mock", args.provider))
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
