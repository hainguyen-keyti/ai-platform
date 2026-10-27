#!/usr/bin/env python3
"""The safety plan's real runs, through the api (the route the web calls), the host worker real on
the new code: (1) a Grok conversation gets a first turn and then a follow-up, which must answer with
its own words (the read before the send answers 200, as almost always); (2) a ChatGPT request
through /v1/images with a picture, done with a picture (the attach path intact). Uses a throwaway
test account of the local app, kept in storage/diagnostics/manual-test-account.json (made here on
the first run from INVITE_CODE in the environment; never printed). Spends two Grok turns and one
ChatGPT turn.

    set -a; . ./.env; set +a; python3 /tmp/real_safety_runs.py
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "http://localhost:3000"
ROOT = Path("/Users/keyti/Sources/RE/chatgpt")
ACCOUNT_FILE = ROOT / "storage" / "diagnostics" / "manual-test-account.json"
OUT = ROOT / "storage" / "diagnostics" / "real-safety-runs"


def call(method, path, body=None, token=None):
    request = urllib.request.Request(API + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None)
    if body is not None:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, raw.decode(errors="replace")


def account():
    if ACCOUNT_FILE.exists():
        return json.loads(ACCOUNT_FILE.read_text())
    invite = os.environ.get("INVITE_CODE")
    if not invite:
        sys.exit("INVITE_CODE is not in the environment (set -a; . ./.env; set +a)")
    made = {"email": "manual-test-{}@aiplatform-acceptance.com".format(int(time.time())),
            "password": "manual-test-pw-{}".format(os.urandom(4).hex())}
    status, body = call("POST", "/auth/register", dict(made, name="Manual test", invite_code=invite))
    if status != 201:
        sys.exit("could not register the test account: {} {}".format(status, body))
    ACCOUNT_FILE.parent.mkdir(parents=True, exist_ok=True)
    ACCOUNT_FILE.write_text(json.dumps(made))
    print("test account made and kept at", ACCOUNT_FILE)
    return made


def wait(job_id, token, limit=420):
    started = time.time()
    while time.time() - started < limit:
        status, job = call("GET", "/jobs/{}".format(job_id), token=token)
        if status == 200 and job.get("status") in ("done", "failed", "cancelled"):
            return job, time.time() - started
        time.sleep(2)
    return {"status": "still running"}, time.time() - started


def turn(token, message, conversation_id=None):
    body = {"provider": "grok", "message": message}
    if conversation_id:
        body["conversation_id"] = conversation_id
    status, made = call("POST", "/chat", body, token=token)
    if status != 202:
        return None, {"status": "refused {} {}".format(status, made)}, 0
    job, took = wait(made["job_id"], token)
    return made["conversation_id"], job, took


def main():
    who = account()
    status, login = call("POST", "/auth/login", {"email": who["email"], "password": who["password"]})
    if status != 200:
        sys.exit("login failed: {} {}".format(status, login))
    token = login["token"]
    before = call("GET", "/auth/me", token=token)[1]["quota_remaining"]
    print("credits before:", before)
    wanted = sys.argv[1:] or ["grok", "chatgpt"]
    if "grok" in wanted:
        grok_runs(token)
    if "chatgpt" in wanted:
        chatgpt_run(token)
    after = call("GET", "/auth/me", token=token)[1]["quota_remaining"]
    print("credits {} -> {}".format(before, after))


def grok_runs(token):
    print("1. Grok, the first turn, at", time.strftime("%H:%M:%S"), flush=True)
    conversation, job, took = turn(token, "Thủ đô của Pháp là thành phố nào? Trả lời trong một câu.")
    answer1 = ((job.get("result") or {}).get("text") or "")
    print("   {} after {:.0f}s: {!r} {}".format(job.get("status"), took, answer1[:80], job.get("error") or ""))
    if job.get("status") != "done" or not conversation:
        sys.exit("the first Grok turn did not end with words; the follow-up is not sent")
    print("   waiting 90s before the follow-up", flush=True)
    time.sleep(90)
    print("2. Grok, the follow-up in the same conversation, at", time.strftime("%H:%M:%S"), flush=True)
    _, job, took = turn(token, "Còn thủ đô của Đức là thành phố nào? Trả lời trong một câu.", conversation)
    answer2 = ((job.get("result") or {}).get("text") or "")
    print("   {} after {:.0f}s: {!r} {}".format(job.get("status"), took, answer2[:80], job.get("error") or ""))
    own = "berlin" in answer2.lower() and answer2.strip() != answer1.strip()
    print("   this turn's own words (Berlin, not the first answer):", own)


def chatgpt_run(token):
    print("3. ChatGPT through /v1/images with a picture, at", time.strftime("%H:%M:%S"), flush=True)
    reference = sorted(p for p in (ROOT / "storage" / "media").glob("chatgpt-*.png"))[-1]
    status, key = call("POST", "/auth/api-keys", {"name": "safety plan real run"}, token=token)
    if status != 201:
        sys.exit("no key: {} {}".format(status, key))
    OUT.mkdir(parents=True, exist_ok=True)
    started = time.time()
    try:
        ran = subprocess.run([sys.executable, str(ROOT / "scripts" / "image_api_example.py"), "--prompt",
                              "the same picture as a pencil sketch", "--image", str(reference), "--out", str(OUT)],
                             capture_output=True, text=True, timeout=900, env=dict(os.environ, AIP_API_KEY=key["key"]))
        said = (ran.stdout + ran.stderr).strip()
        print("   exit {} after {:.0f}s".format(ran.returncode, time.time() - started))
        print("\n".join("   " + line for line in said.splitlines() if "aip_" not in line))
    finally:
        call("DELETE", "/auth/api-keys/{}".format(key["id"]), token=token)
    print("key revoked")
    for path in sorted(OUT.iterdir()):
        blob = path.read_bytes()
        print("   {} {} bytes {}".format(path.name, len(blob), "png" if blob[:8] == b"\x89PNG\r\n\x1a\n" else blob[:4]))


if __name__ == "__main__":
    main()
