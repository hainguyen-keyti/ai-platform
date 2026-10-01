#!/usr/bin/env python3
"""Does each provider still answer through the platform? One short turn per provider, against the
running stack, as a person would send it.

    INVITE_CODE=... python tests/session_check.py [chatgpt] [grok] [gemini] [--keep]

Standard library only. It registers a throwaway user, asks each provider named (or every provider a
worker serves, when none is named) for the single word "pong", and reads beside the reply what the
worker's health says of that provider's account (memory off, on, unknown). A provider no worker serves
fails. With a real worker each turn is a real one: it spends a turn of that account and makes a thread
there, so the check deletes the conversations it made, which has the platform remove their threads
(--keep leaves them). Run it after each start of the worker to see that a saved session still lives.
Prints a PASS/FAIL table and N/M PASSED; exits 1 on any failure.
"""

import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request

API = os.environ.get("API_URL", "http://localhost:3000")
WORKER = os.environ.get("WORKER_URL", "http://localhost:8000")
PROMPT = "Reply with the single word: pong"
TURN_TIMEOUT = 240

results = []


def record(name, ok, detail):
    results.append(ok)
    print("[{}] {}  {}".format("PASS" if ok else "FAIL", name, detail), flush=True)


def http(method, url, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode()
            return response.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except OSError:
        return 0, None


def account_reading(provider):
    status, health = http("GET", WORKER + "/health")
    if status != 200:
        return "the worker's health unread"
    return "memory {}".format(((health.get("providers") or {}).get(provider) or {}).get("memory"))


def ask(provider, token, made):
    status, body = http("POST", API + "/chat", {"provider": provider, "message": PROMPT}, token)
    if status != 202:
        return False, "the turn was refused ({})".format(status)
    made.append(body["conversation_id"])
    started, job = time.time(), {}
    while time.time() - started < TURN_TIMEOUT:
        job = http("GET", "{}/jobs/{}".format(API, body["job_id"]), token=token)[1] or {}
        if job.get("status") in ("done", "failed", "cancelled"):
            break
        time.sleep(1)
    text = " ".join(((job.get("result") or {}).get("text") or "").split())
    ok = job.get("status") == "done" and "pong" in text.casefold()
    return ok, "{} in {:.0f}s, reply {!r}{}, {}".format(
        job.get("status") or "no answer", time.time() - started, text[:60],
        ", error {!r}".format((job.get("error") or "")[:90]) if job.get("error") else "", account_reading(provider))


def main():
    named = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    keep = "--keep" in sys.argv[1:]
    invite = os.environ.get("INVITE_CODE")
    if not invite:
        sys.exit("INVITE_CODE is not set (set -a; . ./.env; set +a)")
    email = "session-check-{}@aiplatform-acceptance.com".format(int(time.time()))
    password = secrets.token_urlsafe(12)
    status, _ = http("POST", API + "/auth/register",
                     {"email": email, "password": password, "invite_code": invite, "name": "Session check"})
    token = (http("POST", API + "/auth/login", {"email": email, "password": password})[1] or {}).get("token")
    if status != 201 or not token:
        sys.exit("could not register and sign in at {} (register {})".format(API, status))
    listed = (http("GET", API + "/providers", token=token)[1] or {}).get("providers") or []
    served = {entry["name"]: entry["served"] for entry in listed}
    wanted = named or [name for name, on in served.items() if on]
    if not wanted:
        record("a provider is served", False, "no worker serves any provider: {}".format(served))
    made = []
    for provider in wanted:
        if not served.get(provider):
            record("{} answers".format(provider), False, "no worker serves it")
            continue
        ok, detail = ask(provider, token, made)
        record("{} answers".format(provider), ok, detail)
    if made and not keep:
        gone = [http("DELETE", "{}/conversations/{}".format(API, conversation), token=token)[0] for conversation in made]
        print("deleted the {} conversation(s) this check made: {}".format(len(made), gone))
    passed = sum(1 for ok in results if ok)
    print("{}/{} PASSED".format(passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
