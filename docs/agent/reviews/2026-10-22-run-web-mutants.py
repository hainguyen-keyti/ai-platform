#!/usr/bin/env python3
"""The web plan (2026-10-22): ui_smoke against a copy of web/ served by the host's vite on 5174, as it
stands ("plain") or with one mutant applied, so the repo's own web can be edited meanwhile. Needs the
stack up, the host worker in mock mode with MOCK_DELAY_SECONDS=4, and INVITE_CODE in the environment.

    set -a; . ./.env; set +a; python3 docs/agent/reviews/2026-10-22-run-web-mutants.py plain
    set -a; . ./.env; set +a; python3 docs/agent/reviews/2026-10-22-run-web-mutants.py W1 W2 ...

Prints the count line for plain, RED or SURVIVED per mutant (RED when every check it names fails).
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path("/Users/keyti/Sources/RE/chatgpt")
PY = str(Path.home() / "cloakbrowser-env/bin/python")
PORT = 5174
APP, CHAT, GALLERY, API, STRINGS, BUBBLE = ("src/App.jsx", "src/pages/Chat.jsx", "src/pages/Gallery.jsx",
                                            "src/lib/api.js", "src/lib/strings.jsx",
                                            "src/components/TypingBubble.jsx")

# name, file under web/, [(old, new)], the checks that must fail
MUTANTS = [
    ("W1 the chat unmounted again outside its view", APP, [
        ("          <Chat chatTaps={chatTaps} visible={view === 'chat'}\n",
         "          {view === 'chat' && <Chat chatTaps={chatTaps} visible={view === 'chat'}\n"),
        ("            onQuotaSpent={() => api.me().then(setUser).catch(() => {})} />\n",
         "            onQuotaSpent={() => api.me().then(setUser).catch(() => {})} />}\n")],
     ["leaving the chat for the gallery mid-job"]),
    ("W2 the open-conversation guard removed", CHAT, [
        ("    if (activeIdRef.current !== id) return\n    const n = ++reads.current\n",
         "    const n = ++reads.current\n")],
     ["a job finishing while another conversation is open"]),
    ("W3 the read counter ignored", CHAT, [
        ("    if (n === reads.current) setConversation(fresh)\n", "    setConversation(fresh)\n")],
     ["a slow load of one conversation", "a read of the open conversation answered after its reply landed"]),
    ("W4 the 401 handler not called", API, [("    if (onUnauthorized) onUnauthorized()\n", "")],
     ["a call refused with 401"]),
    ("W5 sign out without logout", APP, [("    api.logout().catch(() => {})\n", "")],
     ["sign out revokes the session"]),
    ("W6 the gallery confirm removed", GALLERY, [("    if (!window.confirm(t.confirmDeleteMedia)) return\n", "")],
     ["a gallery delete asks first"]),
    ("W7 the offset ignored", API, [("offset=${offset}", "offset=0")],
     ["a gallery of 137"]),
    ("W8 the error mapping removed", CHAT, [
        ("{failureText(shownError, t)}</span>", "{shownError.message}</span>")],
     ["in Vietnamese the phase"]),
    ("W9 the providers not asked again when shown", CHAT, [("  }, [shownAgain])\n", "  }, [])\n")],
     ["the selector greys out a provider no worker serves"]),
    ("W10 the bubble under whatever is on screen", CHAT, [
        ("  const bubbleHere = jobHere && (!conversation || conversation.id === activeId)\n",
         "  const bubbleHere = jobHere\n")],
     ["with its bubble only under it"]),
]


def copy_web(into):
    for part in ("src", "index.html", "package.json", "vite.config.js", "postcss.config.js", "tailwind.config.js"):
        source = REPO / "web" / part
        if source.is_dir():
            shutil.copytree(source, into / part)
        else:
            shutil.copy2(source, into / part)
    (into / "node_modules").symlink_to(REPO / "web" / "node_modules")


def serve(root):
    env = dict(os.environ, VITE_API_URL="http://localhost:3000")
    vite = subprocess.Popen([str(root / "node_modules/.bin/vite"), "--port", str(PORT), "--strictPort"],
                            cwd=root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    for _ in range(60):
        try:
            urllib.request.urlopen("http://localhost:{}/".format(PORT), timeout=2)
            return vite
        except Exception:
            time.sleep(1)
    vite.kill()
    raise SystemExit("vite on {} never answered".format(PORT))


def smoke(label):
    env = dict(os.environ, WEB_URL="http://localhost:{}".format(PORT), SHOT_DIR="/tmp/ui_shots_{}".format(label))
    done = subprocess.run([PY, str(REPO / "tests/ui_smoke.py")], cwd=REPO, env=env,
                          capture_output=True, text=True, timeout=1800)
    return done.stdout + done.stderr


def run(label, edits=()):
    with tempfile.TemporaryDirectory(prefix="web-{}-".format(label.split()[0])) as tmp:
        root = Path(tmp)
        copy_web(root)
        for rel, old, new in edits:
            path = root / rel
            text = path.read_text()
            if text.count(old) != 1:
                raise SystemExit("{}: the mutant's text is found {} times in {}".format(label, text.count(old), rel))
            path.write_text(text.replace(old, new))
        vite = serve(root)
        try:
            return smoke(label.split()[0])
        finally:
            vite.terminate()
            vite.wait(timeout=20)


def main(names):
    if not os.environ.get("INVITE_CODE"):
        raise SystemExit("INVITE_CODE is not set")
    if names == ["plain"]:
        out = run("plain")
        Path("/tmp/web-plain-run.txt").write_text(out)
        print("\n".join(l for l in out.splitlines() if l.startswith("[FAIL]") or "PASSED" in l))
        return
    for name, rel, swaps, checks in MUTANTS:
        if names and name.split()[0] not in names:
            continue
        out = run(name, [(rel, old, new) for old, new in swaps])
        Path("/tmp/web-mutant-{}.txt".format(name.split()[0])).write_text(out)
        lines = out.splitlines()
        failed = [c for c in checks if any(l.startswith("[FAIL]") and c in l for l in lines)]
        count = next((l for l in lines if "PASSED" in l), "no count line")
        verdict = "RED" if checks and len(failed) == len(checks) else "SURVIVED"
        print("{}: {} ({}; failing {}/{} of its checks)".format(name, verdict, count, len(failed), len(checks)),
              flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
