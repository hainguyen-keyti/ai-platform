#!/bin/sh
# Runs the browser worker on the host, where cloakbrowser is installed.
# The API runs in Docker; the worker reaches it over the published port.
set -e

cd "$(dirname "$0")/.."

VENV="${CLOAKBROWSER_VENV:-$HOME/cloakbrowser-env}"
if [ ! -x "$VENV/bin/python" ]; then
  echo "cloakbrowser venv not found at $VENV" >&2
  echo "set CLOAKBROWSER_VENV to its path, or install cloakbrowser there" >&2
  exit 1
fi

# Every line .env sets reaches the worker (set -a exports it: PROVIDERS and the pacing are read by
# the worker, not by this script), and every name the command line or the calling shell exported
# wins over the file, an empty one too (`PROVIDER_MODE= ./scripts/run-worker.sh` falls to the
# default below, real): `export -p` prints them quoted for the shell to read back, and they are
# read back once the file is in.
if [ -f .env ]; then
  _given=$(export -p)
  set -a
  . ./.env
  set +a
  eval "$_given"
  unset _given
fi

"$VENV/bin/pip" install --quiet --disable-pip-version-check -r worker/requirements.txt

export API_URL="${API_URL:-http://localhost:3000}"
export WORKER_TOKEN="${WORKER_TOKEN:?set WORKER_TOKEN in .env}"
export PROVIDER_MODE="${PROVIDER_MODE:-real}"
export MEDIA_PATH="${WORKER_MEDIA_PATH:-$(pwd)/storage/media}"
export SESSIONS_PATH="${SESSIONS_PATH:-$(pwd)/storage/sessions}"
export PYTHONPATH="$(pwd)/worker"

mkdir -p "$MEDIA_PATH" "$SESSIONS_PATH"

echo "worker: provider mode $PROVIDER_MODE, api $API_URL, media $MEDIA_PATH"
exec "$VENV/bin/python" -m uvicorn src.main:app --host 127.0.0.1 --port "${WORKER_PORT:-8000}"
