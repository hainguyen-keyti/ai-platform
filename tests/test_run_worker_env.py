#!/usr/bin/env python3
"""scripts/run-worker.sh gives the worker every line .env sets for it, and a name the command line
set wins over the file.

Found on 2026-10-27 (plan (3) #2, issue #8): the script sourced .env without exporting it, so
PROVIDERS and the pacing reached the worker only when the starting shell had exported them (a mock
worker read min_gap_seconds 0.0 with .env saying 3), and a name given on the command line other than
API_URL, WORKER_TOKEN and PROVIDER_MODE lost to the file. Here the script runs from a copy of the
repo with a .env of its own, never this machine's, in mock mode on a free port, against a fake api
that records the worker's token; each worker is stopped before the next one starts. Runs under the
cloakbrowser venv inside WSL or on macOS. Prints N/N PASSED.
"""

import http.server
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = Path(os.environ.get("CLOAKBROWSER_VENV", str(Path.home() / "cloakbrowser-env")))

FILE_TOKEN = "token-from-the-file"
CLI_TOKEN = "token from the 'command line'"
DOTENV = """# A .env as a person writes it: the secrets, the worker's lines, a per-provider override.
API_URL=http://127.0.0.1:{file_api}
WORKER_TOKEN={token}
PROVIDER_MODE=real
PROVIDERS=chatgpt,grok
MIN_GAP_SECONDS=7
MIN_GAP_SECONDS__GROK=150
COOLDOWN_BASE_SECONDS=45
"""


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeApi:
    """Answers the worker's polls with 204 and keeps the tokens it was sent."""

    def __init__(self):
        self.tokens = []
        seen = self.tokens

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                seen.append(self.headers.get("X-Worker-Token"))
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                self.send_response(204)
                self.end_headers()

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def copy_repo(where):
    (where / "scripts").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "run-worker.sh", where / "scripts" / "run-worker.sh")
    shutil.copytree(ROOT / "worker", where / "worker", ignore=shutil.ignore_patterns("__pycache__"))


def start_worker(repo, extra_env):
    """The script as a person starts it: a clean environment plus what the command line names."""
    port = free_port()
    env = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "CLOAKBROWSER_VENV": str(VENV),
           "CODE_SHA": "test", "WORKER_PORT": str(port), "PYTHONUNBUFFERED": "1"}
    env.update(extra_env)
    log = open(repo / "worker-{}.log".format(port), "w")
    proc = subprocess.Popen(["sh", "./scripts/run-worker.sh"], cwd=str(repo), env=env, stdout=log,
                            stderr=subprocess.STDOUT, start_new_session=True)
    health = None
    deadline = time.time() + 120
    while time.time() < deadline and proc.poll() is None:
        try:
            with urllib.request.urlopen("http://127.0.0.1:{}/health".format(port), timeout=2) as answer:
                health = json.loads(answer.read())
                break
        except Exception:
            time.sleep(0.5)
    return proc, log, port, health


def stop_worker(proc, log, port):
    if proc.poll() is None:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)
    log.close()
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def run(repo, api, extra_env):
    """Start a worker, give it a few polls, read what it took, stop it."""
    api.tokens.clear()
    proc, log, port, health = start_worker(repo, extra_env)
    time.sleep(3 if health else 0)
    tokens = list(api.tokens)
    closed = stop_worker(proc, log, port)
    output = (repo / "worker-{}.log".format(port)).read_text(errors="replace")
    return health, tokens, closed, output


def summary(health):
    if not health:
        return "no health"
    pacing = health.get("pacing") or {}
    return {"mode": health.get("mode"), "providers": sorted((health.get("providers") or {}).keys()),
            "min_gap": pacing.get("min_gap_seconds"), "cooldown_base": pacing.get("cooldown_base_seconds"),
            "grok_min_gap": ((pacing.get("per_provider") or {}).get("grok") or {}).get("min_gap")}


def main():
    if not (VENV / "bin" / "python").exists():
        sys.exit("cloakbrowser venv not found at {}".format(VENV))
    results = []

    def check(name, ok, detail):
        results.append(ok)
        print("[{}] {}  {}".format("PASS" if ok else "FAIL", name, detail))

    work = Path(tempfile.mkdtemp(prefix="run-worker-env-", dir=str(Path.home() / ".cache")))
    file_api, cli_api = FakeApi(), FakeApi()
    try:
        repo = work / "repo"
        copy_repo(repo)
        (repo / ".env").write_text(DOTENV.format(file_api=file_api.port, token=FILE_TOKEN))

        # Only PROVIDER_MODE comes from the command line here: the file says real.
        health, tokens, closed_a, out_a = run(repo, file_api, {"PROVIDER_MODE": "mock"})
        got = summary(health)
        check(".env's own worker lines reach the worker",
              got != "no health" and got["mode"] == "mock" and got["providers"] == ["chatgpt", "grok"]
              and got["min_gap"] == 7.0
              and got["grok_min_gap"] == 150.0 and got["cooldown_base"] == 45.0,
              "{} (the file says chatgpt,grok, a 7s gap, grok's 150s, a 45s cooldown base; mock from the "
              "command line)".format(got))
        check("the token .env sets is the one the worker sends",
              bool(tokens) and set(tokens) == {FILE_TOKEN},
              "{} polls, the file's token {}".format(len(tokens), "on every one" if tokens and set(tokens) == {FILE_TOKEN}
                                                      else "missing"))

        cli = {"PROVIDER_MODE": "mock", "PROVIDERS": "grok", "MIN_GAP_SECONDS": "1",
               "API_URL": "http://127.0.0.1:{}".format(cli_api.port), "WORKER_TOKEN": CLI_TOKEN}
        health, tokens, closed_b, out_b = run(repo, cli_api, cli)
        got = summary(health)
        check("names given on the command line win over .env",
              got != "no health" and got["providers"] == ["grok"] and got["min_gap"] == 1.0
              and got["cooldown_base"] == 45.0,
              "{} (the command line says grok and a 1s gap; the cooldown base still the file's 45)".format(got))
        check("API_URL, WORKER_TOKEN and PROVIDER_MODE given on the command line still win",
              got != "no health" and got["mode"] == "mock"
              and (health or {}).get("api_url") == cli["API_URL"] and bool(tokens) and set(tokens) == {CLI_TOKEN},
              "mode {}, api_url the command line's {}, {} polls to it with the command line's token {}".format(
                  got if got == "no health" else got["mode"], (health or {}).get("api_url") == cli["API_URL"],
                  len(tokens), bool(tokens) and set(tokens) == {CLI_TOKEN}))

        leaked = [t for t in (FILE_TOKEN, CLI_TOKEN) if t in out_a or t in out_b]
        check("every worker it started is gone, and no token is printed",
              closed_a and closed_b and not leaked,
              "ports closed {}, tokens in the script's output {}".format([closed_a, closed_b], len(leaked)))
    finally:
        file_api.close()
        cli_api.close()
        shutil.rmtree(work, ignore_errors=True)

    print("{}/{} PASSED".format(sum(results), len(results)))
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
