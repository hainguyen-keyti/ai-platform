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

# Anything set on the command line must survive .env being sourced.
_cli_api_url=${API_URL-}
_cli_worker_token=${WORKER_TOKEN-}
_cli_provider_mode=${PROVIDER_MODE-}

if [ -f .env ]; then
  . ./.env
fi

[ -n "$_cli_api_url" ] && API_URL=$_cli_api_url
[ -n "$_cli_worker_token" ] && WORKER_TOKEN=$_cli_worker_token
[ -n "$_cli_provider_mode" ] && PROVIDER_MODE=$_cli_provider_mode

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
