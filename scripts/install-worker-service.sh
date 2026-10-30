#!/bin/sh
# Makes the real worker a systemd user service, so it does not live and die with a terminal tab: it comes
# back when it crashes and when WSL starts. Needs systemd in WSL (`systemd=true` in /etc/wsl.conf).
#   ./scripts/install-worker-service.sh [port] [providers]      defaults: 8000, PROVIDERS from .env
# Afterwards: systemctl --user status|stop|start|restart aip-worker
set -e

cd "$(dirname "$0")/.."
REPO=$(pwd)
PORT="${1:-8000}"
PROVIDERS_LINE=""
[ -n "${2:-}" ] && PROVIDERS_LINE="Environment=PROVIDERS=$2"
LOG="$HOME/.cache/ai-platform/host-worker-real.log"
UNIT_DIR="$HOME/.config/systemd/user"

mkdir -p "$UNIT_DIR" "$(dirname "$LOG")"
cat > "$UNIT_DIR/aip-worker.service" <<EOF
[Unit]
Description=AI Platform real worker
RequiresMountsFor=$REPO

[Service]
WorkingDirectory=$REPO
Environment=WORKER_PORT=$PORT
Environment=PYTHONUNBUFFERED=1
$PROVIDERS_LINE
ExecStart=/bin/sh $REPO/scripts/run-worker.sh
Restart=always
RestartSec=30
TimeoutStopSec=30
StandardOutput=append:$LOG
StandardError=append:$LOG

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable aip-worker
# Without lingering the user's services stop with the last login, and WSL with them.
loginctl enable-linger "$(id -un)"
echo "installed; start it with: systemctl --user start aip-worker"
