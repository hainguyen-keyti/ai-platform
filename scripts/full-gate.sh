#!/bin/sh
# The full gate in one command: the quick gate, the web build, then ui_smoke against a
# compose stack and a mock worker OF ITS OWN. The gate's stack is a second compose project
# (`aip-gate`) on GATE_API_PORT and GATE_WEB_PORT, with its database and media in storage/gate/,
# emptied at each run; its mock worker (MOCK_DELAY_SECONDS=4, which ui_smoke's typing check needs)
# serves that api only, on WORKER_PORT. The real stack, its database and a real worker serving it
# are never touched, so the gate can run while people use the platform: on 2026-10-30 the old gate,
# which brought up the real stack and a mock worker on it, answered a real /v1 request with a mock
# picture, and left mock threads tombstoned for the real worker (#25). Exits non-zero on the first
# red step; takes its stack down and stops its worker on exit.
set -eu

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

VENV="${CLOAKBROWSER_VENV:-$HOME/cloakbrowser-env}"
PY="$VENV/bin/python"
GATE_API_PORT="${GATE_API_PORT:-3100}"
GATE_WEB_PORT="${GATE_WEB_PORT:-5273}"
WORKER_PORT="${WORKER_PORT:-8100}"
GATE_STORAGE="$(pwd)/storage/gate"
LOG_DIR="${FULL_GATE_LOG_DIR:-$HOME/.cache/ai-platform}"
mkdir -p "$LOG_DIR"

[ -x "$PY" ] || { echo "full-gate: cloakbrowser venv not found at $VENV" >&2; exit 1; }
[ -f .env ] || { echo "full-gate: .env missing (copy .env.example and set its secrets)" >&2; exit 1; }

gate_compose() {
  API_PORT="$GATE_API_PORT" WEB_PORT="$GATE_WEB_PORT" STORAGE_DIR="$GATE_STORAGE" \
    VITE_API_URL="http://localhost:$GATE_API_PORT" docker compose -p aip-gate "$@"
}

echo "== quick gate"
"$PY" acceptance.py

echo "== web build"
(cd web && npm run build)

started=""
cleanup() {
  if [ -n "$started" ]; then
    kill "$started" 2>/dev/null || true
    wait "$started" 2>/dev/null || true
  fi
  gate_compose down -v >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

echo "== the gate's own stack (api :$GATE_API_PORT, web :$GATE_WEB_PORT, $GATE_STORAGE)"
gate_compose down -v >/dev/null 2>&1 || true
rm -rf "$GATE_STORAGE"
mkdir -p "$GATE_STORAGE/db" "$GATE_STORAGE/media"
gate_compose up -d
# Measured 2026-10-30 in WSL with the repo on /mnt/d: after this `up`, a process started from this
# shell can no longer resolve its working directory (Python's os.getcwd() raises FileNotFoundError,
# and ui_smoke died at its first import), though relative reads still work; entering the folder
# again by its absolute path mends it.
cd "$ROOT"
# Five minutes: measured 2026-10-31, at a load of 13 the web was not up within two, and the gate went red for it.
up_at=$(date +%s)
api_up= web_up=
for _ in $(seq 1 150); do
  [ -n "$api_up" ] || { curl -s -m 5 "http://localhost:$GATE_API_PORT/health" >/dev/null && api_up=1; }
  [ -n "$web_up" ] || { curl -s -m 5 -o /dev/null "http://localhost:$GATE_WEB_PORT/" && web_up=1; }
  [ -n "$api_up" ] && [ -n "$web_up" ] && break
  sleep 2
done
# Asking again here with a short timeout went red on a loaded machine (2026-10-31, three times, the log of none kept).
if [ -z "$api_up" ] || [ -z "$web_up" ]; then
  echo "full-gate: after $(($(date +%s) - up_at))s the gate's api answered: ${api_up:-no}, its web on :$GATE_WEB_PORT: ${web_up:-no}" >&2
  gate_compose logs --tail 40 web api >&2 || true
  exit 1
fi
echo "the gate's stack answered after $(($(date +%s) - up_at))s"

worker_mode() {
  curl -s -m 2 "http://127.0.0.1:$WORKER_PORT/health" | "$PY" -c 'import json, sys; print(json.load(sys.stdin).get("mode", ""))' 2>/dev/null || true
}

echo "== mock worker (:$WORKER_PORT, serving the gate's api only)"
if curl -s -m 2 -o /dev/null "http://127.0.0.1:$WORKER_PORT/"; then
  echo "full-gate: something already answers on :$WORKER_PORT; set WORKER_PORT to a free port" >&2
  exit 1
fi
API_URL="http://localhost:$GATE_API_PORT" WORKER_MEDIA_PATH="$GATE_STORAGE/media" WORKER_PORT="$WORKER_PORT" \
  PROVIDER_MODE=mock MOCK_DELAY_SECONDS=4 PYTHONUNBUFFERED=1 \
  ./scripts/run-worker.sh > "$LOG_DIR/full-gate-worker.log" 2>&1 &
started=$!
mode=""
for _ in $(seq 1 60); do
  mode=$(worker_mode)
  [ -n "$mode" ] && break
  sleep 2
done
[ "$mode" = "mock" ] || { echo "full-gate: the gate's worker on :$WORKER_PORT is in mode '${mode:-none}', not mock" >&2; exit 1; }
sleep 5  # its first claim makes the gate's api count chatgpt as served

echo "== ui smoke"
INVITE_CODE=$(sed -n 's/^INVITE_CODE=//p' .env | tail -n 1)
export INVITE_CODE
WEB_URL="http://localhost:$GATE_WEB_PORT" API_URL="http://localhost:$GATE_API_PORT" "$PY" tests/ui_smoke.py
