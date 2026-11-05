#!/bin/sh
# Keeps the stack up by itself: a systemd user timer in WSL runs scripts/ensure-stack.sh a minute after WSL
# starts and every 3 minutes after, so the api and the web come back after Windows, WSL or Docker restarts.
# Needs systemd in WSL (`systemd=true` in /etc/wsl.conf). On Windows, also run
# scripts/windows/install-autostart.ps1, which starts Docker Desktop and WSL themselves.
#   ./scripts/install-autostart.sh
# Afterwards: systemctl --user list-timers aip-stack; log in ~/.cache/ai-platform/ensure-stack.log
set -e

cd "$(dirname "$0")/.."
REPO=$(pwd)
UNIT_DIR="$HOME/.config/systemd/user"

mkdir -p "$UNIT_DIR"
cat > "$UNIT_DIR/aip-stack.service" <<EOF
[Unit]
Description=AI Platform: bring the stack back if it is down
RequiresMountsFor=$REPO

[Service]
Type=oneshot
WorkingDirectory=$REPO
ExecStart=/bin/sh $REPO/scripts/ensure-stack.sh
TimeoutStartSec=600
EOF

cat > "$UNIT_DIR/aip-stack.timer" <<EOF
[Unit]
Description=AI Platform: check the stack every 3 minutes

[Timer]
OnBootSec=60
OnUnitInactiveSec=180
Persistent=false

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now aip-stack.timer
# Without lingering the user's services stop with the last login, and WSL with them.
loginctl enable-linger "$(id -un)"
echo "installed; see: systemctl --user list-timers aip-stack"
