#!/usr/bin/env python3
"""Acceptance gate for the AI platform.

One command, own ports, own temp database and media directory, PASS/FAIL table,
non-zero exit on failure, cleans up after itself.

    python acceptance.py                         mock providers, about 5 minutes, safe to rerun
    python acceptance.py --real                  drives the real ChatGPT browser session
    python acceptance.py --real --provider grok  the same, against grok (or gemini)
    python acceptance.py --keep                  keeps the temp workspace and prints its path

--provider (chatgpt by default) picks which provider the job checks speak to.
Mock mode serves all three either way. --real drives only that one, runs far
longer than mock (real replies, paced turns) and spends the account's quota;
it skips, each with its reason printed, the checks a real run cannot or should
not make.

Only the provider boundary is faked in mock mode. The API, the database, the job
queue, the worker poll loop and media storage all run for real either way.

Standard library only, so it runs under any python3; the services themselves are
launched with the cloakbrowser venv.
"""

import argparse
import ast
import datetime
import hashlib
import io
import json
import os
import re
import shutil
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent

CHECKS = (
    "api health",
    "register (invite code)",
    "eight registrations at once on an empty database make exactly one admin",
    "the same email registered eight times at once answers one 201 and 409 to the rest, never 500",
    "login returns jwt",
    "auth rejects bad token",
    "chat job completes",
    "image job produces file",
    "video script job returns text",
    "a feature its provider does not offer is refused at once and uncharged",
    "the api says what each provider offers, as its driver does",
    "media listing scoped to user",
    "thread reused within a conversation",
    "threads never cross conversations",
    "a conversation can be renamed and found by search",
    "non image deliverable is kept",
    "non image deliverable is kept when asked in vietnamese",
    "a video the provider makes is kept and served as a video",
    "a follow-up turn packages what the first one made",
    "a conversation's media downloads as one zip",
    "deleting a conversation removes its media files and the provider thread",
    "a turn taken away before it was sent leaves no thread, by the worker's own word",
    "a silent driver leaves its turn unaccounted for, whatever an older record says",
    "a driver that says unsent of a turn that made a thread is believed only once it is removed",
    "deleting a conversation cancels its running job and refunds",
    "the gate's rule for a turn taken away holds on its table",
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
    "an account its admin must fix holds its provider out at once",
    "jobs waiting for a held provider fail and refund at once",
    "a hold ends by itself",
    "health reports the provider's memory setting",
    "health shows code version and pacing",
    "the provider's error banner is recognised by shape",
    "grok settles on words or a picture, never on an empty turn",
    "a script is held to what its video model takes",
    "a real account's picture budget outlives the worker",
    "several accounts of a provider share the work, and a thread stays on its account",
    "a job's failures take the right path through the pool and the runner",
    "a browser that dies under a turn is dropped and cools the provider down",
    "a busy runner keeps saying it is alive",
    "an api key is shown once, listed without its secret, stored as a hash, and revoked",
    "an api key works only on /v1/images, and a login token not there",
    "a person keeps at most ten live api keys",
    "a /v1 request with a prompt ends with a picture to download",
    "a /v1 request with a prompt and a picture hands the worker exactly that picture",
    "a /v1 request without a prompt, with a file not png jpeg or webp, or over 10 MB is refused "
    "uncharged, nothing kept",
    "a /v1 request refused for quota keeps no picture",
    "a /v1 request names its provider, chatgpt when it names none, and an unknown one is refused uncharged",
    "a reference picture sent to a provider that takes none is refused uncharged, nothing kept",
    "with a key, /v1/providers says which providers are served and what each takes",
    "with a key, /v1/account says the credits left today, after the day's refill",
    "a /v1 request and its pictures reach only their owner",
    "a failed /v1 request gives its credit back once",
    "a /v1 request can be cancelled while queued or running, its credit back once, and only by its owner",
    "a /v1 request can continue an earlier one in its thread, and is refused uncharged otherwise",
    "a /v1 chatgpt request carries up to four reference pictures in order, and more is refused uncharged",
    "a /v1 key's requests share one conversation and thread a day, apart from other keys and providers",
    "a named session keeps its own conversation and thread across days, apart from other names, keys and providers",
    "a session with no name or with continue_from is refused uncharged, and a continued request stays in its session",
    "a key lists its own sessions only, and a session whose conversation was deleted starts a new one",
    "a picture request answered in words alone fails with those words and gives its credit back",
    "a /v1 script is checked against its video model, on Grok unless told, and one that does not fit gives its credit back",
    "a /v1 script for an unknown target or provider is refused uncharged, and its answers name no account",
    "the example script sends a prompt and a picture, waits, and saves the picture made",
    "the api tells a worker which threads are the platform's, and only for that provider",
    "a done result with nothing in it fails and refunds",
    "a running job whose worker died is failed and refunded by its owner's next poll",
)

# The /v1 checks that run jobs; the real requests through /v1 with a key prove them on the site.
V1_JOB_CHECKS = (
    "a /v1 request with a prompt ends with a picture to download",
    "a /v1 request with a prompt and a picture hands the worker exactly that picture",
    "a /v1 request and its pictures reach only their owner",
    "a failed /v1 request gives its credit back once",
    "a /v1 request can be cancelled while queued or running, its credit back once, and only by its owner",
    "a /v1 request can continue an earlier one in its thread, and is refused uncharged otherwise",
    "a /v1 chatgpt request carries up to four reference pictures in order, and more is refused uncharged",
    "a /v1 key's requests share one conversation and thread a day, apart from other keys and providers",
    "a named session keeps its own conversation and thread across days, apart from other names, keys and providers",
    "a session with no name or with continue_from is refused uncharged, and a continued request stays in its session",
    "a key lists its own sessions only, and a session whose conversation was deleted starts a new one",
    "a picture request answered in words alone fails with those words and gives its credit back",
    "a /v1 script is checked against its video model, on Grok unless told, and one that does not fit gives its credit back",
    "a /v1 script for an unknown target or provider is refused uncharged, and its answers name no account",
    "the example script sends a prompt and a picture, waits, and saves the picture made",
    "a /v1 request names its provider, chatgpt when it names none, and an unknown one is refused uncharged",
)
V1_REAL_SKIP = "spends real chatgpt turns; proven by the plan's real requests through /v1 with a key"

# Checks a real provider cannot be asked to do, by name, with the reason the
# gate prints. Grok's account is on the free tier and allows seven turns a day,
# so the provider-agnostic reliability checks are left to mock mode rather than
# spending the day's budget proving the queue twice.
REAL_SKIPS = {
    "chatgpt": {
        "a video the provider makes is kept and served as a video":
            "chatgpt makes no video in a chat turn",
    },
    "grok": {
        "video script job returns text":
            "grok's first driver serves chat and image only",
        "a video the provider makes is kept and served as a video":
            "grok's driver collects no video",
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
        "a video the provider makes is kept and served as a video":
            "spends one of the shared account's few videos a day; proven by a real turn through the web",
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
EMPTY_PHRASE = "answer with nothing"
MEMORY_PHRASE = "pretend memory is on"
UNSENT_PHRASE = "wait before you speak"
SILENT_PHRASE = "and say nothing of it"
LYING_PHRASE = "and call it unsent"

THREAD_MARKER = re.compile(r"\[thread=([^\]]+)\]")


def thread_accounted(removed, stop, moment, owed, made):
    """What became, at the provider, of a turn taken away from a running job at `moment`.

    While anything is still owed for the turn (its result not handed back, a tombstone made since
    and not settled, the api's record unreadable), nothing accounts for it: None. After that,
    "removed": the worker removed a thread tombstoned since. Or "unsent": no thread was tombstoned
    since (`made` is False) and the driver's own stop record, made at or after that moment (its
    time is rounded to a tenth), says the turn never went out, so there is no thread to remove.
    A record that says the turn was sent accounts for nothing, and neither does any record of a
    turn that made a thread: only that thread's removal does.
    """
    if owed:
        return None
    if removed:
        return "removed"
    if not made and stop and stop.get("at", 0) >= moment - 0.05 and stop.get("sent") is False:
        return "unsent"
    return None


# The rule above, row by row: a thread removed, the driver's stop record, the moment the turn was
# taken away (on the clock the gate shares with its worker), something still owed, a thread
# tombstoned since, the answer. A record's time is rounded to a tenth: one made at or after a
# moment reads at most 0.05 below it.
ACCOUNTED = (
    (True, None, 1000.0, False, True, "removed"),
    (True, {"sent": False, "pressed": False, "at": 1005.0}, 1000.0, False, True, "removed"),
    (True, None, 1000.0, True, True, None),
    (False, None, 1000.0, False, False, None),
    (False, {}, 1000.0, False, False, None),
    (False, {"sent": False, "pressed": False, "at": 1005.0}, 1000.0, False, False, "unsent"),
    (False, {"sent": False, "pressed": False, "at": 1005.0}, 1000.0, False, True, None),
    (False, {"sent": False, "pressed": False, "at": 1000.0}, 1000.0, False, False, "unsent"),
    (False, {"sent": False, "pressed": False, "at": 1000.0}, 1000.049, False, False, "unsent"),
    (False, {"sent": False, "pressed": False, "at": 1000.0}, 1000.051, False, False, None),
    (False, {"sent": False, "pressed": False, "at": 999.9}, 1000.0, False, False, None),
    (False, {"sent": False, "pressed": False, "at": 990.0}, 1000.0, False, False, None),
    (False, {"sent": False, "pressed": False, "at": 1005.0}, 2000.0, False, False, None),
    (False, {"sent": False, "pressed": False, "at": 499.0}, 250.0, False, False, "unsent"),
    (False, {"sent": False, "pressed": False}, 1000.0, False, False, None),
    (False, {"sent": True, "pressed": True, "at": 1005.0}, 1000.0, False, False, None),
    (False, {"sent": True, "pressed": False, "at": 1005.0}, 1000.0, False, False, None),
    (False, {"sent": None, "pressed": False, "at": 1005.0}, 1000.0, False, False, None),
    (False, {"sent": 0, "pressed": False, "at": 1005.0}, 1000.0, False, False, None),
    (False, {"pressed": False, "at": 1005.0}, 1000.0, False, False, None),
    (False, {"sent": False, "pressed": False, "at": 1005.0}, 1000.0, True, False, None),
)
ACCOUNTED_ROWS = 21


def still_owed(handed_back, stones, known):
    """Whether anything is still owed for a turn taken away from a running job.

    Its result not handed back yet (the api refuses it, and only then knows the turn's thread); the
    api's record of tombstones unreadable (`stones` is None: no word is not a clean word); or a
    tombstone made since (its id not in `known`) and not settled. `stones` holds (id, settled).
    """
    return (not handed_back or stones is None
            or any(stone not in known and not settled for stone, settled in stones))


# The same, row by row: the result handed back, the record of tombstones, the ones known before
# the turn, the answer.
OWED = (
    (False, [], set(), True),
    (False, [(7, "2026-10-02 02:00:00")], set(), True),
    (True, None, set(), True),
    (True, [], set(), False),
    (True, [(7, "2026-10-02 02:00:00")], set(), False),
    (True, [(7, None)], set(), True),
    (True, [(7, None)], {7}, False),
    (True, [(7, "2026-10-02 02:00:00"), (8, None)], {7}, True),
    (True, [(7, None), (8, "2026-10-02 02:00:00")], {7}, False),
    (True, [(8, None), (9, "2026-10-02 02:00:00")], {7}, True),
)
OWED_ROWS = 10


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


def driver_features():
    """What each real driver offers, read from its `supported_features` without importing it."""
    offered = {}
    for name in ("chatgpt", "grok", "gemini"):
        tree = ast.parse((ROOT / "worker" / "src" / "providers" / "{}.py".format(name)).read_text())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "supported_features"
                                                     for t in node.targets)):
                offered[name] = [element.attr.lower() for element in node.value.elts]
    return offered


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


def http_form(url, fields, files=None, token=None, timeout=60):
    """POST multipart/form-data: fields {name: text}, files {name: (filename, content type, bytes)} or a
    list of (name, (filename, content type, bytes)) when one name repeats."""
    boundary = "acceptance-" + os.urandom(12).hex()
    parts = []
    for name, value in fields.items():
        parts.append('--{}\r\nContent-Disposition: form-data; name="{}"\r\n\r\n'.format(
            boundary, name).encode() + value.encode() + b"\r\n")
    for name, (filename, ctype, blob) in (files.items() if isinstance(files, dict) else files or []):
        parts.append('--{}\r\nContent-Disposition: form-data; name="{}"; filename="{}"\r\n'
                     'Content-Type: {}\r\n\r\n'.format(boundary, name, filename, ctype).encode()
                     + blob + b"\r\n")
    req = urllib.request.Request(url, data=b"".join(parts) + "--{}--\r\n".format(boundary).encode(),
                                 method="POST")
    req.add_header("Content-Type", "multipart/form-data; boundary=" + boundary)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, (json.loads(raw) if raw.strip() else None)
        except ValueError:
            return exc.code, raw
    except Exception as exc:
        return 0, "{}: {}".format(type(exc).__name__, exc)


def tiny_png(rgb):
    """A real 8x8 PNG of one colour, standard library only."""
    raw = b"".join(b"\x00" + bytes(rgb) * 8 for _ in range(8))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def jpeg_head(width, height):
    """A JPEG's opening as the api reads it: SOI, JFIF, and a baseline frame of this size."""
    return (b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            + b"\xff\xc0\x00\x11\x08" + struct.pack(">HH", height, width) + b"\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01")


def jpeg_hiding(width, height):
    """The re-review's JPEG (2026-10-09): FF 00 and two bytes a decoder skips as stray, then an APP1 the
    decoder skips whole but which holds an 8x8 frame, then the real frame of this size."""
    tail = b"\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    fake = b"\xff\xc0\x00\x11\x08" + struct.pack(">HH", 8, 8) + tail
    return (b"\xff\xd8\xff\x00" + struct.pack(">H", 6) + b"\xff\xe1" + struct.pack(">H", 2 + len(fake)) + fake
            + b"\xff\xc0\x00\x11\x08" + struct.pack(">HH", height, width) + tail + b"\x11" * 64 + b"\xff\xd9")


def webp_lossless(width, height):
    """A WEBP whose VP8L header gives this size."""
    bits = (width - 1) | ((height - 1) << 14)
    chunk = b"\x2f" + struct.pack("<I", bits) + b"\x00" * 5
    return b"RIFF" + struct.pack("<I", 4 + 8 + len(chunk)) + b"WEBP" + b"VP8L" + struct.pack("<I", len(chunk)) + chunk


def png_head(width, height):
    """A PNG's signature and IHDR claiming this size, nothing after."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr
            + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr) & 0xFFFFFFFF))


# What the api reads of a picture is its signature and its size in pixels; these carry both.
TINY_JPEG = jpeg_head(8, 8) + b"\x11" * 64 + b"\xff\xd9"
TINY_WEBP = webp_lossless(8, 8)


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


def register_at_once(api, bodies):
    """POST each body to /auth/register from its own thread, all released together."""
    start = threading.Barrier(len(bodies))
    answers = [None] * len(bodies)

    def send(i):
        try:
            start.wait(timeout=30)
        except threading.BrokenBarrierError:
            answers[i] = (0, "never released with the others")
            return
        answers[i] = http("POST", api + "/auth/register", bodies[i])
    threads = [threading.Thread(target=send, args=(i,)) for i in range(len(bodies))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return answers


# Registrations sent at once. With the hash made first, a check, a count and an insert taken outside
# one transaction sit well under a millisecond apart, and the race needs the hashes to end together.
# Measured on a 12-core machine (2026-10-27) with register() stripped of its transaction: two
# registrations made two admins in 4 runs of 5, eight in 30 of 30; two copies of one email answered
# 500 in 14 runs of 15, eight copies in 14 of 15. A machine with fewer cores catches it less often.
RACERS = 8


def register_race_checks(c, fresh_api, invite_code, password, stamp):
    # The gate's own api already has its first account, so the race for it runs on an api of its
    # own over an empty database.
    one_admin = "eight registrations at once on an empty database make exactly one admin"
    twin = "the same email registered eight times at once answers one 201 and 409 to the rest, never 500"
    api, why, stop_api = fresh_api("api-empty")
    try:
        if not api:
            c[one_admin].failed("the api on an empty database never became healthy\n" + why)
            c[twin].failed("the api on an empty database never became healthy")
            return
        answers = register_at_once(api, [
            {"email": "race-{}-{}@aiplatform-acceptance.com".format(n, stamp), "password": password,
             "name": "Race", "invite_code": invite_code} for n in range(RACERS)])
        roles = sorted(str(body.get("role") if isinstance(body, dict) else body)
                       for _, body in answers)
        if ([status for status, _ in answers] == [201] * RACERS
                and roles == ["admin"] + ["user"] * (RACERS - 1)):
            c[one_admin].passed("all {} 201, one admin".format(RACERS))
        else:
            c[one_admin].failed("answers {}".format(
                [(status, body.get("role") if isinstance(body, dict) else body) for status, body in answers]))

        # Eight copies of one email missed the race in 1 run of 15 (RACERS above); three emails make
        # a miss on all three unlikely.
        for n in range(3):
            email = "twin-{}-{}@aiplatform-acceptance.com".format(n, stamp)
            answers = register_at_once(api, [
                {"email": email, "password": password, "name": "Twin", "invite_code": invite_code}] * RACERS)
            if sorted(status for status, _ in answers) != [201] + [409] * (RACERS - 1):
                c[twin].failed("email {}: answers {}".format(n, [
                    (status, body if status != 201 else "created") for status, body in answers]))
                break
        else:
            c[twin].passed("three emails, each one 201 and {} 409".format(RACERS - 1))
    finally:
        stop_api()


def v1_checks(api, c, token, btoken, media_dir, db_path, job_timeout, real, restart_worker):
    """API keys and /v1/images. token: the first account's login (its admin); btoken: another person's."""
    def files_now():
        return set(os.listdir(media_dir))

    def quota_of(login):
        return (http("GET", api + "/auth/me", token=login)[1] or {}).get("quota_remaining")

    def new_key(login, name):
        status, body = http("POST", api + "/auth/api-keys", {"name": name}, token=login)
        return status, (body if isinstance(body, dict) else {})

    def keys_of(login):
        status, body = http("GET", api + "/auth/api-keys", token=login)
        return (body or {}).get("items") or [] if status == 200 and isinstance(body, dict) else []

    def poll_v1(request_id, key):
        deadline, body = time.time() + job_timeout, {}
        while time.time() < deadline:
            status, body = http("GET", "{}/v1/images/{}".format(api, request_id), token=key)
            if status != 200 or not isinstance(body, dict):
                return {"status": "unreadable {} {}".format(status, body)}
            if body.get("status") in ("done", "failed", "cancelled"):
                return body
            time.sleep(0.4)
        return body if isinstance(body, dict) else {}

    nowhere = api + "/v1/images/not-a-request"

    # A key's life: shown once, listed without it, stored as its SHA-256 only, used, revoked.
    status, made = new_key(token, "gate key")
    key, key_id = made.get("key") or "", made.get("id")
    listed = keys_of(token)
    mine = [i for i in listed if i.get("id") == key_id]
    try:
        with sqlite3.connect("file:{}?mode=ro".format(db_path), uri=True) as conn:
            stored = [tuple(r) for r in conn.execute("SELECT * FROM api_keys")]
    except sqlite3.Error as exc:
        stored = [("unreadable", str(exc))]
    in_plain = bool(key) and any(key in str(v) for row in stored for v in row)
    as_hash = bool(key) and any(v == hashlib.sha256(key.encode()).hexdigest() for row in stored for v in row)
    used = http("GET", nowhere, token=key)[0] if key else None
    last_used = [i.get("last_used_at") for i in keys_of(token) if i.get("id") == key_id]
    stranger = http("DELETE", "{}/auth/api-keys/{}".format(api, key_id), token=btoken)[0] if key_id else None
    revoked = http("DELETE", "{}/auth/api-keys/{}".format(api, key_id), token=token)[0] if key_id else None
    gone = key_id is not None and not [i for i in keys_of(token) if i.get("id") == key_id]
    refused = http("GET", nowhere, token=key)[0] if key else None
    again = http("DELETE", "{}/auth/api-keys/{}".format(api, key_id), token=token)[0] if key_id else None
    if (status == 201 and key.startswith("aip_") and len(key) >= 40 and len(mine) == 1
            and "key" not in mine[0] and key not in json.dumps(listed) and stored and not in_plain
            and as_hash and used == 404 and last_used and last_used[0] and stranger == 404
            and revoked == 204 and gone and refused == 401 and again == 404):
        c["an api key is shown once, listed without its secret, stored as a hash, and revoked"].passed(
            "made {}, listed once without it, stored as its sha256, used (404 on no request), another "
            "person's revoke 404, revoked 204, then 401, revoked again 404".format(status))
    else:
        c["an api key is shown once, listed without its secret, stored as a hash, and revoked"].failed(
            "made {} {}..., listed {}, in plain {}, as hash {}, used {}, last used {}, stranger {}, "
            "revoked {}, gone {}, then {}, again {}".format(
                status, key[:6], len(mine), in_plain, as_hash, used, last_used, stranger, revoked, gone,
                refused, again))

    # A key opens /v1/images and nothing else; a login token does not open /v1.
    skey = new_key(token, "scope key")[1].get("key") or ""
    elsewhere = {path: http("GET", api + path, token=skey)[0] if skey else None
                 for path in ("/auth/me", "/conversations", "/auth/api-keys", "/media", "/providers",
                              "/admin/usage")}
    elsewhere["POST /auth/api-keys"] = http("POST", api + "/auth/api-keys", {"name": "minted by a key"},
                                             token=skey)[0] if skey else None
    on_v1 = {"a key": http("GET", nowhere, token=skey)[0] if skey else None,
             "a login token": http("GET", nowhere, token=token)[0],
             "nothing": http("GET", nowhere)[0],
             "a forged key": http("GET", nowhere, token="aip_" + "A" * 43)[0],
             "a login token sending": http_form(api + "/v1/images", {"prompt": "no place for a jwt"},
                                                token=token)[0]}
    if (skey and all(v == 401 for v in elsewhere.values()) and on_v1["a key"] == 404
            and all(v == 401 for k, v in on_v1.items() if k != "a key")):
        c["an api key works only on /v1/images, and a login token not there"].passed(
            "a key: /v1 404 on no request, 401 on {} web routes; a login token, none, a forged key: 401 "
            "on /v1".format(len(elsewhere)))
    else:
        c["an api key works only on /v1/images, and a login token not there"].failed(
            "key made {}, elsewhere {}, on /v1 {}".format(bool(skey), elsewhere, on_v1))

    # At most ten live keys a person; a revoked one frees its place.
    made_b = [new_key(btoken, "b key {}".format(n)) for n in range(max(0, 10 - len(keys_of(btoken))))]
    eleventh = new_key(btoken, "one too many")[0]
    freed = http("DELETE", "{}/auth/api-keys/{}".format(api, made_b[0][1].get("id")), token=btoken)[0] \
        if made_b and made_b[0][1].get("id") else None
    refilled, bkey_made = new_key(btoken, "b key again")
    bkey = bkey_made.get("key") or ""
    if (made_b and all(s == 201 for s, _ in made_b) and eleventh == 409 and freed == 204
            and refilled == 201 and len(keys_of(btoken)) == 10):
        c["a person keeps at most ten live api keys"].passed(
            "ten made, the eleventh 409, one revoked, then one more 201")
    else:
        c["a person keeps at most ten live api keys"].failed(
            "made {}, eleventh {}, revoked {}, then {}, live {}".format(
                [s for s, _ in made_b], eleventh, freed, refilled, len(keys_of(btoken))))

    # Refused before anything is charged or kept.
    akey = new_key(token, "job key")[1].get("key") or ""
    png = tiny_png((200, 40, 90))
    files_before, quota_before = files_now(), quota_of(token)
    sent = {
        "a picture alone": ({}, ("a.png", "image/png", png), 422),
        "a blank prompt": ({"prompt": "   "}, ("a.png", "image/png", png), 422),
        "text named .png": ({"prompt": "draw it"}, ("photo.png", "image/png", b"hello, no picture here"), 415),
        "a gif": ({"prompt": "draw it"}, ("a.gif", "image/gif", b"GIF89a" + b"\x01" * 40), 415),
        "over 10 MB": ({"prompt": "draw it"},
                       ("big.png", "image/png", png_head(8, 8) + b"\x00" * (10 * 1024 * 1024)), 413),
        # The tier 1 review, 2026-10-09: a small file claiming a huge size would reach the shared
        # browser; a RIFF that is not a WEBP passed a four byte check.
        "a png of 30000x30000": ({"prompt": "draw it"}, ("huge.png", "image/png", png_head(30000, 30000)), 413),
        "a jpeg 20000 wide": ({"prompt": "draw it"},
                              ("wide.jpg", "image/jpeg", jpeg_head(20000, 100) + b"\x11" * 64 + b"\xff\xd9"), 413),
        "a webp of 60 megapixels": ({"prompt": "draw it"}, ("many.webp", "image/webp", webp_lossless(10000, 6000)), 413),
        "a wave file": ({"prompt": "draw it"},
                        ("sound.webp", "image/webp", b"RIFF" + struct.pack("<I", 36) + b"WAVEfmt " + b"\x00" * 28), 415),
        "a png with no header": ({"prompt": "draw it"}, ("cut.png", "image/png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 20), 415),
        "a jpeg hiding 9000x9000 behind FF 00": ({"prompt": "draw it"},
                                                 ("hidden.jpg", "image/jpeg", jpeg_hiding(9000, 9000)), 415),
        "a jpeg of fill bytes": ({"prompt": "draw it"}, ("fill.jpg", "image/jpeg", b"\xff\xd8" + b"\xff" * 200000), 415),
    }
    answered = {name: http_form(api + "/v1/images", fields, {"image": picture}, token=akey)[0]
                for name, (fields, picture, _) in sent.items()}
    # Refused before the key is even read, the body cut off at the limit; and refused for want of a
    # served ChatGPT (503), the picture sent with it not kept either.
    answered["12 MB with no key"] = http_form(
        api + "/v1/images", {"prompt": "draw it"},
        {"image": ("big.png", "image/png", png_head(8, 8) + b"\x00" * (12 * 1024 * 1024))})[0]
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("INSERT OR REPLACE INTO provider_holds (provider, until, reason)"
                         " VALUES ('chatgpt', datetime('now', '+5 minutes'), 'the gate')")
        answered["chatgpt held"] = http_form(api + "/v1/images", {"prompt": "draw it"},
                                             {"image": ("a.png", "image/png", png)}, token=akey)[0]
    finally:
        with sqlite3.connect(db_path) as conn:
            conn.execute("DELETE FROM provider_holds WHERE provider = 'chatgpt' AND reason = 'the gate'")
    wanted_answers = {name: want for name, (_, _, want) in sent.items()}
    wanted_answers.update({"12 MB with no key": 413, "chatgpt held": 503})
    files_after, quota_after = files_now(), quota_of(token)
    if (akey and answered == wanted_answers
            and files_after == files_before and quota_after == quota_before):
        c["a /v1 request without a prompt, with a file not png jpeg or webp, or over 10 MB is refused "
          "uncharged, nothing kept"].passed("{}; credits {} and files unchanged".format(answered, quota_after))
    else:
        c["a /v1 request without a prompt, with a file not png jpeg or webp, or over 10 MB is refused "
          "uncharged, nothing kept"].failed("{}; credits {} -> {}; files added {}".format(
              answered, quota_before, quota_after, sorted(files_after - files_before)[:3]))

    # No credit: refused, and the picture sent with it is not kept.
    me_b = http("GET", api + "/auth/me", token=btoken)[1] or {}
    b_quota = me_b.get("quota_remaining")
    emptied = http("PUT", "{}/admin/users/{}/quota".format(api, me_b.get("id")), {"quota_remaining": 0},
                   token=token)[0]
    files_before = files_now()
    broke = http_form(api + "/v1/images", {"prompt": "a picture with no credit left"},
                      {"image": ("b.png", "image/png", png)}, token=bkey)[0]
    files_after, still_none = files_now(), quota_of(btoken)
    restored = http("PUT", "{}/admin/users/{}/quota".format(api, me_b.get("id")),
                    {"quota_remaining": b_quota}, token=token)[0] if b_quota is not None else None
    if bkey and emptied == 200 and broke == 402 and files_after == files_before and still_none == 0 \
            and restored == 200:
        c["a /v1 request refused for quota keeps no picture"].passed("402 with no credit, no file kept")
    else:
        c["a /v1 request refused for quota keeps no picture"].failed(
            "key {}, emptied {}, sent {}, files added {}, credits {}, restored {}".format(
                bool(bkey), emptied, broke, sorted(files_after - files_before)[:3], still_none, restored))

    # Issue #16: Grok's driver takes no reference picture (worker/src/providers/grok.py), so the api
    # refuses one sent to grok before it keeps the file or takes a credit.
    files_before, q0 = files_now(), quota_of(token)
    graw = http_form(api + "/v1/images", {"prompt": "the same subject at night", "provider": "grok"},
                     {"image": ("ref.png", "image/png", png)}, token=akey)
    files_after, q1 = files_now(), quota_of(token)
    if graw[0] == 400 and files_after == files_before and q1 == q0:
        c["a reference picture sent to a provider that takes none is refused uncharged, nothing kept"].passed(
            "grok with a picture: 400 {!r}; credits and files unchanged".format((graw[1] or {}).get("detail")))
    else:
        c["a reference picture sent to a provider that takes none is refused uncharged, nothing kept"].failed(
            "grok with a picture: {} {}, credits {} -> {}, files added {}".format(
                graw[0], graw[1], q0, q1, sorted(files_after - files_before)[:3]))

    # Issue #16: a program asks with its key which providers are there and what each takes.
    pstatus, plist = http("GET", api + "/v1/providers", token=akey)
    said = {p.get("name"): (p.get("served"), p.get("makes_pictures"), p.get("takes_reference"))
            for p in (plist or {}).get("providers") or []} if isinstance(plist, dict) else {}
    others = {"nothing": http("GET", api + "/v1/providers")[0],
              "a login token": http("GET", api + "/v1/providers", token=token)[0]}
    takes = {name: entry[2] for name, entry in said.items()}
    if (pstatus == 200 and set(said) == {"chatgpt", "grok", "gemini"}
            and all(isinstance(entry[0], bool) and entry[1] is True for entry in said.values())
            and takes == {"chatgpt": True, "grok": False, "gemini": True}
            and all(v == 401 for v in others.values())):
        c["with a key, /v1/providers says which providers are served and what each takes"].passed(
            "{}; without a key and with a login token 401".format(said))
    else:
        c["with a key, /v1/providers says which providers are served and what each takes"].failed(
            "status {}: {}; others {}".format(pstatus, said or plist, others))

    # Issue #20: a program asks with its key how many credits are left before it sends a set. The
    # other person's balance is put back to nothing on a day long gone, so their next read is the
    # first of a new day and must show the refilled balance, not yesterday's leftover.
    account = "with a key, /v1/account says the credits left today, after the day's refill"
    me_b = http("GET", api + "/auth/me", token=btoken)[1] or {}
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("UPDATE users SET quota_remaining = 0, last_refill_day = '2000-01-01' WHERE id = ?",
                         (me_b.get("id"),))
        astatus, first_read = http("GET", api + "/v1/account", token=bkey)
        second_read = http("GET", api + "/v1/account", token=bkey)[1]
        with sqlite3.connect("file:{}?mode=ro".format(db_path), uri=True) as conn:
            day = (conn.execute("SELECT last_refill_day FROM users WHERE id = ?", (me_b.get("id"),)).fetchone()
                   or [None])[0]
    except sqlite3.Error as exc:
        astatus, first_read, second_read, day = 0, "db: {}".format(exc), None, None
    next_day = ("{}T00:00:00Z".format((datetime.date.fromisoformat(day) + datetime.timedelta(days=1)).isoformat())
                if day and day != "2000-01-01" else None)
    wanted_read = {"credits_left": me_b.get("quota_daily"), "credits_daily": me_b.get("quota_daily"),
                   "refills_at": next_day}
    others = {"nothing": http("GET", api + "/v1/account")[0],
              "a login token": http("GET", api + "/v1/account", token=btoken)[0]}
    try:
        ran = subprocess.run([sys.executable, str(ROOT / "scripts" / "image_api_example.py"), "--api", api,
                              "--account"], capture_output=True, text=True, timeout=60,
                             env=dict(os.environ, AIP_API_KEY=bkey))
        script = (ran.returncode, (ran.stdout or "") + (ran.stderr or ""))
    except Exception as exc:
        script = (-1, "{}: {}".format(type(exc).__name__, exc))
    if (astatus == 200 and me_b.get("quota_daily") and next_day and first_read == wanted_read
            and second_read == wanted_read and all(v == 401 for v in others.values())
            and script[0] == 0 and str(me_b.get("quota_daily")) in script[1] and bkey not in script[1]):
        c[account].passed("{} on the first read of a new day, the same on the next; without a key and with a "
                          "login token 401; the example's --account printed it".format(first_read))
    else:
        c[account].failed("status {}: {} then {}, wanted {}; others {}; --account {}".format(
            astatus, first_read, second_read, wanted_read, others, script))

    if real:
        return

    # A prompt alone: queued at once, then done with a picture that downloads as its bytes.
    q0 = quota_of(token)
    status, sent_one = http_form(api + "/v1/images", {"prompt": "a plain blue square"}, token=akey)
    rid = (sent_one or {}).get("id") if isinstance(sent_one, dict) else None
    final = poll_v1(rid, akey) if rid else {}
    images = final.get("images") or []
    downloads = []
    for item in images:
        dstatus, blob = http_bytes(api + (item.get("url") or "/nowhere"), akey)
        downloads.append((dstatus, len(blob), blob[:8] == b"\x89PNG\r\n\x1a\n", item.get("bytes"),
                          item.get("content_type"),
                          (item.get("url") or "").startswith("/v1/images/{}/files/".format(rid))))
    q1 = quota_of(token)
    if (status == 202 and (sent_one or {}).get("status") == "queued" and final.get("status") == "done"
            and images and all(d[0] == 200 and d[1] == d[3] and d[2] and d[4] == "image/png" and d[5]
                               for d in downloads) and q1 == q0 - 1):
        c["a /v1 request with a prompt ends with a picture to download"].passed(
            "202 queued, then done with {} picture(s), downloaded {} bytes, one credit".format(
                len(images), [d[1] for d in downloads]))
    else:
        c["a /v1 request with a prompt ends with a picture to download"].failed(
            "sent {} {}, then {} {}, downloads {}, credits {} -> {}".format(
                status, sent_one, final.get("status"), final.get("error"), downloads, q0, q1))

    # Issue #16: the request names its provider; one that names none stays on chatgpt.
    def provider_of(request_id):
        return (http("GET", "{}/jobs/{}".format(api, request_id), token=token)[1] or {}).get("provider") \
            if request_id else None

    made = {"named none": (rid, final.get("status"), len(images), provider_of(rid))}
    for name in ("grok", "gemini", "chatgpt"):
        nstatus, nsent = http_form(api + "/v1/images", {"prompt": "a plain green square", "provider": name},
                                   token=akey)
        nrid = (nsent or {}).get("id") if isinstance(nsent, dict) else None
        ndone = poll_v1(nrid, akey) if nrid else {}
        made[name] = (nrid if nstatus == 202 else nstatus, ndone.get("status"), len(ndone.get("images") or []),
                      provider_of(nrid))
    q0 = quota_of(token)
    unknown = http_form(api + "/v1/images", {"prompt": "a square", "provider": "claude"}, token=akey)
    q1 = quota_of(token)
    wanted = {"named none": "chatgpt", "grok": "grok", "gemini": "gemini", "chatgpt": "chatgpt"}
    if (all(m[1] == "done" and m[2] >= 1 and m[3] == wanted[k] for k, m in made.items())
            and unknown[0] == 400 and q1 == q0):
        c["a /v1 request names its provider, chatgpt when it names none, and an unknown one is refused "
          "uncharged"].passed("each done with a picture on its provider {}; 'claude' 400 {!r}, credits {}".format(
              {k: m[3] for k, m in made.items()}, (unknown[1] or {}).get("detail"), q1))
    else:
        c["a /v1 request names its provider, chatgpt when it names none, and an unknown one is refused "
          "uncharged"].failed("(id, status, pictures, provider) {}; unknown {} {}, credits {} -> {}".format(
              made, unknown[0], unknown[1], q0, q1))

    # A prompt and a picture of each kind: the worker gets exactly those bytes, and the web shows the
    # picture on the person's own message.
    handed, upload_id, picture_rid, result_rids = [], None, None, []
    exactly_ten = png_head(8, 8)
    exactly_ten += b"\x00" * (10 * 1024 * 1024 - len(exactly_ten))
    q_pictures = quota_of(token)
    for name, ctype, blob in (("ref.png", "image/png", tiny_png((10, 200, 60))),
                              ("ref.jpg", "image/jpeg", TINY_JPEG), ("ref.webp", "image/webp", TINY_WEBP),
                              ("exactly-10-MB.png", "image/png", exactly_ten)):
        pstatus, posted = http_form(api + "/v1/images", {"prompt": "the same subject at night"},
                                    {"image": (name, ctype, blob)}, token=akey)
        prid = (posted or {}).get("id") if isinstance(posted, dict) else None
        done = poll_v1(prid, akey) if prid else {}
        want = "reference {} bytes sha256 {}".format(len(blob), hashlib.sha256(blob).hexdigest()[:16])
        job = http("GET", "{}/jobs/{}".format(api, prid), token=token)[1] or {} if prid else {}
        conv = (http("GET", "{}/conversations/{}".format(api, job.get("conversation_id")), token=token)[1]
                or {}) if job.get("conversation_id") else {}
        # The key's conversation holds its earlier requests too (#26): this request's message is the newest.
        asked = [m for m in conv.get("messages") or [] if m.get("role") == "user"]
        shown = (asked[-1].get("media") or []) if asked else []
        kept = http_bytes("{}/media/{}/file".format(api, shown[0]["id"]), token)[1] if shown else b""
        if shown and upload_id is None:
            upload_id, picture_rid = shown[0]["id"], prid
        handed.append((name, pstatus, done.get("status"), want in (done.get("text") or ""), len(shown),
                       kept == blob, len(done.get("images") or [])))
        result_rids.append((prid, [i.get("id") for i in done.get("images") or []]))
    spent = q_pictures - quota_of(token) if q_pictures is not None else None
    if (all(h[1] == 202 and h[2] == "done" and h[3] and h[4] == 1 and h[5] and h[6] >= 1 for h in handed)
            and spent == len(handed)):
        c["a /v1 request with a prompt and a picture hands the worker exactly that picture"].passed(
            "png, jpeg, webp and exactly 10 MB: each done, one credit each, the worker got its exact "
            "bytes, shown on the person's message")
    else:
        c["a /v1 request with a prompt and a picture hands the worker exactly that picture"].failed(
            "(name, sent, then, exact bytes, on the message, kept same, pictures) {}, credits spent {}".format(
                handed, spent))

    # Only the owner reaches a request, and only its own result pictures through it.
    result_id = images[0].get("id") if images else None
    reach = {
        "another person, the request": http("GET", "{}/v1/images/{}".format(api, rid), token=bkey)[0]
        if rid else None,
        "another person, its picture": http_bytes("{}/v1/images/{}/files/{}".format(api, rid, result_id),
                                                  bkey)[0] if rid and result_id else None,
        "a picture of another request": http_bytes("{}/v1/images/{}/files/{}".format(api, rid, upload_id),
                                                   akey)[0] if rid and upload_id else None,
        "the picture sent, not made": http_bytes("{}/v1/images/{}/files/{}".format(
            api, picture_rid, upload_id), akey)[0] if picture_rid and upload_id else None,
    }
    # The tier 1 review, 2026-10-09: another request's result through this request's path, and the
    # web's own requests (a picture, a chat turn) through /v1, which serves only what /v1 made.
    other = next((ids[0] for prid, ids in result_rids if ids), None)
    if rid and other:
        reach["a result of another request"] = http_bytes("{}/v1/images/{}/files/{}".format(api, rid, other),
                                                          akey)[0]
    wstatus, web_made = http("POST", api + "/image/generate", {"provider": "chatgpt", "prompt": "a web picture"},
                             token=token)
    web_job = (web_made or {}).get("job_id") if wstatus == 202 else None
    if web_job:
        poll_job(api, web_job, token, job_timeout)
    reach["a picture made on the web"] = http("GET", "{}/v1/images/{}".format(api, web_job), token=akey)[0] \
        if web_job else "not made: {}".format(wstatus)
    cstatus, chat_made = http("POST", api + "/chat", {"provider": "chatgpt", "message": "a chat turn"}, token=token)
    chat_job = (chat_made or {}).get("job_id") if cstatus == 202 else None
    reach["a chat turn"] = http("GET", "{}/v1/images/{}".format(api, chat_job), token=akey)[0] \
        if chat_job else "not made: {}".format(cstatus)
    if chat_job:
        poll_job(api, chat_job, token, job_timeout)
    if all(v == 404 for v in reach.values()):
        c["a /v1 request and its pictures reach only their owner"].passed(
            "404 for {}".format(", ".join(reach)))
    else:
        c["a /v1 request and its pictures reach only their owner"].failed("{}".format(reach))

    # A request the provider fails gives its credit back, once.
    q0 = quota_of(token)
    fstatus, failing = http_form(api + "/v1/images", {"prompt": "a square, " + BROKEN_PHRASE}, token=akey)
    frid = (failing or {}).get("id") if isinstance(failing, dict) else None
    ended = poll_v1(frid, akey) if frid else {}
    q1 = quota_of(token)
    time.sleep(1.5)
    q2 = quota_of(token)
    if fstatus == 202 and ended.get("status") == "failed" and ended.get("error") and q1 == q0 and q2 == q0:
        c["a failed /v1 request gives its credit back once"].passed(
            "failed ({}), credits {} -> {} -> {}".format(str(ended.get("error"))[:50], q0, q1, q2))
    else:
        c["a failed /v1 request gives its credit back once"].failed(
            "sent {}, then {} {}, credits {} -> {} -> {}".format(
                fstatus, ended.get("status"), ended.get("error"), q0, q1, q2))

    # Issue #20: a request sent by mistake is cancelled through /v1. The worker is made slow so one
    # request is caught running and the next waiting behind it, with a web picture queued after
    # both, which /v1 must not reach.
    cancelling = "a /v1 request can be cancelled while queued or running, its credit back once, and only by its owner"

    def sent_id(prompt):
        sstatus, sbody = http_form(api + "/v1/images", {"prompt": prompt}, token=akey)
        return sbody.get("id") if sstatus == 202 and isinstance(sbody, dict) else None

    def v1_state(request_id):
        return (http("GET", "{}/v1/images/{}".format(api, request_id), token=akey)[1] or {}) if request_id else {}

    def cancel(request_id, key):
        return http("POST", "{}/v1/images/{}/cancel".format(api, request_id), token=key)

    slowed = restart_worker({"MOCK_DELAY_SECONDS": "8"})
    q0 = quota_of(token)
    running_id, queued_id = sent_id("a square to cancel while it runs"), sent_id("a square to cancel while it waits")
    deadline = time.time() + 20
    while time.time() < deadline and v1_state(running_id).get("status") != "running":
        time.sleep(0.2)
    wstatus, web_live = http("POST", api + "/image/generate",
                             {"provider": "chatgpt", "prompt": "a web picture /v1 may not cancel"}, token=token)
    web_id = (web_live or {}).get("job_id") if wstatus == 202 else None
    refused = {"another person": cancel(running_id, bkey)[0],
               "a login token": cancel(running_id, token)[0],
               "nothing": http("POST", "{}/v1/images/{}/cancel".format(api, running_id))[0],
               "an unknown request": cancel("not-a-request", akey)[0],
               "a web picture": cancel(web_id, akey)[0] if web_id else "not made: {}".format(wstatus)}
    before = (v1_state(running_id).get("status"), v1_state(queued_id).get("status"),
              (http("GET", "{}/jobs/{}".format(api, web_id), token=token)[1] or {}).get("status") if web_id else None)
    q_sent = quota_of(token)
    answers = {"waiting": cancel(queued_id, akey), "running": cancel(running_id, akey),
               "waiting, again": cancel(queued_id, akey), "already done": cancel(rid, akey)}
    q_back = quota_of(token)
    time.sleep(1.5)
    after = (v1_state(running_id), v1_state(queued_id))
    web_after = (http("GET", "{}/jobs/{}".format(api, web_id), token=token)[1] or {}).get("status") if web_id else None
    q_later = quota_of(token)
    try:
        ran = subprocess.run([sys.executable, str(ROOT / "scripts" / "image_api_example.py"), "--api", api,
                              "--cancel", rid or "none"], capture_output=True, text=True, timeout=60,
                             env=dict(os.environ, AIP_API_KEY=akey))
        script = (ran.returncode, (ran.stdout or "") + (ran.stderr or ""))
    except Exception as exc:
        script = (-1, "{}: {}".format(type(exc).__name__, exc))
    if web_id:
        http("POST", "{}/jobs/{}/cancel".format(api, web_id), token=token)
    restored = restart_worker()
    said = {name: (s, (b or {}).get("status") if isinstance(b, dict) else b) for name, (s, b) in answers.items()}
    no_key = ("a login token", "nothing")
    if (slowed and restored and running_id and queued_id and web_id
            and all(v == 404 for k, v in refused.items() if k not in no_key)
            and all(refused[k] == 401 for k in no_key) and before == ("running", "queued", "pending")
            and said == {"waiting": (200, "cancelled"), "running": (200, "cancelled"),
                         "waiting, again": (200, "cancelled"), "already done": (200, "done")}
            and q_sent == q0 - 3 and q_back == q0 - 1 and q_later == q0 - 1
            and all(a.get("status") == "cancelled" and not a.get("images") for a in after)
            and web_after not in ("cancelled", None) and script[0] == 0 and "done" in script[1]):
        c[cancelling].passed("cancelled waiting and running, 200 each, again unchanged, a done one left done; "
                             "credits {} -> {} -> {} and held; 404 for {}, 401 with a login token or no key; the "
                             "web picture stayed {}".format(q0, q_sent, q_back,
                                                            ", ".join(k for k in refused if k not in no_key),
                                                            web_after))
    else:
        c[cancelling].failed("worker slowed {} restored {}; refused {}; before {}; answers {}; credits {} -> {} -> "
                             "{} -> {}; after {}; web {}; --cancel {}".format(
                                 slowed, restored, refused, before, said, q0, q_sent, q_back, q_later,
                                 [(a.get("status"), len(a.get("images") or [])) for a in after], web_after, script))

    # Issue #21: a request continues an earlier done one: it goes into that request's conversation,
    # so the worker sends it into the stored thread (the mock says which thread it was handed).
    continuing = "a /v1 request can continue an earlier one in its thread, and is refused uncharged otherwise"

    def thread_in(state):
        found = re.search(r"\[thread=([^\]]+)\]", (state or {}).get("text") or "")
        return found.group(1) if found else None

    def conversation_of(request_id):
        return (http("GET", "{}/jobs/{}".format(api, request_id), token=token)[1] or {}).get("conversation_id") \
            if request_id else None

    q0 = quota_of(token)
    cstatus, csent = http_form(api + "/v1/images", {"prompt": "the same square, at night", "continue_from": rid or ""},
                               token=akey)
    cid = csent.get("id") if cstatus == 202 and isinstance(csent, dict) else None
    later_state = poll_v1(cid, akey) if cid else {}
    first_state = v1_state(rid)
    q1 = quota_of(token)
    files_before = files_now()
    refusals = {
        "another person's request": (http_form(api + "/v1/images", {"prompt": "x", "continue_from": rid or ""},
                                               token=bkey)[0], 404),
        "an unknown request, with a picture": (http_form(
            api + "/v1/images", {"prompt": "x", "continue_from": "not-a-request"},
            {"image": ("a.png", "image/png", tiny_png((1, 2, 3)))}, token=akey)[0], 404),
        "a picture made on the web": (http_form(api + "/v1/images", {"prompt": "x", "continue_from": web_job or ""},
                                                token=akey)[0], 404),
        "a request not done": (http_form(api + "/v1/images", {"prompt": "x", "continue_from": running_id or ""},
                                         token=akey)[0], 409),
        "another provider": (http_form(api + "/v1/images", {"prompt": "x", "continue_from": rid or "",
                                                            "provider": "grok"}, token=akey)[0], 409),
    }
    q2, files_after = quota_of(token), files_now()
    wrong = {k: v for k, v in refusals.items() if v[0] != v[1]}
    if (cstatus == 202 and later_state.get("status") == "done" and later_state.get("images")
            and thread_in(first_state) and thread_in(later_state) == thread_in(first_state)
            and conversation_of(cid) == conversation_of(rid) and later_state.get("continued_from") == rid
            and first_state.get("continued_from") is None and q1 == q0 - 1 and not wrong and q2 == q1
            and files_after == files_before):
        c[continuing].passed("continued in conversation {}... and thread {}, one credit; refused uncharged, "
                             "nothing kept: {}".format((conversation_of(rid) or "")[:8], thread_in(later_state),
                                                       {k: v[0] for k, v in refusals.items()}))
    else:
        c[continuing].failed("sent {} {}, then {}, threads {} -> {}, conversations {} -> {}, continued_from {}/{}, "
                             "credits {} -> {} -> {}; refusals wrong {}; files added {}".format(
                                 cstatus, csent, later_state.get("status"), thread_in(first_state),
                                 thread_in(later_state), conversation_of(rid), conversation_of(cid),
                                 first_state.get("continued_from"), later_state.get("continued_from"),
                                 q0, q1, q2, wrong, sorted(files_after - files_before)[:3]))

    # Issue #22: a chatgpt request carries up to four reference pictures; the mock says each one it
    # was handed, in order, by its size and sha256.
    several = "a /v1 chatgpt request carries up to four reference pictures in order, and more is refused uncharged"
    pics = [tiny_png((40 * n, 30, 200 - 40 * n)) for n in range(5)]

    def with_pictures(count, provider=None, blobs=None):
        fields = {"prompt": "these pictures together"}
        if provider:
            fields["provider"] = provider
        return http_form(api + "/v1/images", fields,
                         [("image", ("p{}.png".format(n), "image/png", blob))
                          for n, blob in enumerate((blobs or pics)[:count])], token=akey)

    q0 = quota_of(token)
    mstatus, msent = with_pictures(4)
    mid = msent.get("id") if mstatus == 202 and isinstance(msent, dict) else None
    mdone = poll_v1(mid, akey) if mid else {}
    handed = re.findall(r"with reference (\d+) bytes sha256 (\w+)", mdone.get("text") or "")
    wanted_refs = [(str(len(b)), hashlib.sha256(b).hexdigest()[:16]) for b in pics[:4]]
    mjob = http("GET", "{}/jobs/{}".format(api, mid), token=token)[1] or {} if mid else {}
    mconv = (http("GET", "{}/conversations/{}".format(api, mjob.get("conversation_id")), token=token)[1]
             or {}) if mjob.get("conversation_id") else {}
    # The key's conversation holds its earlier requests too (#26): this request's message is the newest.
    masked = [m for m in mconv.get("messages") or [] if m.get("role") == "user"]
    shown = [http_bytes("{}/media/{}/file".format(api, m["id"]), token)[1]
             for m in ((masked[-1].get("media") or []) if masked else [])]
    q1, files_before = quota_of(token), files_now()
    big = png_head(8, 8) + b"\x00" * (3 * 1024 * 1024)
    refused = {"five pictures": (with_pictures(5)[0], 400),
               "two pictures to gemini": (with_pictures(2, provider="gemini")[0], 400),
               "two pictures to grok": (with_pictures(2, provider="grok")[0], 400),
               "four of 3 MB, over the request's cap": (with_pictures(4, blobs=[big] * 4)[0], 413)}
    q2, files_after = quota_of(token), files_now()
    wrong = {k: v for k, v in refused.items() if v[0] != v[1]}
    if (mstatus == 202 and mdone.get("status") == "done" and handed == wanted_refs and shown == pics[:4]
            and q1 == q0 - 1 and not wrong and q2 == q1 and files_after == files_before):
        c[several].passed("four pictures handed over in order, kept on the person's message, one credit; "
                          "refused uncharged, nothing kept: {}".format({k: v[0] for k, v in refused.items()}))
    else:
        c[several].failed("sent {} {}, then {}, handed {} (wanted {}), kept on the message {} of 4 in order {}, "
                          "credits {} -> {} -> {}; refusals wrong {}; files added {}".format(
                              mstatus, msent if mstatus != 202 else "", mdone.get("status"), handed, wanted_refs,
                              len(shown), shown == pics[:4], q0, q1, q2, wrong,
                              sorted(files_after - files_before)[:3]))

    # Issue #26: every request of one key goes into that key's conversation, and so its thread, for
    # the day; another key, another day and another provider each get their own.
    per_key = "a /v1 key's requests share one conversation and thread a day, apart from other keys and providers"

    def sent_with(key, provider=None, session=None):
        fields = {"prompt": "a square for the key's thread"}
        if provider:
            fields["provider"] = provider
        if session:
            fields["session"] = session
        sstatus, sbody = http_form(api + "/v1/images", fields, token=key)
        request_id = sbody.get("id") if sstatus == 202 and isinstance(sbody, dict) else None
        state = poll_v1(request_id, key) if request_id else {}
        return request_id, conversation_of(request_id), thread_in(state), state.get("conversation_id")

    k1 = new_key(token, "thread key one")[1]
    k2 = new_key(token, "thread key two")[1]
    one_a, one_b = sent_with(k1.get("key")), sent_with(k1.get("key"))
    two = sent_with(k2.get("key"))
    on_grok = sent_with(k1.get("key"), provider="grok")
    try:
        with sqlite3.connect(db_path) as conn:
            moved = conn.execute("UPDATE api_key_conversations SET day = '2000-01-01' WHERE key_id = ?",
                                 (k1.get("id"),)).rowcount
    except sqlite3.Error as exc:
        moved = "db: {}".format(exc)
    next_day = sent_with(k1.get("key"))
    later = sent_with(k1.get("key"))
    if (one_a[1] and one_a[1] == one_b[1] and one_a[2] and one_a[2] == one_b[2] and one_a[3] == one_a[1]
            and two[1] and two[1] != one_a[1] and on_grok[1] and on_grok[1] not in (one_a[1], two[1])
            and moved and next_day[1] and next_day[1] not in (one_a[1], two[1], on_grok[1])
            and later[1] == next_day[1]):
        c[per_key].passed("one key: two requests in conversation {}… and thread {}; another key, grok and the "
                          "next day each their own, the next day's kept for the day".format(
                              one_a[1][:8], one_a[2]))
    else:
        c[per_key].failed("key one {} then {}; key two {}; grok {}; day moved {}; next day {} then {} "
                          "(request, conversation, thread, answered conversation)".format(
                              one_a, one_b, two, on_grok, moved, next_day, later))

    # Issue #28: a name of its own for a character: one conversation and thread on any day, seen by no other.
    per_session = "a named session keeps its own conversation and thread across days, apart from other names, keys and providers"
    k3 = new_key(token, "session key one")[1]
    k4 = new_key(token, "session key two")[1]
    a1 = sent_with(k3.get("key"), session="woman-a")
    b1 = sent_with(k3.get("key"), session="woman-b")
    a2 = sent_with(k3.get("key"), session="  Woman-A ")
    no_name = sent_with(k3.get("key"))
    other_key = sent_with(k4.get("key"), session="woman-a")
    grok_a = sent_with(k3.get("key"), provider="grok", session="woman-a")
    try:
        with sqlite3.connect(db_path) as conn:
            aged = conn.execute("UPDATE api_key_conversations SET day = '2000-01-01' WHERE key_id = ?",
                                (k3.get("id"),)).rowcount
    except sqlite3.Error as exc:
        aged = "db: {}".format(exc)
    a3 = sent_with(k3.get("key"), session="woman-a")
    plain_next = sent_with(k3.get("key"))
    seen = [state[1] for state in (a1, b1, no_name, other_key, grok_a)]
    told = (http("GET", api + "/v1/images/{}".format(a1[0]), token=k3.get("key"))[1] or {}) if a1[0] else {}
    plain_told = (http("GET", api + "/v1/images/{}".format(no_name[0]), token=k3.get("key"))[1] or {}) if no_name[0] else {}
    if (all(seen) and len(set(seen)) == 5 and a1[2] and a1[2] != b1[2] and a2[1] == a1[1] and a2[2] == a1[2]
            and aged and a3[1] == a1[1] and plain_next[1] not in seen
            and told.get("session") == "woman-a" and plain_told.get("session") is None):
        c[per_session].passed("woman-a in conversation {}… on any day and however spelled, thread {}; woman-b, no name, "
                              "another key and grok each their own".format(a1[1][:8], a1[2]))
    else:
        c[per_session].failed("a {} then {} then next day {}; b {}; no name {} then next day {}; other key {}; grok {}; "
                              "told {!r} and {!r}".format(a1, a2, a3, b1, no_name, plain_next, other_key, grok_a,
                                                          told.get("session"), plain_told.get("session")))

    refusals = "a session with no name or with continue_from is refused uncharged, and a continued request stays in its session"

    def credits_of(key):
        return (http("GET", api + "/v1/account", token=key)[1] or {}).get("credits_left")
    before = credits_of(k3.get("key"))
    blank = http_form(api + "/v1/images", {"prompt": "x", "session": "   "}, token=k3.get("key"))[0]
    too_long = http_form(api + "/v1/images", {"prompt": "x", "session": "n" * 65}, token=k3.get("key"))[0]
    both = http_form(api + "/v1/images", {"prompt": "x", "session": "woman-a", "continue_from": a1[0] or "x"},
                     token=k3.get("key"))[0]
    after = credits_of(k3.get("key"))
    onward_status, onward = http_form(api + "/v1/images", {"prompt": "the same, at night", "continue_from": a1[0] or "x"},
                                      token=k3.get("key"))
    onward_id = onward.get("id") if onward_status == 202 and isinstance(onward, dict) else None
    onward_state = poll_v1(onward_id, k3.get("key")) if onward_id else {}
    if (blank == 400 and too_long == 422 and both == 400 and before is not None and after == before
            and onward_state.get("session") == "woman-a" and onward_state.get("conversation_id") == a1[1]):
        c[refusals].passed("blank 400, over-long 422, both 400, credits {} unchanged; continued in session {}".format(
            after, onward_state.get("session")))
    else:
        c[refusals].failed("blank {} long {} both {} credits {} then {}; continued {} session {!r}".format(
            blank, too_long, both, before, after, onward_status, onward_state.get("session")))

    listing = "a key lists its own sessions only, and a session whose conversation was deleted starts a new one"
    mine = http("GET", api + "/v1/sessions?provider=chatgpt", token=k3.get("key"))
    names = [row.get("name") for row in (mine[1] or {}).get("sessions") or []] if mine[0] == 200 else []
    row_a = next((row for row in (mine[1] or {}).get("sessions") or [] if row.get("name") == "woman-a"), {}) if mine[0] == 200 else {}
    theirs = http("GET", api + "/v1/sessions", token=k4.get("key"))
    their_rows = (theirs[1] or {}).get("sessions") or [] if theirs[0] == 200 else []
    grok_only = http("GET", api + "/v1/sessions?provider=grok", token=k3.get("key"))
    nobody = http("GET", api + "/v1/sessions")[0]
    login_token = http("GET", api + "/v1/sessions", token=token)[0]
    gone = http("DELETE", api + "/conversations/{}".format(b1[1]), token=token)[0] if b1[1] else None
    b2 = sent_with(k3.get("key"), session="woman-b")
    if (sorted(names) == ["woman-a", "woman-b"] and row_a.get("conversation_id") == a1[1] and row_a.get("requests") == 4
            and row_a.get("pictures") == 4 and [r.get("conversation_id") for r in their_rows] == [other_key[1]]
            and [r.get("provider") for r in (grok_only[1] or {}).get("sessions") or []] == ["grok"]
            and nobody == 401 and login_token == 401 and gone in (200, 204) and b2[1] and b2[1] != b1[1]):
        c[listing].passed("{} on this key, woman-a {} requests {} pictures; the other key's alone; anonymous and login "
                          "token 401; deleted woman-b starts anew".format(names, row_a.get("requests"), row_a.get("pictures")))
    else:
        c[listing].failed("names {} row {}; other key {}; grok {}; anonymous {} login {}; delete {} then {} after {}".format(
            names, row_a, their_rows, grok_only[1], nobody, login_token, gone, b2[1], b1[1]))

    # 2026-10-31: asked for a picture, a provider can answer in words alone; that made no picture.
    words_only = "a picture request answered in words alone fails with those words and gives its credit back"
    if real:
        c[words_only].skip("needs a driver that answers in words on command; covered in mock mode")
    else:
        spent = credits_of(k3.get("key"))
        wstatus, wbody = http_form(api + "/v1/images", {"prompt": "answer in words only", "session": "words"}, token=k3.get("key"))
        wid = wbody.get("id") if wstatus == 202 and isinstance(wbody, dict) else None
        wstate = poll_v1(wid, k3.get("key")) if wid else {}
        wjob = (http("GET", api + "/jobs/{}".format(wid), token=token)[1] or {}) if wid else {}
        wconv = (http("GET", api + "/conversations/{}".format(wstate.get("conversation_id")), token=token)[1] or {}
                 ) if wstate.get("conversation_id") else {}
        stored = [m for m in wconv.get("messages") or [] if m.get("role") == "assistant"]
        if (wstate.get("status") == "failed" and "Please upload the previous picture." in (wstate.get("error") or "")
                and wjob.get("error_kind") == "no_picture" and credits_of(k3.get("key")) == spent and stored == []):
            c[words_only].passed("failed as no_picture saying {!r}, credits {} unchanged, no answer stored".format(
                wstate.get("error"), spent))
        else:
            c[words_only].failed("status {} error {!r} kind {} credits {} -> {} answers stored {}".format(
                wstate.get("status"), wstate.get("error"), wjob.get("error_kind"), spent, credits_of(k3.get("key")), len(stored)))

    # Issue #30: a video script through /v1, checked against the video model it is for.
    scripts_ok = "a /v1 script is checked against its video model, on Grok unless told, and one that does not fit gives its credit back"
    scripts_refused = "a /v1 script for an unknown target or provider is refused uncharged, and its answers name no account"
    if real:
        c[scripts_ok].skip("needs a driver that answers on command; covered in mock mode")
        c[scripts_refused].skip("covered in mock mode")
    else:
        k5 = new_key(token, "script key")[1]

        def script_for(**fields):
            sstatus, body = http("POST", api + "/v1/scripts", dict({"brief": "Lan goes home", "target": "flow"}, **fields), token=k5.get("key"))
            rid = body.get("id") if sstatus == 202 and isinstance(body, dict) else None
            deadline = time.time() + job_timeout
            state = {}
            while rid and time.time() < deadline:
                state = http("GET", api + "/v1/scripts/" + rid, token=k5.get("key"))[1] or {}
                if state.get("status") in ("done", "failed", "cancelled"):
                    break
                time.sleep(0.3)
            return sstatus, state, (http("GET", api + "/jobs/" + rid, token=token)[1] or {}) if rid else {}

        before = credits_of(k5.get("key"))
        code, flow, flow_job = script_for(scenes=2, session="Lan")
        _, wan, _ = script_for(target="wan")
        _, h3, _ = script_for(target="minimax_h3")
        mid = credits_of(k5.get("key"))
        _, broken, broken_job = script_for(brief="answer with a broken script")
        _, too_long, _ = script_for(brief="answer with a scene too long")
        after = credits_of(k5.get("key"))
        flow_scenes = (flow.get("script") or {}).get("scenes") or []
        if (code == 202 and flow.get("status") == "done" and flow.get("provider") == "grok" and flow.get("session") == "lan" and len(flow_scenes) == 2
                and flow_scenes[0]["duration_seconds"] == 8 and (wan.get("script") or {}).get("scenes", [{}])[0].get("negative_prompt")
                and h3.get("status") == "done" and before - mid == 3 and broken.get("status") == "failed" and "fit" in (broken.get("error") or "")
                and broken_job.get("error_kind") == "bad_script" and too_long.get("status") == "failed" and "999" in (too_long.get("error") or "") and after == mid):
            c[scripts_ok].passed("flow, wan and minimax_h3 done on grok; a broken one and a long one failed, credits {} then {} then {}".format(before, mid, after))
        else:
            c[scripts_ok].failed("flow {} {}; wan {}; h3 {}; broken {} {}; long {}; credits {} {} {}".format(
                code, flow, wan.get("status"), h3.get("status"), broken, broken_job.get("error_kind"), too_long, before, mid, after))

        spent = credits_of(k5.get("key"))
        unknown = http("POST", api + "/v1/scripts", {"brief": "x", "target": "nosuch"}, token=k5.get("key"))[0]
        nobody = http("POST", api + "/v1/scripts", {"brief": "x", "target": "flow", "provider": "nosuch"}, token=k5.get("key"))[0]
        anon = http("POST", api + "/v1/scripts", {"brief": "x", "target": "flow"})[0]
        targets = http("GET", api + "/v1/script-targets", token=k5.get("key"))
        shown = json.dumps(flow)
        not_a_script = http("GET", api + "/v1/scripts/{}".format(one_a[0]), token=k1.get("key"))[0]
        if (unknown == 400 and nobody == 400 and anon == 401 and credits_of(k5.get("key")) == spent and targets[0] == 200
                and [t["name"] for t in targets[1]["targets"]] == ["flow", "minimax_h3", "wan"] and "account" not in shown and not_a_script == 404):
            c[scripts_refused].passed("unknown target 400, unknown provider 400, anonymous 401, credits {} unchanged".format(spent))
        else:
            c[scripts_refused].failed("target {} provider {} anon {} credits {} then {}; targets {}; picture read as a script {}".format(
                unknown, nobody, anon, spent, credits_of(k5.get("key")), targets, not_a_script))

    # The documented example, run as a person would: the key in the environment, never on the line.
    example = "the example script sends a prompt and a picture, waits, and saves the picture made"
    out = Path(tempfile.mkdtemp(prefix="acceptance-example-"))
    reference = out / "reference.png"
    reference.write_bytes(tiny_png((90, 90, 240)))
    try:
        ran = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "image_api_example.py"), "--api", api,
             "--prompt", "the same subject on a beach", "--image", str(reference), "--out", str(out)],
            capture_output=True, text=True, timeout=job_timeout + 30, cwd=str(out),
            env=dict(os.environ, AIP_API_KEY=akey))
        code, said = ran.returncode, ((ran.stdout or "") + (ran.stderr or "")).strip()
    except Exception as exc:
        code, said = -1, "{}: {}".format(type(exc).__name__, exc)
    saved = [p for p in out.iterdir() if p.name != "reference.png"]
    pictures = [p for p in saved if p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"]
    if code == 0 and len(pictures) >= 1 and akey not in said:
        c[example].passed("exit 0, saved {}".format([p.name for p in pictures]))
    else:
        c[example].failed("exit {}, saved {}, said {!r}".format(code, [p.name for p in saved], said[-160:]))
    shutil.rmtree(out, ignore_errors=True)


def run_checks(api, media_dir, real, invite_code, worker_token, worker_health, worker_ctl,
               python, restart_api, provider="chatgpt", *, db_path, fresh_api):
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
        for name in V1_JOB_CHECKS:
            c[name].skip(V1_REAL_SKIP)
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
    settled = re.match(r"(\d+)/(\d+) PASSED", summary)
    if settle.returncode == 0 and settled and settled.group(1) == settled.group(2) and int(settled.group(2)) >= 8:
        c["grok settles on words or a picture, never on an empty turn"].passed(summary)
    else:
        c["grok settles on words or a picture, never on an empty turn"].failed(
            "exit {} {}".format(settle.returncode, (summary or (lines[-1] if lines else ""))[:110]))

    for name, script, at_least in (
            ("a script is held to what its video model takes", "test_scripts.py", 30),
            ("a real account's picture budget outlives the worker", "test_worker_pacing.py", 8),
            ("several accounts of a provider share the work, and a thread stays on its account", "test_provider_accounts.py", 33),
            ("a job's failures take the right path through the pool and the runner", "test_worker_paths.py", 68),
            ("a browser that dies under a turn is dropped and cools the provider down", "test_pool_dead_browser.py", 6),
            ("a busy runner keeps saying it is alive", "test_runner_liveness.py", 4)):
        suite = subprocess.run([python, str(ROOT / "tests" / script)], capture_output=True, text=True, cwd=str(ROOT))
        lines = [l for l in ((suite.stdout or "") + (suite.stderr or "")).splitlines() if l.strip()]
        summary = next((l for l in reversed(lines) if "PASSED" in l), "")
        counted = re.match(r"(\d+)/(\d+) PASSED", summary)
        if suite.returncode == 0 and counted and counted.group(1) == counted.group(2) and int(counted.group(2)) >= at_least:
            c[name].passed(summary)
        else:
            c[name].failed("exit {} {}".format(suite.returncode, (summary or (lines[-1] if lines else ""))[:110]))

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

    register_race_checks(c, fresh_api, invite_code, password, stamp)

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

    # Issue #12 (2026-10-28): a video script asked of grok was taken (202) and failed a second later
    # in the worker. What a provider does not offer is refused before anything is made or charged.
    lacking = [name for name, offered in driver_features().items() if "video_script" not in offered]
    if media_id and lacking:
        def me():
            return (http("GET", api + "/auth/me", token=token)[1] or {}).get("quota_remaining")

        def conversations():
            return len((http("GET", api + "/conversations?limit=200", token=token)[1] or {}).get("items") or [])

        q0, conversations0 = me(), conversations()
        status, body = http("POST", api + "/video/script", {"provider": lacking[0], "media_id": media_id},
                            token=token)
        if status == 400 and me() == q0 and conversations() == conversations0:
            c["a feature its provider does not offer is refused at once and uncharged"].passed(
                "{} video script: 400 {!r}, credit and conversations untouched".format(
                    lacking[0], (body or {}).get("detail")))
        else:
            c["a feature its provider does not offer is refused at once and uncharged"].failed(
                "{} video script: status {} body {}, quota {} -> {}, conversations {} -> {}".format(
                    lacking[0], status, body, q0, me(), conversations0, conversations()))
    else:
        c["a feature its provider does not offer is refused at once and uncharged"].failed(
            "no media id ({}) or every driver writes video scripts ({})".format(media_id, lacking))

    pstatus, plist = http("GET", api + "/providers", token=token)
    said = {p.get("name"): sorted(p.get("features") or []) for p in (plist or {}).get("providers") or []}
    drivers = {name: sorted(offered) for name, offered in driver_features().items()}
    if pstatus == 200 and said == drivers:
        c["the api says what each provider offers, as its driver does"].passed(repr(said))
    else:
        c["the api says what each provider offers, as its driver does"].failed(
            "status {}: the api says {}, the drivers {}".format(pstatus, said, drivers))

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
        # A failed or empty turn knows nothing, so it proves nothing (two failed Gemini runs of
        # 2026-09-29 read green here).
        if (fresh or {}).get("status") == "done" and leaked.strip() and secret not in leaked:
            c["threads never cross conversations"].passed(
                "a new conversation does not know {}".format(secret))
        else:
            c["threads never cross conversations"].failed(
                "a new conversation answered {} with {!r}, knew {} {}".format(
                    (fresh or {}).get("status"), leaked[:80], secret in leaked, err_c or ""))
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

    # Gemini makes a video when asked for one (2026-10-06). Whoever made it, the platform keeps it as
    # a video and serves it as one, or a browser has nothing it knows how to play.
    if wanted("a video the provider makes is kept and served as a video"):
        done, err, _ = chat_once("make a short video of a cat asleep in the sun")
        found = []
        for media_id in ((done or {}).get("result") or {}).get("media") or []:
            mstatus, meta = http("GET", "{}/media/{}".format(api, media_id), token=token)
            req = urllib.request.Request("{}/media/{}/file".format(api, media_id), method="GET")
            req.add_header("Authorization", "Bearer " + token)
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    ctype, blob = resp.headers.get("Content-Type") or "", resp.read()
            except Exception as exc:
                ctype, blob = "{}: {}".format(type(exc).__name__, exc), b""
            found.append(((meta or {}).get("type"), ctype.split(";")[0].strip(), blob[4:8], len(blob)))
        played = [f for f in found if f[0] == "video" and f[1] == "video/mp4" and f[2] == b"ftyp"]
        if played:
            c["a video the provider makes is kept and served as a video"].passed(
                "type video, served as video/mp4, {} bytes starting with ftyp".format(played[0][3]))
        else:
            c["a video the provider makes is kept and served as a video"].failed(
                err or "media (type, served as, bytes 4-8, size): {}".format(found or "none came back"))

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

    # A deletion counts when the worker says it deleted a thread (its own count) and the api's record,
    # read-only, says it is this thread, claimed by the worker and settled after this delete: the count
    # alone cannot tell one deletion from another, the record alone cannot tell the worker did it.
    # A count the worker's health could not give is None, never 0: a failed read must not make the
    # next good one look like growth.
    def threads_deleted():
        health = http("GET", worker_health)[1]
        return (health.get("threads_deleted") or 0) if isinstance(health, dict) else None

    def read_db(sql, args, unreadable=()):
        try:
            con = sqlite3.connect(Path(db_path).as_uri() + "?mode=ro", uri=True)
            try:
                return con.execute(sql, args).fetchall()
            finally:
                con.close()
        except sqlite3.Error:
            return unreadable

    def tombstones():
        return read_db("SELECT id, thread_url, deleted_at, claimed_at FROM thread_tombstones WHERE provider = ?",
                       (provider,))

    def worker_removed(stone_ids, count_before, url=None):
        """A new tombstone (for url, if given) claimed and settled, and the worker's count grown."""
        settled = any(stone_id not in stone_ids and gone and claimed and (url is None or thread == url)
                      for stone_id, thread, gone, claimed in tombstones())
        count = threads_deleted()
        return settled and count is not None and count_before is not None and count >= count_before + 1

    def stop_record():
        health = http("GET", worker_health)[1]
        if not isinstance(health, dict):
            return None
        return ((health.get("providers") or {}).get(provider) or {}).get("last_stop")

    def results_refused():
        health = http("GET", worker_health)[1]
        return (health.get("results_refused") or 0) if isinstance(health, dict) else None

    def own_thread(conversation_id):
        rows = read_db("SELECT provider_thread_url FROM conversations WHERE id = ?", (conversation_id,))
        return rows[0][0] if rows else None

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
        own_url = own_thread(conv_pack)
        known = {stone[0] for stone in tombstones()}
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
        # gap and its tombstone interval: measured at 16s on a quiet host, and
        # 64s for a Gemini deletion, which drives the page (2026-09-29).
        deadline = time.time() + 150
        own_deleted = False
        while own_url and time.time() < deadline and not own_deleted:
            time.sleep(1)
            own_deleted = worker_removed(known, deleted_before, own_url)
        if (foreign_delete == 404 and still_mine and dstatus == 204 and conv_gone and media_gone
                and files_gone and media_ids and quota_now() == q_before and own_deleted):
            c["deleting a conversation removes its media files and the provider thread"].passed(
                "other user 404 and nothing moved; owner 204; {} media rows and files gone; "
                "its own thread deleted; quota unchanged".format(len(media_ids)))
        else:
            c["deleting a conversation removes its media files and the provider thread"].failed(
                "other user {} still mine {}, delete {}, conversation gone {}, {} media gone {}, "
                "files gone {}, quota {} -> {}, own thread {} deleted {}".format(
                    foreign_delete, still_mine, dstatus, conv_gone, len(media_ids), media_gone,
                    files_gone, q_before, quota_now(), (own_url or "none")[-24:], own_deleted))
    else:
        c["deleting a conversation removes its media files and the provider thread"].failed(
            "no conversation to delete")

    # ---- what became of a turn taken away from a running job ----

    def taken_away(message):
        """Post a turn, see its job running, delete its conversation: what the gate then holds."""
        held = {"q0": quota_now(), "known": {stone[0] for stone in tombstones()},
                "deleted_before": threads_deleted(), "refused_before": results_refused()}
        status, body = http("POST", api + "/chat", {"provider": provider, "message": message}, token=token)
        held["job"] = (body or {}).get("job_id") if status == 202 else None
        conversation = (body or {}).get("conversation_id") if status == 202 else None
        held["seen"] = (wait_state(held["job"], ("running", "done", "failed"), 20)
                        if held["job"] else {}).get("status")
        held["taken_at"] = time.time()
        held["delete"] = http("DELETE", "{}/conversations/{}".format(api, conversation), token=token)[0] \
            if conversation else 0
        held["state"] = wait_state(held["job"], ("cancelled", "done", "failed"), job_timeout) \
            if held["job"] else {}
        return held

    def is_back(held):
        refused = results_refused()
        return refused is not None and held["refused_before"] is not None and refused > held["refused_before"]

    def look(held):
        """(What accounts for the turn at this moment, the driver's stop record in hand, and what
        this look saw: the result back, a thread of the turn's still waiting to be removed)."""
        stop = stop_record()
        # The refusals before the tombstones: a result that comes back between the two reads is
        # then seen as still out, never as back with no tombstone.
        back = is_back(held)
        stones = read_db("SELECT id, deleted_at FROM thread_tombstones WHERE provider = ?", (provider,), None)
        fresh = [settled for stone, settled in stones or () if stone not in held["known"]]
        answer = thread_accounted(worker_removed(held["known"], held["deleted_before"]), stop,
                                  held["taken_at"], still_owed(back, stones, held["known"]), bool(fresh))
        return answer, stop, {"back": back, "waiting": any(not settled for settled in fresh)}

    def handed_back(held, seconds):
        """Wait for the worker to hand the turn's result back, which the api refuses."""
        deadline = time.time() + seconds
        while time.time() < deadline and not is_back(held):
            time.sleep(0.5)
        return is_back(held)

    def cancelled_and_refunded(held):
        return (held["seen"] == "running" and held["delete"] == 204
                and held["state"].get("status") == "cancelled" and quota_now() == held["q0"])

    def new_stones(held):
        return [stone for stone in tombstones() if stone[0] not in held["known"]]

    def told(held):
        return "seen {} delete {} final {} quota {} -> {}".format(
            held["seen"], held["delete"], held["state"].get("status"), held["q0"], quota_now())

    # Since 4536183 ChatGPT does not send a turn whose job is gone: no thread is made, nothing can
    # be removed, and the driver's own stop record is the only word on it. The mock plays that on
    # command, so every run meets what the real gate of 2026-10-01 met.
    unsent_check = "a turn taken away before it was sent leaves no thread, by the worker's own word"
    if real:
        c[unsent_check].skip("needs a provider that stops before its send on command; covered in mock mode")
    else:
        held = taken_away(UNSENT_PHRASE + ", then delete me")
        deadline = time.time() + 30
        accounted, stop = None, None
        while held["job"] and time.time() < deadline and not accounted:
            time.sleep(1)
            accounted, stop, _ = look(held)
        stones = new_stones(held)
        if cancelled_and_refunded(held) and accounted == "unsent" and not stones:
            c[unsent_check].passed(
                "job cancelled by the delete, credit returned, no thread made: the worker's stop "
                "record {} and no tombstone".format(stop))
        else:
            c[unsent_check].failed("{} accounted {} stop record {} new tombstones {}".format(
                told(held), accounted, stop, len(stones)))

    # No thread is not a clean word by itself. A driver that says nothing of its turn leaves it
    # unaccounted for, even once its result is back and with an older record in hand: the one the
    # check above left, which is why this one runs after it.
    silent_check = "a silent driver leaves its turn unaccounted for, whatever an older record says"
    if real:
        c[silent_check].skip("needs a provider that keeps silent on command; covered in mock mode")
    else:
        held = taken_away("{} {}, then delete me".format(UNSENT_PHRASE, SILENT_PHRASE))
        back = handed_back(held, 30)
        looks = []
        for _ in range(3):
            time.sleep(1)
            looks.append(look(held))
        stop = looks[-1][1]
        older = bool(stop) and stop.get("sent") is False and stop.get("at", held["taken_at"]) < held["taken_at"]
        stones = new_stones(held)
        if (cancelled_and_refunded(held) and back and older and not stones
                and all(look_[0] is None for look_ in looks)):
            c[silent_check].passed(
                "job cancelled by the delete, credit returned, its result back and no thread: "
                "unaccounted for at {} looks, with the older record {} in hand".format(len(looks), stop))
        else:
            c[silent_check].failed(
                "{} result handed back {} answers {} stop record {} older than the taking {} "
                "new tombstones {}".format(told(held), back, [look_[0] for look_ in looks], stop,
                                           older, len(stones)))

    # Nor is a driver's word enough while its own result is still out or a thread waits to be
    # removed: this one says unsent, reports the thread its turn made 2.5 seconds later, and that
    # thread takes 2.5 seconds to remove. The gate must be seen holding its answer through both.
    lying_check = "a driver that says unsent of a turn that made a thread is believed only once it is removed"
    if real:
        c[lying_check].skip("needs a provider that misreports on command; covered in mock mode")
    else:
        held = taken_away("{} {}, then delete me".format(UNSENT_PHRASE, LYING_PHRASE))
        deadline = time.time() + 60
        accounted, stop, held_out, held_waiting = None, None, 0, 0
        while held["job"] and time.time() < deadline and not accounted:
            time.sleep(0.5)
            accounted, stop, saw = look(held)
            said = bool(stop) and stop.get("sent") is False and stop.get("at", 0) >= held["taken_at"] - 0.05
            held_out += accounted is None and said and not saw["back"]
            held_waiting += accounted is None and said and saw["back"] and saw["waiting"]
        # Whatever was answered, let this turn's result come back before the next check counts.
        handed_back(held, 30)
        stones = new_stones(held)
        if (cancelled_and_refunded(held) and accounted == "removed" and held_out >= 2
                and held_waiting >= 2 and len(stones) == 1):
            c[lying_check].passed(
                "job cancelled by the delete, credit returned; its driver said {} of a turn that made "
                "a thread: no answer at {} looks while its result was out, none at {} while the thread "
                "waited, then removed".format(stop, held_out, held_waiting))
        else:
            c[lying_check].failed(
                "{} accounted {} stop record {} looks held while the result was out {} and while the "
                "thread waited {} new tombstones {}".format(
                    told(held), accounted, stop, held_out, held_waiting, len(stones)))

    # Deleting a conversation whose job is still running ends the job and gives
    # the credit back; the worker's late result is refused, so nothing of the
    # deleted conversation is written afterwards: no row, and no file either.
    # A picture is asked for so that there would be something to write.
    # The thread that turn had already opened on the provider's site is removed
    # too, once the worker reports where it landed; a turn the driver never sent
    # has none, and then the driver's own stop record says so.
    doomed_check = "deleting a conversation cancels its running job and refunds"
    if wanted(doomed_check):
        files_before = set(os.listdir(media_dir))
        held = taken_away(SLOW_PHRASE + ": draw a picture, then delete me while running")
        # The worker hands the turn's result back and the api refuses it (the mock's slow picture
        # finishes first; a real driver's stopped turn is posted and refused too). What it had
        # saved is removed then, so wait for that before looking at the files.
        handed_back(held, 20)
        time.sleep(1.5)
        files_after = set(os.listdir(media_dir))
        deadline = time.time() + 150
        accounted, stop = None, None
        while held["job"] and time.time() < deadline and not accounted:
            time.sleep(1)
            accounted, stop, _ = look(held)
        # The mock's slow picture always makes a thread; only a real driver can leave its turn unsent.
        answers = ("removed", "unsent") if real else ("removed",)
        media = (held["state"].get("result") or {}).get("media")
        if (cancelled_and_refunded(held) and not media and files_after == files_before
                and accounted in answers):
            c[doomed_check].passed(
                "job cancelled by the delete, credit returned, no media row or file written, " + (
                    "a thread tombstoned after its delete removed by the worker" if accounted == "removed"
                    else "its turn never sent, by the worker's stop record {}: no thread to remove".format(stop)))
        else:
            c[doomed_check].failed(
                "{} media {} new files {} its thread accounted {} stop record {}".format(
                    told(held), media, sorted(files_after - files_before)[:3], accounted, stop))

    # The rule the checks above lean on is the gate's own judgement, so it is held to its tables
    # on every run, and the tables to their size.
    table_check = "the gate's rule for a turn taken away holds on its table"
    wrong = [("accounted",) + row + (thread_accounted(*row[:5]),) for row in ACCOUNTED]
    wrong += [("owed",) + row + (still_owed(*row[:3]),) for row in OWED]
    wrong = [row for row in wrong if row[-2] != row[-1]]
    if not wrong and (len(ACCOUNTED), len(OWED)) == (ACCOUNTED_ROWS, OWED_ROWS):
        c[table_check].passed("{}/{} rows on what accounts for the turn, {}/{} on what is still owed".format(
            len(ACCOUNTED), ACCOUNTED_ROWS, len(OWED), OWED_ROWS))
    else:
        c[table_check].failed("{} rows wrong; {} and {} rows held, {} and {} owed{}".format(
            len(wrong), len(ACCOUNTED), len(OWED), ACCOUNTED_ROWS, OWED_ROWS,
            "; the first: {}".format(wrong[0]) if wrong else ""))

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

    # The safety plan, 2026-10-21: a driver that calls a turn done with neither words nor media.
    q0 = quota_now()
    if real:
        c["a done result with nothing in it fails and refunds"].skip(
            "needs a driver that answers with nothing on command; covered in mock mode")
    else:
        job_id = start_job(EMPTY_PHRASE + " for this one message")
        final = wait_state(job_id, ("done", "failed"), job_timeout) if job_id else {}
        conv = (job_state(job_id) or {}).get("conversation_id") if job_id else None
        cstatus, cbody = http("GET", "{}/conversations/{}".format(api, conv), token=token) if conv else (0, {})
        answers = [m for m in (cbody or {}).get("messages") or [] if m.get("role") == "assistant"]
        if (final.get("status") == "failed" and final.get("error_kind") == "empty_reply"
                and quota_now() == q0 and cstatus == 200 and answers == []):
            c["a done result with nothing in it fails and refunds"].passed(
                "failed as empty_reply, credit returned, no answer stored")
        else:
            c["a done result with nothing in it fails and refunds"].failed(
                "status {} kind {} quota {} -> {} answers stored {} conversation {}".format(
                    final.get("status"), final.get("error_kind"), q0, quota_now(), len(answers), cstatus))

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

    # The safety plan, 2026-10-21: with no worker coming back, the owner's own poll must free the
    # job its dead keeper held (the lease is 2s in this gate, and the served window the api's floor of
    # 30s, which is why the job is freed about 31s after the kill).
    q0 = quota_now()
    dead = "a running job whose worker died is failed and refunded by its owner's next poll"
    job_id = None if real else start_job(SLOW_PHRASE + ": nobody comes back for me")
    seen = wait_state(job_id, ("running",), 10) if job_id else {}
    if real:
        c[dead].skip("kills the worker mid-turn; provider-agnostic, covered in mock mode")
    elif seen.get("status") != "running":
        c[dead].failed("job never observed running (status {})".format(seen.get("status")))
    else:
        killed = worker_ctl["stop"]()
        killed_at = time.time()
        final = wait_state(job_id, ("failed", "done"), 45)
        freed_in = time.time() - killed_at
        left = quota_now()
        back = worker_ctl["start"]()
        if (killed and final.get("status") == "failed" and final.get("error_kind") in ("no_worker", "stranded")
                and left == q0 and back):
            c[dead].passed("failed as {} {:.0f}s after the kill, credit returned, no worker up meanwhile; the "
                           "new worker seen by the api {:.1f}s after its health answered".format(
                               final.get("error_kind"), freed_in, worker_ctl["seen_after"]()))
        else:
            c[dead].failed("killed {} final {} kind {} after {:.0f}s quota {} -> {} worker back {}".format(
                killed, final.get("status"), final.get("error_kind"), freed_in, q0, left, back))

    q0 = quota_now()
    job_id = start_job(SLOW_PHRASE + ": cancel me") if wanted("a running job can be cancelled") else None
    seen = wait_state(job_id, ("running",), 10) if job_id else {}
    cancelled_at = time.time()
    cancel_status, _ = http("POST", "{}/jobs/{}/cancel".format(api, job_id), token=token) \
        if job_id else (0, None)
    final = wait_state(job_id, ("cancelled", "done", "failed"), 20) if job_id else {}
    # Against ChatGPT the turn also stops at the site: never sent, or its stop button pressed, as the
    # driver says in health. Measured 2026-10-01: a stopped turn used to run on there. The mock has no
    # site to stop.
    at_site = real and provider == "chatgpt"
    stop = None
    # A stop is heard only once the page has opened, which can take two loads of a slow site.
    deadline = time.time() + 150
    while at_site and job_id and time.time() < deadline:
        got = stop_record()
        if got and got.get("at", 0) >= cancelled_at - 1:
            stop = got
            break
        time.sleep(1)
    stopped = not at_site or bool(stop and (stop.get("sent") is False or stop.get("pressed") is True))
    if (cancel_status == 200 and final.get("status") == "cancelled"
            and not ((final.get("result") or {}).get("media")) and quota_now() == q0 and stopped):
        c["a running job can be cancelled"].passed(
            "cancelled while {}, credit returned{}".format(
                seen.get("status"), ", at the site {}".format(stop) if at_site else ""))
    else:
        c["a running job can be cancelled"].failed(
            "cancel {} final {} quota {} -> {} stopped at the site {}".format(
                cancel_status, final.get("status"), q0, quota_now(), stop if at_site else "n/a"))

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
    # The video probe needs a picture still there: where no file is asked for (grok, gemini), the
    # delete check above removed the run's only one, and a missing picture rightly answers 404 first.
    live_picture = media_id and http("GET", "{}/media/{}".format(api, media_id), token=token)[0] != 404
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

    # An account its admin must fix (signed out, memory on) fails every turn until then, so the
    # provider is held out: not offered, a new turn refused uncharged, and the jobs already waiting
    # for it failed and refunded at once instead of each failing the same way in turn. The hold ends
    # by itself (5s here, 10 minutes in production) and the next turn is tried again. Measured
    # 2026-10-01: Gemini signed out, the web kept offering it and every turn failed in English.
    hold_checks = ("an account its admin must fix holds its provider out at once",
                   "jobs waiting for a held provider fail and refund at once",
                   "a hold ends by itself")
    if real:
        for name in hold_checks:
            c[name].skip("needs a provider that can pretend memory is on; covered in mock mode")
    else:
        def served_now():
            _, listing = http("GET", api + "/providers", token=token)
            return {p.get("name"): p.get("served") for p in ((listing or {}).get("providers") or [])
                    if isinstance(p, dict)}

        def served_within(seconds):
            deadline = time.time() + seconds
            while time.time() < deadline:
                if served_now().get(provider) is True:
                    return True
                time.sleep(0.5)
            return False

        # The memory check above may have started a hold of its own.
        ready = served_within(15)
        q0 = quota_now()
        busy = start_job(SLOW_PHRASE + ": keep the runner busy while two wait")
        wait_state(busy, ("running",), 20) if busy else {}
        refused = start_job(MEMORY_PHRASE + " for the first of the two")
        waiting = start_job("the second of the two, queued behind the refused one")
        # The other provider's runner is busy three seconds longer, so one of its jobs is waiting too
        # when the hold starts: a hold is its own provider's, never everybody's.
        time.sleep(3)
        start_job(SLOW_PHRASE + ": the other provider is busy too", as_provider=other_provider)
        other_waiting = start_job("waiting for the other provider", as_provider=other_provider)
        settled = wait_state(refused, ("failed", "done"), 60) if refused else {}
        held_at = time.time()
        served = served_now()
        q_held = quota_now()
        other_at_hold = job_state(other_waiting).get("status") if other_waiting else None
        rstatus, _ = http("POST", api + "/chat",
                          {"provider": provider, "message": "a turn into the hold"}, token=token)
        q_refused = quota_now()
        behind = wait_state(waiting, ("failed", "done", "cancelled"), 10) if waiting else {}
        behind_in = time.time() - held_at
        wait_state(busy, ("done", "failed"), 30) if busy else {}
        # Still held three seconds on (the hold is five here), then back by itself.
        time.sleep(max(0.0, held_at + 3 - time.time()))
        still_held = served_now().get(provider) is False
        back = served_within(15)
        back_in = time.time() - held_at
        other_final = wait_state(other_waiting, ("done", "failed", "cancelled"), 30) if other_waiting else {}
        if (ready and settled.get("status") == "failed"
                and settled.get("error_kind") == "provider_misconfigured"
                and served.get(provider) is False and served.get(other_provider) is True
                and rstatus == 503 and q_refused == q_held):
            c["an account its admin must fix holds its provider out at once"].passed(
                "{} not served right after the refusal, {} still served, a new turn 503 and "
                "uncharged".format(provider, other_provider))
        else:
            c["an account its admin must fix holds its provider out at once"].failed(
                "served before {} refused {} kind {} served after {} new turn {} quota {} -> {}".format(
                    ready, settled.get("status"), settled.get("error_kind"), served, rstatus,
                    q_held, q_refused))
        # Of this provider's three only the slow turn may cost: the refused one and the one behind it
        # are given back, the second without ever reaching the worker. The other provider's two are
        # untouched: still charged at the hold, the waiting one still waiting, then done.
        if (behind.get("status") == "failed" and behind.get("error_kind") == "provider_misconfigured"
                and behind.get("attempts") == 0 and behind_in < 5 and q_held == q0 - 3
                and other_at_hold == "pending" and other_final.get("status") == "done"):
            c["jobs waiting for a held provider fail and refund at once"].passed(
                "the job behind it failed {:.1f}s after the refusal, never claimed, quota {} -> {}; "
                "{}'s waiting job untouched, then done".format(behind_in, q0, q_held, other_provider))
        else:
            c["jobs waiting for a held provider fail and refund at once"].failed(
                "the job behind it {} kind {} attempts {} after {:.1f}s, quota {} -> {}; {}'s waiting job "
                "{} at the hold, then {}".format(
                    behind.get("status"), behind.get("error_kind"), behind.get("attempts"), behind_in,
                    q0, q_held, other_provider, other_at_hold, other_final.get("status")))
        after_hold = start_job("an ordinary turn once the hold is over")
        after_final = wait_state(after_hold, ("done", "failed"), job_timeout) if after_hold else {}
        if still_held and back and after_final.get("status") == "done":
            c["a hold ends by itself"].passed(
                "{} still held 3s after the refusal, served again after {:.1f}s, an ordinary turn "
                "done".format(provider, back_in))
        else:
            c["a hold ends by itself"].failed(
                "held at 3s {}, served again {} after {:.1f}s, then a turn {} {}".format(
                    still_held, back, back_in, after_final.get("status"), after_final.get("error")))

    v1_checks(api, c, token, btoken, media_dir, db_path, job_timeout, real, restart_worker)

    # Issue #27: the nightly Library cleanup removes files only of threads the api says are the
    # platform's: a live conversation's, or a deleted one's tombstone, of that provider.
    known_check = "the api tells a worker which threads are the platform's, and only for that provider"
    try:
        with sqlite3.connect(db_path) as conn:
            live = conn.execute("SELECT provider_thread_url FROM conversations WHERE provider = ? AND"
                                " provider_thread_url IS NOT NULL LIMIT 1", (provider,)).fetchone()
            stone = conn.execute("SELECT thread_url FROM thread_tombstones WHERE provider = ? LIMIT 1",
                                 (provider,)).fetchone()
    except sqlite3.Error:
        live, stone = None, None
    asked = [u[0] for u in (live, stone) if u] + ["https://chatgpt.com/c/not-the-platforms"]

    def known_for(name, headers):
        kstatus, kbody = http("POST", api + "/internal/threads/known", {"provider": name, "thread_urls": asked},
                              headers=headers)
        return kstatus, set((kbody or {}).get("known") or []) if isinstance(kbody, dict) else set()

    mine_status, mine = known_for(provider, {"X-Worker-Token": worker_token})
    other_status, other = known_for(other_provider, {"X-Worker-Token": worker_token})
    nobody = known_for(provider, None)[0]
    if (live and stone and mine_status == 200 and mine == set(asked[:-1]) and other_status == 200
            and not (other & mine) and nobody == 401):
        c[known_check].passed("a live thread and a tombstone known, an address it never stored not, another "
                              "provider none of them, no worker token 401")
    else:
        c[known_check].failed("asked {}, answered {} {}, another provider {} {}, no token {}".format(
            asked, mine_status, mine, other_status, other, nobody))

    if not real:
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
    extra_apis = []
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
        # A provider whose account needs its admin is held out this long (10 minutes in production),
        # so the check that the hold ends by itself does not wait out the production one.
        "PROVIDER_HOLD_SECONDS": "5",
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

        worker_logs = {"n": 1, "seen_after": None}

        def seen_by_api(providers, since, seconds=30):
            """Seconds until the api had a contact (a claim or a ping) from each provider since `since`,
            None if it never did: the api counts a worker as serving only from that contact."""
            started = time.time()
            while time.time() < started + seconds:
                with sqlite3.connect(db_dir / "app.db") as conn:
                    seen = {row[0] for row in conn.execute(
                        "SELECT provider FROM worker_pings WHERE last_seen >= ?", (since,))}
                if set(providers) <= seen:
                    return time.time() - started
                time.sleep(0.25)
            return None

        def start_worker(extra_env=None):
            nonlocal worker_proc, worker_log
            worker_logs["n"] += 1
            env = dict(worker_env)
            env.update(extra_env or {})
            with sqlite3.connect(db_dir / "app.db") as conn:
                since = conn.execute("SELECT datetime('now')").fetchone()[0]
            worker_proc, worker_log = start_service(
                python, ROOT / "worker", worker_port, env,
                workspace / "worker-{}.log".format(worker_logs["n"]))
            if not wait_healthy(worker_health, 40)[0]:
                return False
            # Healthy is not yet serving: a check that sends at once was refused 503 with no job on a
            # loaded machine (2026-10-22, twice), so the gate waits for the api to have seen it.
            worker_logs["seen_after"] = seen_by_api(env["PROVIDERS"].split(","), since)
            return worker_logs["seen_after"] is not None

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

        worker_ctl = {"restart": restart_worker, "stop": stop_worker, "start": start_worker,
                      "seen_after": lambda: worker_logs["seen_after"]}

        def restart_api(extra_env):
            """Bring the api back with extra settings, on the same database and port."""
            nonlocal api_proc, api_log
            stop(api_proc, api_log)
            env = dict(api_env)
            env.update(extra_env)
            api_proc, api_log = start_service(python, ROOT / "api", api_port, env, workspace / "api-2.log")
            return wait_healthy(api_base + "/health", 25)[0]

        def fresh_api(name):
            """A second api on its own port and its own empty database; returns its base url (None
            if it never became healthy, with its log's tail), and the function that stops it. The
            gate's own exit stops it too, should the gate be interrupted while it waits."""
            port = free_port()
            env = dict(api_env)
            env.update({"DB_PATH": str(workspace / name / "app.db"),
                        "MEDIA_PATH": str(workspace / name / "media")})
            log_path = workspace / "{}.log".format(name)
            proc, log = start_service(python, ROOT / "api", port, env, log_path)
            extra_apis.append((proc, log))
            base = "http://127.0.0.1:{}".format(port)
            if wait_healthy(base + "/health", 25)[0]:
                return base, "", lambda: stop(proc, log)
            return None, tail(log_path), lambda: stop(proc, log)

        checks = run_checks(api_base, media_dir, args.real, invite_code,
                            worker_token, worker_health, worker_ctl, python, restart_api,
                            args.provider, db_path=db_dir / "app.db", fresh_api=fresh_api)

    except RuntimeError:
        pass
    except KeyboardInterrupt:
        boot_error = "interrupted"
    finally:
        stop(worker_proc, worker_log)
        stop(api_proc, api_log)
        for proc, log in extra_apis:
            stop(proc, log)

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
