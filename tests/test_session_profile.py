#!/usr/bin/env python3
"""A provider's session is one browser profile and one device. The real driver classes with a real
browser on a local page; no site, no account.

    ~/cloakbrowser-env/bin/python tests/test_session_profile.py

Measured 2026-10-01: every cloakbrowser launch draws a random device seed (two launches read the GPU
as "Apple M3", then "Apple M1 Pro"), the drivers loaded a state file saved on the login day and never
wrote it back, and a Gemini login was signed out by Google after four such launches in 47 minutes.
With one profile directory and one seed a second launch reads the same device, keeps its cookies,
and a second browser on the same profile is refused by Chromium itself.
The sessions folder here is as this machine has it: the old state file still lies beside the profile.
Prints N/8 PASSED.
"""

import http.server
import json
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import cloakbrowser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from src.providers import chatgpt, gemini, grok  # noqa: E402
from src.providers.base import ProviderError  # noqa: E402

DRIVERS = (("chatgpt", chatgpt.ChatGPTProvider), ("grok", grok.GrokProvider), ("gemini", gemini.GeminiProvider))
SEED = "device-seed"
OLD_STATE = json.dumps({"cookies": [], "origins": []})
GPU = """
() => { try { const gl = document.createElement('canvas').getContext('webgl');
    return gl.getParameter(gl.getExtension('WEBGL_debug_renderer_info').UNMASKED_RENDERER_WEBGL);
} catch (e) { return 'unreadable: ' + String(e).slice(0, 40); } }
"""
# Another process holding a provider's session, the way a worker, a gate or a probe would.
HOLDER = """
import sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from src.providers import chatgpt
p = chatgpt.ChatGPTProvider(Path(sys.argv[2]), Path(sys.argv[3]))
page = p._ensure_page()
page.goto(sys.argv[4], wait_until="domcontentloaded", timeout=20000)
print("READY", flush=True)
time.sleep(600)
"""

results = []
launches = []


def record(name, ok, detail):
    results.append(ok)
    print("[{}] {}  {}".format("PASS" if ok else "FAIL", name, detail), flush=True)


def recording(how, real):
    def launch(*args, **kwargs):
        where = kwargs.get("user_data_dir") or (args[0] if args else None)
        launches.append({"how": how, "args": list(kwargs.get("args") or []), "where": str(where or "")})
        return real(*args, **kwargs)
    return launch


class Page(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"<html><body>session profile test</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        if self.path.startswith("/learn"):
            self.send_header("Set-Cookie", "learned=1; Max-Age=86400; Path=/")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def folder(profiles=True):
    """A sessions folder: each provider's old state file, and its profile as a login leaves it."""
    sessions = Path(tempfile.mkdtemp(prefix="session-profile-test-"))
    for name, _ in DRIVERS:
        (sessions / "{}.json".format(name)).write_text(OLD_STATE)
        if profiles:
            (sessions / name).mkdir()
    return sessions


def media():
    return Path(tempfile.mkdtemp(prefix="session-profile-media-"))


def seeds(launch):
    return [arg.split("=", 1)[1] for arg in launch["args"] if arg.startswith("--fingerprint=")]


def kept_seed(sessions, name):
    try:
        return (sessions / name / SEED).read_text().strip()
    except OSError:
        return None


def hold(sessions, url):
    """Start another process on chatgpt's session; True once its browser has the page."""
    child = subprocess.Popen([sys.executable, "-c", HOLDER, str(ROOT / "worker"), str(media()), str(sessions), url],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    watchdog = threading.Timer(90, child.kill)
    watchdog.start()
    try:
        line = child.stdout.readline()
    finally:
        watchdog.cancel()
    return child, "READY" in line


def end(child, sessions):
    """Kill the holder the way a worker is killed, and wait for its browser to let the profile go."""
    child.kill()
    child.wait(timeout=30)
    profile = str(sessions / "chatgpt")
    for _ in range(40):
        if subprocess.run(["pgrep", "-f", profile], capture_output=True).returncode != 0:
            return
        time.sleep(0.5)


def same_device(name, cls, sessions, url):
    first, gpus, error = len(launches), [], None
    try:
        for _ in range(3):
            p = cls(media(), sessions)
            page = p._ensure_page()
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            gpus.append(page.evaluate(GPU))
            p.stop()
    except Exception as exc:
        error = "{}: {}".format(type(exc).__name__, str(exc).strip().split("\n")[0][:90])
    mine = launches[first:]
    named = [seeds(launch) for launch in mine]
    kept = kept_seed(sessions, name)
    ok = (error is None and len(mine) == 3 and all(len(n) == 1 for n in named)
          and {n[0] for n in named} == {kept} and len(set(gpus)) == 1
          and all(launch["where"] == str(sessions / name) for launch in mine))
    record("{}: every launch is the same device".format(name), ok,
           "seed named at each launch {}, kept in the profile {}, gpu {}, profile {}{}".format(
               [n[0] if n else None for n in named], kept, [g.split("Renderer: ")[-1].split(",")[0] for g in gpus],
               sorted({launch["where"].rsplit("/", 1)[-1] or "none" for launch in mine}),
               ", " + error if error else ""))


def main():
    cloakbrowser.launch = recording("launch", cloakbrowser.launch)
    cloakbrowser.launch_persistent_context = recording("profile", cloakbrowser.launch_persistent_context)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Page)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:{}".format(server.server_address[1])
    sessions = folder()

    for name, cls in DRIVERS:
        same_device(name, cls, sessions, base + "/")

    own = {name: kept_seed(sessions, name) for name, _ in DRIVERS}
    given = folder()
    (given / "chatgpt" / SEED).write_text("24680")
    first, error = len(launches), None
    try:
        p = chatgpt.ChatGPTProvider(media(), given)
        p._ensure_page()
        p.stop()
    except Exception as exc:
        error = "{}: {}".format(type(exc).__name__, str(exc).strip().split("\n")[0][:90])
    used = [seeds(launch) for launch in launches[first:]]
    record("the seed is drawn once and each provider has its own",
           error is None and all(seed and seed.isdigit() and 10000 <= int(seed) <= 99999 for seed in own.values())
           and used == [["24680"]] and kept_seed(given, "chatgpt") == "24680",
           "a seed in each profile {}; a seed written before the first launch: used {}, kept {}{}".format(
               own, used, kept_seed(given, "chatgpt"), ", " + error if error else ""))

    child, ready = hold(sessions, base + "/learn")
    end(child, sessions)
    names, error = [], None
    try:
        p = chatgpt.ChatGPTProvider(media(), sessions)
        page = p._ensure_page()
        page.goto(base + "/", wait_until="domcontentloaded", timeout=20000)
        names = sorted(c["name"] for c in p._context.cookies(base))
        p.stop()
    except Exception as exc:
        error = "{}: {}".format(type(exc).__name__, str(exc).strip().split("\n")[0][:90])
    record("what a browser learned outlives a killed worker", ready and "learned" in names,
           "the killed worker's browser had the page {}; cookies at the next open {}{}".format(
               ready, names, ", " + error if error else ""))

    child, ready = hold(sessions, base + "/")
    refused, opened = None, False
    p = chatgpt.ChatGPTProvider(media(), sessions)
    try:
        p._ensure_page()
        opened = True
    except Exception as exc:
        refused = exc
    finally:
        p.stop()
        end(child, sessions)
    words = str(refused or "")
    record("a second browser on an open session is refused in words",
           ready and not opened and isinstance(refused, ProviderError) and "chatgpt" in words
           and "another browser" in words,
           "the first had the session {}; the second {}".format(
               ready, "opened" if opened else "{}: {}".format(type(refused).__name__, words[:110])))

    bare = folder(profiles=False)
    said = {}
    for name, cls in DRIVERS:
        try:
            cls(media(), bare).start()
            said[name] = "started"
        except Exception as exc:
            said[name] = str(exc)
    record("a provider with no profile says so at start, an old state file notwithstanding",
           all("scripts/login_provider.py {}".format(name) in said[name] for name, _ in DRIVERS),
           str({name: words[-48:] for name, words in said.items()}))

    p = chatgpt.ChatGPTProvider(media(), sessions)
    error = None
    try:
        p._ensure_page()
    except Exception as exc:
        error = "{}: {}".format(type(exc).__name__, str(exc).strip().split("\n")[0][:90])
    p.stop()
    child, ready = hold(sessions, base + "/")
    end(child, sessions)
    record("stop leaves the session free for the next opener", error is None and ready,
           "after stop another process had the session {}{}".format(ready, ", " + error if error else ""))

    server.shutdown()
    passed = sum(1 for ok in results if ok)
    print("{}/{} PASSED".format(passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
