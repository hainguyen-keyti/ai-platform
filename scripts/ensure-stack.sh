#!/bin/sh
# Brings the stack back after Windows, WSL or Docker restarts, and does nothing while it is up: safe to run
# every few minutes (scripts/install-autostart.sh runs it on a systemd timer). It waits for Docker, starts the
# compose stack, recreates the api and web only if the api still does not answer (Docker can start a container
# before WSL has mounted the project's drive, and the api's bind mount is then empty), and starts the worker
# service if it is installed and stopped. It never restarts a worker that is running.
#   ./scripts/ensure-stack.sh            the real stack
#   COMPOSE_PROJECT=aip-gate API_PORT=3100 WEB_PORT=5273 STORAGE_DIR=... ./scripts/ensure-stack.sh
set -u

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
API_PORT="${API_PORT:-3000}"
WAIT_DOCKER_SECONDS="${WAIT_DOCKER_SECONDS:-300}"
LOG="${ENSURE_STACK_LOG:-$HOME/.cache/ai-platform/ensure-stack.log}"
mkdir -p "$(dirname "$LOG")"

say() {
  echo "$(date -u '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"
}

compose() {
  if [ -n "${COMPOSE_PROJECT:-}" ]; then
    docker compose -p "$COMPOSE_PROJECT" "$@"
  else
    docker compose "$@"
  fi
}

api_up() {
  curl -s -m 5 "http://127.0.0.1:$API_PORT/health" 2>/dev/null | grep -q '"ok"'
}

wait_api() {
  for _ in $(seq 1 "$1"); do
    api_up && return 0
    sleep 3
  done
  return 1
}

# Docker Desktop takes minutes to come up after WSL starts (measured 2026-11-05: about 3 minutes), and its
# `docker` command only appears in this distro once it is up.
waited=0
until command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; do
  if [ "$waited" -ge "$WAIT_DOCKER_SECONDS" ]; then
    say "docker did not answer within ${WAIT_DOCKER_SECONDS}s; is Docker Desktop running?"
    exit 1
  fi
  sleep 5
  waited=$((waited + 5))
done

if api_up; then
  status=0
else
  say "api on :$API_PORT does not answer; starting the stack"
  compose up -d >> "$LOG" 2>&1
  cd "$ROOT"
  if wait_api 20; then
    say "api back after compose up"
    status=0
  else
    say "api still down; recreating api and web (an empty bind mount after a restart looks like this)"
    compose logs --tail 5 api >> "$LOG" 2>&1
    compose up -d --force-recreate api web >> "$LOG" 2>&1
    cd "$ROOT"
    if wait_api 40; then
      say "api back after recreate"
      status=0
    else
      say "api still down after recreate; read: docker compose logs api"
      status=1
    fi
  fi
fi

# Only the real stack's worker: the gate's own worker is not a service.
if [ -z "${COMPOSE_PROJECT:-}" ] && systemctl --user cat aip-worker >/dev/null 2>&1; then
  if ! systemctl --user is-active --quiet aip-worker; then
    say "worker service not running; starting it"
    systemctl --user start aip-worker >> "$LOG" 2>&1 || status=1
  fi
fi

exit "$status"
