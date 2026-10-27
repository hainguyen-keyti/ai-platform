#!/bin/sh
# The full gate in one command (CLAUDE.md): the quick gate, the web build, then ui_smoke against
# the running stack and a mock worker. Brings the compose stack up, and starts a mock worker with
# MOCK_DELAY_SECONDS=4 when nothing answers on the worker port; stops only a worker it started.
# A worker already on that port is used only if its health says mock mode, since ui_smoke must
# never drive a real account; its delay cannot be read from health, and one started without
# MOCK_DELAY_SECONDS=4 fails ui_smoke's typing check. Exits non-zero on the first red step.
set -eu

cd "$(dirname "$0")/.."

VENV="${CLOAKBROWSER_VENV:-$HOME/cloakbrowser-env}"
PY="$VENV/bin/python"
WORKER_PORT="${WORKER_PORT:-8000}"
LOG_DIR="${FULL_GATE_LOG_DIR:-$HOME/.cache/ai-platform}"
mkdir -p "$LOG_DIR"

[ -x "$PY" ] || { echo "full-gate: cloakbrowser venv not found at $VENV" >&2; exit 1; }
[ -f .env ] || { echo "full-gate: .env missing (copy .env.example and set its secrets)" >&2; exit 1; }

echo "== quick gate"
"$PY" acceptance.py

echo "== web build"
(cd web && npm run build)

echo "== stack"
docker compose up -d
for _ in $(seq 1 60); do
  curl -s -m 2 http://localhost:3000/health >/dev/null && curl -s -m 2 -o /dev/null http://localhost:5173/ && break
  sleep 2
done
curl -s -m 2 http://localhost:3000/health >/dev/null || { echo "full-gate: api does not answer on :3000" >&2; exit 1; }
curl -s -m 2 -o /dev/null http://localhost:5173/ || { echo "full-gate: web does not answer on :5173" >&2; exit 1; }

worker_mode() {
  curl -s -m 2 "http://127.0.0.1:$WORKER_PORT/health" | "$PY" -c 'import json, sys; print(json.load(sys.stdin).get("mode", ""))' 2>/dev/null || true
}

started=""
cleanup() {
  if [ -n "$started" ]; then
    kill "$started" 2>/dev/null || true
    wait "$started" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "== mock worker"
mode=$(worker_mode)
if [ -z "$mode" ]; then
  PROVIDER_MODE=mock MOCK_DELAY_SECONDS=4 PYTHONUNBUFFERED=1 ./scripts/run-worker.sh > "$LOG_DIR/full-gate-worker.log" 2>&1 &
  started=$!
  for _ in $(seq 1 60); do
    mode=$(worker_mode)
    [ -n "$mode" ] && break
    sleep 2
  done
fi
[ "$mode" = "mock" ] || { echo "full-gate: the worker on :$WORKER_PORT is in mode '${mode:-none}', not mock" >&2; exit 1; }
sleep 5  # its first claim makes the api count chatgpt as served

echo "== ui smoke"
INVITE_CODE=$(sed -n 's/^INVITE_CODE=//p' .env | tail -n 1)
export INVITE_CODE
"$PY" tests/ui_smoke.py
