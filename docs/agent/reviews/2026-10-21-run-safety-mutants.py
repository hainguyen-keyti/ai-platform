#!/usr/bin/env python3
"""Mutants of the safety plan (2026-10-21), each on a copy of api/, worker/, tests/, scripts/ and
acceptance.py outside the repo, against the suite that should catch it. Prints RED or SURVIVED.

    python3 /tmp/run_safety_mutants.py [M1 M2 ...]
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path("/Users/keyti/Sources/RE/chatgpt")
PY = str(Path.home() / "cloakbrowser-env/bin/python")
GROK, CHATGPT, POOL, JOBS = ("worker/src/providers/grok.py", "worker/src/providers/chatgpt.py",
                             "worker/src/pool.py", "api/src/jobs.py")
SETTLE, COMPOSER, DEAD, GATE = ("tests/test_grok_settle.py", "tests/test_chatgpt_composer.py",
                                "tests/test_pool_dead_browser.py", "acceptance.py")

MUTANTS = [
    ("M1 grok: the empty set back on a failed read", GROK, [(
        '        raise ProviderError("grok\'s thread could not be read before sending ({}), so nothing was "\n'
        '                            "sent".format(status))\n', "        return set()\n")], SETTLE,
     ["first answers 429", "first answers 500", "stays unreadable"]),
    ("M2 grok: no retry", GROK, [("BASELINE_TRIES = 3\n", "BASELINE_TRIES = 1\n")], SETTLE,
     ["first answers 429", "first answers 500"]),
    ("M3 grok: an endless retry", GROK, [("BASELINE_TRIES = 3\n", "BASELINE_TRIES = 300\n")], SETTLE,
     ["stays unreadable"]),
    ("M4 grok: no stop check between tries", GROK, [(
        "                pause *= 2\n                self._check_stop()\n", "                pause *= 2\n")], SETTLE,
     ["taken away while its thread is read again"]),
    ("M5 grok: an empty 200 taken as a read", GROK, [(
        "            if ids:\n                return ids\n", "            return ids\n")], SETTLE, []),
    ("M6 api: the empty done charged", JOBS, [(
        '            if status == "done" and not (text or "").strip() and not media:\n'
        '                status, error_kind = "failed", "empty_reply"\n',
        '            if False:\n                status, error_kind = "failed", "empty_reply"\n')], GATE,
     ["a done result with nothing in it"]),
    ("M7 api: the stranded sweep out of get_job", JOBS, [(
        "            _sweep_stranded(conn)\n            _sweep_unserved(conn, job_id)\n",
        "            _sweep_unserved(conn, job_id)\n")], GATE, ["whose worker died"]),
    ("M8 pool: the closed target mapping removed", POOL, [(
        "                if browser_gone(exc):\n                    # The page or browser died under the turn",
        "                if False:\n                    # The page or browser died under the turn")], DEAD,
     ["a closed target", "a plain Playwright error"]),
    ("M9 pool: the provider not stopped", POOL, [(
        "                        provider.stop()\n                    except Exception:\n                        pass\n"
        "                    return GenerationResult.failure(\n                        \"the {} browser closed under the turn",
        "                        pass\n                    except Exception:\n                        pass\n"
        "                    return GenerationResult.failure(\n                        \"the {} browser closed under the turn")], DEAD,
     ["a closed target"]),
    ("M10 chatgpt: the look for a leftover chip removed", CHATGPT, [(
        "        self._drop_attachments(page)\n", "")], COMPOSER, ["a chip a site keeps", "cannot be removed"]),
    ("M11 chatgpt: an unremovable chip sent anyway", CHATGPT, [(
        "        if left:\n            raise ProviderError(\"chatgpt's composer holds an attachment",
        "        if False:\n            raise ProviderError(\"chatgpt's composer holds an attachment")], COMPOSER,
     ["cannot be removed", "cannot be told apart"]),
    ("M12 grok: a read that raises escapes the retry", GROK, [(
        "            try:\n                status, raw = self._api(page, SERVER_TURNS.format(cid))\n            except Exception as exc:\n",
        "            try:\n                status, raw = self._api(page, SERVER_TURNS.format(cid))\n            except ZeroDivisionError as exc:\n")],
     SETTLE, ["raises on the way"]),
    ("M13 chatgpt: a preview with no readable remove control sent along", CHATGPT, [(
        "            left = removes.count() or previews.count()\n", "            left = removes.count()\n")], COMPOSER,
     ["cannot be told apart"]),
    ("M14 pool: the deletion path keeps a dead browser", POOL, [(
        "                if browser_gone(exc):\n                    # A browser that died while the runner was idle",
        "                if False:\n                    # A browser that died while the runner was idle")], DEAD,
     ["under a thread deletion"]),
    ("M16 chatgpt: the remove control clicked without a hover", CHATGPT, [(
        "                    (previews.first if previews.count() else removes.first).hover(timeout=3000)\n", "")], COMPOSER,
     ["a chip a site keeps", "left on a thread's page"]),
    ("M15 api: whitespace counted as words", JOBS, [(
        '            if status == "done" and not (text or "").strip() and not media:\n',
        '            if status == "done" and not text and not media:\n')], GATE, ["a done result with nothing in it"]),
]


def run(name, path, pairs, suite, wanted):
    work = Path(tempfile.mkdtemp(prefix="safety-mutant-"))
    for part in ("api", "worker", "tests", "scripts"):
        shutil.copytree(REPO / part, work / part, ignore=shutil.ignore_patterns("__pycache__", "node_modules"))
    shutil.copy(REPO / "acceptance.py", work / "acceptance.py")
    target = work / path
    text = target.read_text()
    for old, new in pairs:
        if text.count(old) != 1:
            shutil.rmtree(work, ignore_errors=True)
            return "{}: NOT APPLIED (found {} times: {!r})".format(name, text.count(old), old[:60])
        text = text.replace(old, new)
    target.write_text(text)
    command = [sys.executable, str(work / "acceptance.py")] if suite == GATE else [PY, str(work / suite)]
    try:
        ran = subprocess.run(command, capture_output=True, text=True, timeout=900, cwd=str(work))
        out = ran.stdout + ran.stderr
    except subprocess.TimeoutExpired:
        return "{}: RED (hung, killed after 900s)".format(name)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    failed = [line[7:].split("  ")[0] for line in out.splitlines() if line.startswith("[FAIL]")]
    summary = next((l for l in reversed(out.splitlines()) if l.endswith("PASSED")), "?")
    missing = [w for w in wanted if not any(w in f for f in failed)]
    verdict = "RED" if failed and not missing else ("RED, but not all named checks" if failed else "SURVIVED")
    return "{}: {} ({}; red: {}{})".format(name, verdict, summary, [f[:55] for f in failed],
                                            "; expected red but green: {}".format(missing) if missing else "")


for m in MUTANTS:
    if len(sys.argv) > 1 and not any(m[0].startswith(a + " ") for a in sys.argv[1:]):
        continue
    print(run(*m), flush=True)
