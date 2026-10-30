#!/bin/sh
# The full gate in one command (CLAUDE.md): the quick gate, the web build, then ui_smoke against a
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
for _ in $(seq 1 60); do
  curl -s -m 2 "http://localhost:$GATE_API_PORT/health" >/dev/null \
    && curl -s -m 2 -o /dev/null "http://localhost:$GATE_WEB_PORT/" && break
  sleep 2
done
curl -s -m 2 "http://localhost:$GATE_API_PORT/health" >/dev/null \
  || { echo "full-gate: the gate's api does not answer on :$GATE_API_PORT" >&2; exit 1; }
curl -s -m 2 -o /dev/null "http://localhost:$GATE_WEB_PORT/" \
  || { echo "full-gate: the gate's web does not answer on :$GATE_WEB_PORT" >&2; exit 1; }

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
