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
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class Check:
    def __init__(self, name):
        self.name = name
        self.ok = False
        self.detail = "not reached"

    def passed(self, detail=""):
        self.ok = True
        self.detail = detail

    def failed(self, detail):
        self.ok = False
        self.detail = detail


def http(method, url, body=None, token=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
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


def run_checks(api, media_dir, real, invite_code):
    # Must exceed the provider's own ceiling (REPLY_TIMEOUT is 300s) plus the
    # first-use browser launch, otherwise the gate reports a timeout that only
    # the gate caused.
    job_timeout = 420 if real else 30
    checks = [Check(n) for n in (
        "api health",
        "register (invite code)",
        "login returns jwt",
        "auth rejects bad token",
        "chat job completes",
        "image job produces file",
        "video script job returns text",
        "media listing scoped to user",
    )]
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
            },
            workspace / "api.log",
        )
        ok, detail = wait_healthy(api_base + "/health", 25)
        if not ok:
            boot_error = "api never became healthy ({})\n{}".format(detail, tail(workspace / "api.log"))
            raise RuntimeError(boot_error)

        worker_proc, worker_log = start_service(
            python, ROOT / "worker", worker_port,
            {
                "API_URL": api_base,
                "WORKER_TOKEN": worker_token,
                "PROVIDER_MODE": "real" if args.real else "mock",
                "MEDIA_PATH": str(media_dir),
                "SESSIONS_PATH": str(sessions_dir),
            },
            workspace / "worker.log",
        )
        ok, detail = wait_healthy("http://127.0.0.1:{}/health".format(worker_port), 40)
        if not ok:
            boot_error = "worker never became healthy ({})\n{}".format(detail, tail(workspace / "worker.log"))
            raise RuntimeError(boot_error)

        checks = run_checks(api_base, media_dir, args.real, invite_code)

    except RuntimeError:
        pass
    except KeyboardInterrupt:
        boot_error = "interrupted"
    finally:
        stop(worker_proc, worker_log)
        stop(api_proc, api_log)

    if not checks:
        names = ("api health", "register (invite code)", "login returns jwt", "auth rejects bad token",
                 "chat job completes", "image job produces file", "video script job returns text",
                 "media listing scoped to user")
        checks = []
        for n in names:
            ch = Check(n)
            ch.failed("stack did not start")
            checks.append(ch)

    width = max(len(c.name) for c in checks)
    print()
    print("mode: {}".format("real providers" if args.real else "mock providers"))
    print()
    for c in checks:
        print("[{}] {}  {}".format("PASS" if c.ok else "FAIL", c.name.ljust(width), c.detail))
    passed = sum(1 for c in checks if c.ok)
    print("=" * (width + 12))
    print("{}/{} PASSED".format(passed, len(checks)))
    if boot_error:
        print()
        print("boot error:")
        print(boot_error)

    if args.keep:
        print("\nworkspace kept at {}".format(workspace))
    else:
        shutil.rmtree(workspace, ignore_errors=True)

    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
