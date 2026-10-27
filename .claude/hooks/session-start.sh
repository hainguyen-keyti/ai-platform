#!/bin/sh
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
[ -d docs/agent ] || exit 0
mkdir -p .claude && touch .claude/session-start
stamp="kt-skeleton 1.3.0 (the kt version whose skeleton these hooks match; /kt:load compares it with the stamp in the installed kt)"
src=""
[ -t 0 ] || src="$(cat | python3 -c 'import sys, json
try:
    print(json.load(sys.stdin).get("source", ""))
except Exception:
    print("")' 2>/dev/null)"
if [ "$src" = "resume" ]; then
  echo "$stamp; resumed session: the docs/agent block from when it opened still holds, continue the task in progress."
  exit 0
fi
echo "=== docs/agent bootstrap (injected by the SessionStart hook) ==="
echo "$stamp"
case "$src" in
  compact|fork) echo "The conversation was compacted or forked: the sections below still bind; continue the task in progress, no restatement or wait needed." ;;
  *) echo "Before doing anything else: restate to the user, in one short paragraph, the project stage and its consequences, the open decisions, and the next step, based on the sections below. Do not start coding until the user confirms." ;;
esac
echo "Respect the stage consequences absolutely. Items under '4. Open decisions' in DECISIONS.md must not be re-decided or re-proposed. The rest of the ledger is in docs/agent/: /kt:load or a Read when a task needs it."
python3 - <<'PY'
CAP = 2900
for path, needle in (("docs/agent/PROJECT.md", "current stage"), ("docs/agent/DECISIONS.md", "open decisions"), ("docs/agent/HANDOFF.md", "next steps")):
    try:
        lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    except OSError:
        continue
    out, on = [], False
    for line in lines:
        if line.startswith("## "):
            if on:
                break
            on = needle in line.lower()
        if on:
            out.append(line)
    kept, size = [], 0
    for line in out:
        if size + len(line) + 1 > CAP:
            kept.append("[cut to stay under the hook output limit: Read " + path + " for the rest of this section]")
            break
        kept.append(line)
        size += len(line) + 1
    if kept:
        print("\n--- " + path + " ---\n" + "\n".join(kept))
PY
exit 0
