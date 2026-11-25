#!/bin/sh
# Makes scripts/stall-watch.py a systemd user service (issue #41): it keeps a per-second record of the
# machine around any stall of the api, in storage/diagnostics/stall-watch/. Standard library only, so the
# system python3 runs it. Needs systemd in WSL (`systemd=true` in /etc/wsl.conf).
#   ./scripts/install-stall-watch.sh
# Afterwards: systemctl --user status|stop|start aip-stall-watch
set -e

cd "$(dirname "$0")/.."
REPO=$(pwd)
LOG="$HOME/.cache/ai-platform/stall-watch.log"
UNIT_DIR="$HOME/.config/systemd/user"

mkdir -p "$UNIT_DIR" "$(dirname "$LOG")"
cat > "$UNIT_DIR/aip-stall-watch.service" <<EOF
[Unit]
Description=AI Platform stall recorder (issue #41)
RequiresMountsFor=$REPO

[Service]
WorkingDirectory=$REPO
ExecStart=/usr/bin/python3 $REPO/scripts/stall-watch.py
Nice=10
Restart=always
RestartSec=30
StandardOutput=append:$LOG
StandardError=append:$LOG

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now aip-stall-watch
echo "installed and started; see: systemctl --user status aip-stall-watch"
