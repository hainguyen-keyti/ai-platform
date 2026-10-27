#!/usr/bin/env python3
"""Stop gate, two machine checks, no self-report trusted.
1. Any stop: a commit made in this session (newer than .claude/session-start) that is newer than
   docs/agent/HANDOFF.md blocks, so a silent session cannot leave the ledger behind. HANDOFF counts
   as fresh at max(mtime, time of the last commit touching it), which keeps tracked ledgers honest.
2. A handoff (last assistant message carries the REPORT block): HANDOFF.md must also be newer than
   the session stamp and, with an active plan, the kt fence audit must pass.
Everything else passes through."""
import json
import os
import subprocess
import sys


def git_time(*args):
    try:
        proc = subprocess.run(["git", "log", "-1", "--format=%ct", *args], capture_output=True, text=True)
        return int(proc.stdout.strip()) if proc.returncode == 0 and proc.stdout.strip() else 0
    except Exception:
        return 0


def stale_after_commit(stamp, handoff):
    if not os.path.isfile(stamp) or not os.path.isfile(handoff):
        return False
    head = git_time()
    if not head or head <= os.path.getmtime(stamp):
        return False
    return max(os.path.getmtime(handoff), git_time("--", handoff)) < head


def last_assistant_text(path):
    last = ""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if obj.get("type") != "assistant":
                    continue
                content = (obj.get("message") or {}).get("content") or []
                text = "".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
                if text.strip():
                    last = text
    except OSError:
        return ""
    return last


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    if payload.get("stop_hook_active"):
        return 0
    os.chdir(os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or ".")
    if not os.path.isdir("docs/agent"):
        return 0
    problems = []
    stamp = os.path.join(".claude", "session-start")
    handoff = os.path.join("docs", "agent", "HANDOFF.md")
    if stale_after_commit(stamp, handoff):
        problems.append("docs/agent/HANDOFF.md is older than a commit made in this session: update it (current state with the HEAD sha, next step, plan progress) before stopping.")
    if "## REPORT" in last_assistant_text(payload.get("transcript_path") or ""):
        if os.path.isfile(stamp) and os.path.isfile(handoff) and os.path.getmtime(handoff) < os.path.getmtime(stamp):
            problems.append("docs/agent/HANDOFF.md is older than this session's start: update it (what was done, durable decisions mirrored into DECISIONS.md, current state, next step, known traps, plan progress) before handing off.")
        if os.path.isfile(os.path.join(".claude", "active-plan")):
            try:
                reg = json.load(open(os.path.expanduser("~/.claude/plugins/installed_plugins.json"), encoding="utf-8"))
                kt = reg["plugins"]["kt@kt"][0]["installPath"]
                audit = subprocess.run([sys.executable, os.path.join(kt, "hooks", "no-offplan-edit.py"), "--audit"], capture_output=True, text=True)
                if audit.returncode != 0:
                    problems.append("plan fence audit failed, fix or report each file in UNSURE before handing off:\n" + audit.stdout.strip())
            except Exception as exc:
                problems.append("plan fence audit could not run (" + type(exc).__name__ + "); run it by hand and report the output.")
    if problems:
        sys.stderr.write("STOP GATE (docs/agent): " + "\n".join(problems) + "\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
