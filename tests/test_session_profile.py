#!/usr/bin/env python3
"""A provider's session is one browser profile and one device. The real driver classes with a real
browser on a local page; no site, no account.

    ~/cloakbrowser-env/bin/python tests/test_session_profile.py

Measured 2026-10-01: every cloakbrowser launch draws a random device seed (three launches read the
GPU as M1, M4 Pro, M1), the drivers loaded a state file saved on the login day and never wrote it
back, and a Gemini login was signed out by Google after four such launches in 47 minutes. With one
profile directory and one seed a second launch reads the same device, keeps its cookies, and a
second browser on the same profile is refused by Chromium itself.
The sessions folder here is as this machine has it: each provider's old state file, a cookie still
in it, lies beside the profile its login made. Prints N/12 PASSED.
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

from src.providers import chatgpt, gemini, grok, session  # noqa: E402
from src.providers.base import ProviderError  # noqa: E402

DRIVERS = (("chatgpt", chatgpt.ChatGPTProvider), ("grok", grok.GrokProvider), ("gemini", gemini.GeminiProvider))
SEED = "device-seed"
OLD_STATE = json.dumps({"origins": [], "cookies": [{
    "name": "stale", "value": "1", "domain": "127.0.0.1", "path": "/", "expires": time.time() + 86400,
    "httpOnly": False, "secure": False, "sameSite": "Lax"}]})
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
base = None


def record(name, ok, detail):
    results.append(ok)
    print("[{}] {}  {}".format("PASS" if ok else "FAIL", name, detail), flush=True)


def check(name, body):
    """Run one check; a check that cannot even run is a failed check, said as such."""
    try:
        ok, detail = body()
    except Exception as exc:
        ok, detail = False, "could not run: {}: {}".format(type(exc).__name__, str(exc).strip().split("\n")[0][:110])
    record(name, ok, detail)


def recording(how, real):
    def launch(*args, **kwargs):
        where = kwargs.get("user_data_dir") or (args[0] if args else None)
        launches.append({"how": how, "args": list(kwargs.get("args") or []), "where": str(where or ""),
                         "headless": kwargs.get("headless")})
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


def media():
    return Path(tempfile.mkdtemp(prefix="session-profile-media-"))


def log_in(sessions, name):
    """The login script's way in: the profile made and opened, then closed. The GPU its page read."""
    context = session.open_session(sessions, name, create=True)
    try:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(base + "/", wait_until="domcontentloaded", timeout=20000)
        return page.evaluate(GPU)
    finally:
        context.close()


def folder(seeds=None, used=()):
    """A sessions folder: each provider's old state file, and a profile for each seed given (text,
    bytes, or None for no seed file). A used profile already holds what a browser left in it."""
    sessions = Path(tempfile.mkdtemp(prefix="session-profile-test-"))
    for name, _ in DRIVERS:
        (sessions / "{}.json".format(name)).write_text(OLD_STATE)
    for name, seed in (seeds or {}).items():
        (sessions / name).mkdir()
        if seed is not None:
            (sessions / name / SEED).write_bytes(seed if isinstance(seed, bytes) else seed.encode())
        if name in used:
            (sessions / name / "Local State").write_text("{}")
    return sessions


def raw_seed(sessions, name):
    try:
        return (sessions / name / SEED).read_bytes()
    except OSError:
        return None


def seeds(launch):
    return [arg.split("=", 1)[1] for arg in launch["args"] if arg.startswith("--fingerprint=")]


def kept_seed(sessions, name):
    try:
        return (sessions / name / SEED).read_text().strip()
    except OSError:
        return None


def model(gpu):
    return gpu.split("Renderer: ")[-1].split(",")[0]


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


def refusal(cls, sessions):
    """What a driver says when asked to open: (opened, the error or None, launches made)."""
    first, opened, refused = len(launches), False, None
    p = cls(media(), sessions)
    try:
        p._ensure_page()
        opened = True
    except Exception as exc:
        refused = exc
    finally:
        p.stop()
    return opened, refused, len(launches) - first


def same_device(name, cls, sessions, at_login):
    def body():
        first, gpus = len(launches), []
        for _ in range(3):
            p = cls(media(), sessions)
            page = p._ensure_page()
            page.goto(base + "/", wait_until="domcontentloaded", timeout=20000)
            gpus.append(page.evaluate(GPU))
            p.stop()
        mine = launches[first:]
        named = [seeds(launch) for launch in mine]
        kept = kept_seed(sessions, name)
        ok = (len(mine) == 3 and all(len(n) == 1 for n in named) and {n[0] for n in named} == {kept}
              and set(gpus) == {at_login} and all(launch["where"] == str(sessions / name) for launch in mine))
        return ok, "the login read {}; three launches named {} (kept {}), read {}, on profile {}".format(
            model(at_login), [n[0] if n else None for n in named], kept, [model(g) for g in gpus],
            sorted({launch["where"].rsplit("/", 1)[-1] or "none" for launch in mine}))
    check("{}: every launch is the device of its login".format(name), body)


def main():
    global base
    cloakbrowser.launch = recording("launch", cloakbrowser.launch)
    cloakbrowser.launch_persistent_context = recording("profile", cloakbrowser.launch_persistent_context)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Page)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:{}".format(server.server_address[1])

    sessions = folder()
    at_login = {}
    for name, cls in DRIVERS:
        try:
            at_login[name] = log_in(sessions, name)
        except Exception as exc:
            at_login[name] = "the login could not open: {}".format(str(exc)[:60])
        same_device(name, cls, sessions, at_login[name])

    def drawn_once():
        own = {name: kept_seed(sessions, name) for name, _ in DRIVERS}
        first = len(launches)
        again = log_in(sessions, "chatgpt")
        second = seeds(launches[first])
        fresh = []
        for _ in range(6):
            profile = Path(tempfile.mkdtemp(prefix="session-profile-draw-"))
            fresh.append(session.device_seed(profile, draw=True))
        given = folder({"chatgpt": "24680"})
        first = len(launches)
        p = chatgpt.ChatGPTProvider(media(), given)
        p._ensure_page()
        p.stop()
        used = [seeds(launch) for launch in launches[first:]]
        ok = (all(seed and seed.isdigit() and 10000 <= int(seed) <= 99999 for seed in own.values())
              and second == [own["chatgpt"]] and kept_seed(sessions, "chatgpt") == own["chatgpt"]
              and again == at_login["chatgpt"] and len(set(fresh)) > 1
              and used == [["24680"]] and kept_seed(given, "chatgpt") == "24680")
        return ok, ("a seed in each profile {}; a second login named {} and kept {}; six fresh draws {}; "
                    "a seed written before the first launch: used {}".format(
                        own, second, kept_seed(sessions, "chatgpt"), sorted(set(fresh)), used))
    check("the seed is drawn once, at the login, and a second login keeps the device", drawn_once)

    def lost_seed():
        def login(sessions_):
            first, opened, refused = len(launches), False, None
            try:
                session.open_session(sessions_, "chatgpt", create=True).close()
                opened = True
            except Exception as exc:
                refused = exc
            return opened, refused, len(launches) - first

        def driver(sessions_):
            return refusal(chatgpt.ChatGPTProvider, sessions_)

        cases = [(label, seed, driver, ()) for label, seed in (
            ("no seed file", None), ("empty", ""), ("words", "garbage"), ("negative", "-5"), ("zero", "0"),
            ("underscore", "2_4680"), ("thirty digits", "9" * 30), ("just under", "9999"), ("just over", "100000"),
            ("not text", b"\xff\xfe\x00\x01"), ("other digits", "12³45"), ("unreadable", "24680"))]
        cases += [("a login into a used profile with no seed", None, login, ("chatgpt",)),
                  ("a login onto a seed that is no seed", "garbage", login, ())]
        said = {}
        for label, seed, opener, used in cases:
            broken = folder({"chatgpt": seed}, used)
            if label == "unreadable":
                (broken / "chatgpt" / SEED).chmod(0)
            before = None if label == "unreadable" else raw_seed(broken, "chatgpt")
            opened, refused, made = opener(broken)
            after = None if label == "unreadable" else raw_seed(broken, "chatgpt")
            fine = (not opened and made == 0 and isinstance(refused, ProviderError)
                    and refused.kind == "provider_error"
                    and "scripts/login_provider.py chatgpt" in str(refused) and after == before)
            said[label] = "refused" if fine else "{}, {} launch(es), seed file {!r} then {!r}".format(
                "OPENED" if opened else "{} ({})".format(type(refused).__name__, getattr(refused, "kind", "no kind")),
                made, before, after)
        wrong = {label: what for label, what in said.items() if what != "refused"}
        return not wrong, "{} of {} refused{}".format(len(said) - len(wrong), len(said), ": " + str(wrong) if wrong else "")
    check("a profile whose seed is lost or unreadable is refused in words, not given a new device", lost_seed)

    def outlives():
        child, ready = hold(sessions, base + "/learn")
        end(child, sessions)
        p = chatgpt.ChatGPTProvider(media(), sessions)
        try:
            page = p._ensure_page()
            page.goto(base + "/", wait_until="domcontentloaded", timeout=20000)
            names = sorted(c["name"] for c in p._context.cookies(base))
        finally:
            p.stop()
        return ready and names == ["learned"], "the killed worker's browser had the page {}; cookies at the next open {}".format(
            ready, names)
    check("what a browser learned outlives a killed worker, and the old state file is not read", outlives)

    def second_refused():
        child, ready = hold(sessions, base + "/")
        try:
            opened, refused, _ = refusal(chatgpt.ChatGPTProvider, sessions)
        finally:
            end(child, sessions)
        words = str(refused or "")
        ok = (ready and not opened and isinstance(refused, ProviderError) and "chatgpt" in words
              and "another browser" in words and refused.kind == "provider_error")
        return ok, "the first had the session {}; the second {}".format(
            ready, "opened" if opened else "{} ({}): {}".format(
                type(refused).__name__, getattr(refused, "kind", "no kind"), words[:96]))
    check("a second browser on an open session is refused in words, as the provider's own error", second_refused)

    def start_says():
        def starts(folder_):
            out = {}
            for name, cls in DRIVERS:
                try:
                    cls(media(), folder_).start()
                    out[name] = "started"
                except Exception as exc:
                    out[name] = "refused" if "scripts/login_provider.py {}".format(name) in str(exc) else str(exc)[:40]
            return out
        names = [name for name, _ in DRIVERS]
        bare = starts(folder())
        empty = starts(folder({name: None for name in names}))
        seedless = starts(folder({name: None for name in names}, used=names))
        alone = {name: starts(folder({name: "24680"})) for name in names}
        ok = (set(bare.values()) == {"refused"} and set(empty.values()) == {"refused"}
              and set(seedless.values()) == {"refused"}
              and all(alone[name] == {other: "started" if other == name else "refused" for other in names}
                      for name in names))
        return ok, ("old state files only {}; empty directories {}; used profiles with no seed {}; each provider "
                    "logged in alone {}".format(bare, empty, seedless, alone))
    check("a provider whose login never made its profile says so at start", start_says)

    def stop_frees():
        p = chatgpt.ChatGPTProvider(media(), sessions)
        p._ensure_page()
        p.stop()
        child, ready = hold(sessions, base + "/")
        end(child, sessions)
        files = {f.name: f.read_text() == OLD_STATE for f in sorted(sessions.glob("*.json"))}
        ok = ready and files == {"{}.json".format(name): True for name, _ in sorted(DRIVERS)}
        return ok, "after stop another process had the session {}; state files untouched {}".format(ready, files)
    check("stop leaves the session free for the next opener, and no state file is written", stop_frees)

    def makes_none():
        bare, said = folder(), {}
        for name, cls in DRIVERS:
            opened, refused, made = refusal(cls, bare)
            fine = (not opened and made == 0 and isinstance(refused, ProviderError)
                    and refused.kind == "provider_error"
                    and "scripts/login_provider.py {}".format(name) in str(refused))
            said[name] = "refused" if fine else ("OPENED" if opened else "{} ({}): {}".format(
                type(refused).__name__, getattr(refused, "kind", "no kind"), str(refused)[:40]))
        left = sorted(f.name for f in bare.iterdir())
        return (set(said.values()) == {"refused"} and left == sorted("{}.json".format(name) for name, _ in DRIVERS),
                "{}; the folder holds {}".format(said, left))
    check("a driver does not make a profile that is not there", makes_none)

    def way_in():
        real, asked = cloakbrowser.launch_persistent_context, []

        def answer(outcome):
            def launcher(*args, **kwargs):
                asked.append(kwargs.get("headless"))
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome
            return launcher
        given, seen = folder({"chatgpt": "24680"}), {}
        try:
            cloakbrowser.launch_persistent_context = answer("a browser")
            seen["window"] = session.open_session(given, "chatgpt", headless=False)
            seen["default"] = session.open_session(given, "chatgpt")
            seen["edges"] = [session.open_session(folder({"chatgpt": edge}), "chatgpt")
                             for edge in ("10000", "99999", "24680\n")]
            first = Path(tempfile.mkdtemp(prefix="session-profile-first-")) / "no" / "sessions" / "yet"
            viewed = folder({"chatgpt": None})
            (viewed / "chatgpt" / ".DS_Store").write_text("left by the Finder")
            seen["logins"] = [session.open_session(where, "chatgpt", create=True) for where in (first, viewed)]
            seen["drawn"] = [kept_seed(where, "chatgpt") for where in (first, viewed)]
            for label, error in (("other", RuntimeError("the binary would not start")),
                                 ("held", RuntimeError("Failed to create a ProcessSingleton for your profile directory"))):
                cloakbrowser.launch_persistent_context = answer(error)
                try:
                    session.open_session(given, "chatgpt")
                    seen[label] = "opened"
                except Exception as exc:
                    seen[label] = "{}: {}".format(type(exc).__name__, str(exc)[:70])
        finally:
            cloakbrowser.launch_persistent_context = real
        ok = (asked[:2] == [False, True] and seen["edges"] == ["a browser"] * 3
              and seen["logins"] == ["a browser"] * 2 and all(seed and seed.isdigit() for seed in seen["drawn"])
              and seen["other"] == "RuntimeError: the binary would not start"
              and seen["held"].startswith("ProviderError: the chatgpt session is open in another browser"))
        return ok, ("asked for a window, then by default: headless {}; the smallest seed, the largest and one "
                    "ending in a newline open {}; a first login with no sessions folder and one into a "
                    "directory the Finder has looked at drew {}; another failure {!r}; a held profile {!r}".format(
                        asked[:2], len(seen.get("edges") or []), seen.get("drawn"), seen.get("other"), seen.get("held")))
    check("the way in opens with a window when asked, and a launch that fails says its own reason", way_in)

    def only_the_login_makes():
        sources = (list((ROOT / "worker" / "src").rglob("*.py")) + list((ROOT / "scripts").glob("*.py"))
                   + [ROOT / "tests" / name for name in ("gemini_probe.py", "grok_probe.py", "provider_probe.py")])
        asking = sorted(str(path.relative_to(ROOT)) for path in sources if "create=True" in path.read_text())
        return asking == ["scripts/login_provider.py"], "create=True is written in {}, of {} files read".format(
            asking, len(sources))
    check("only the login script asks for a profile to be made", only_the_login_makes)

    server.shutdown()
    passed = sum(1 for ok in results if ok)
    print("{}/{} PASSED".format(passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
