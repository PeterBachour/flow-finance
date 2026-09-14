#!/usr/bin/env bash
set -euo pipefail

FLOW_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$FLOW_DIR/.." && pwd)"
USER_NAME="${SUDO_USER:-$USER}"
GROUP_NAME="$(id -gn "$USER_NAME")"
MAINT_DIR="/var/lib/flow-finance-maintenance"
HELPER="$FLOW_DIR/maintenance/update_helper.py"
SERVICE="/etc/systemd/system/flow-finance-update.service"
AUDIT_SERVICE="/etc/systemd/system/flow-finance-audit.service"
AUDIT_TIMER="/etc/systemd/system/flow-finance-audit.timer"
DOCKER_BIN="$(command -v docker)"

if [[ ! -d "$REPO_ROOT/.git" ]]; then
  echo "Erreur: $REPO_ROOT n'est pas un dépôt Git." >&2
  exit 1
fi
if [[ ! -f "$FLOW_DIR/docker-compose.yml" || ! -f "$HELPER" ]]; then
  echo "Erreur: installation Flow incomplète dans $FLOW_DIR." >&2
  exit 1
fi
command -v python3 >/dev/null || { echo "Erreur: python3 introuvable." >&2; exit 1; }
command -v docker >/dev/null || { echo "Erreur: docker introuvable." >&2; exit 1; }
docker compose version >/dev/null

sudo install -d -o "$USER_NAME" -g "$GROUP_NAME" "$MAINT_DIR"
chmod 0755 "$HELPER"

sudo tee "$SERVICE" >/dev/null <<EOF
[Unit]
Description=Flow Finance update helper
After=docker.service network-online.target
Wants=network-online.target
Requires=docker.service

[Service]
Type=simple
User=$USER_NAME
Group=$GROUP_NAME
WorkingDirectory=$REPO_ROOT
Environment=FLOW_REPO_ROOT=$REPO_ROOT
Environment=FLOW_MAINTENANCE_DIR=$MAINT_DIR
ExecStart=/usr/bin/python3 $HELPER
Restart=always
RestartSec=3
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
EOF

sudo tee "$AUDIT_SERVICE" >/dev/null <<EOF
[Unit]
Description=Flow Finance daily read-only financial audit
After=docker.service flow-finance.service
Wants=docker.service

[Service]
Type=oneshot
User=$USER_NAME
Group=$GROUP_NAME
WorkingDirectory=$FLOW_DIR
ExecStart=$DOCKER_BIN compose run --rm --no-deps flow-finance python maintenance/audit_financial_integrity.py --db /data/flow.db --fail-on-hard
Nice=10
IOSchedulingClass=idle
EOF

sudo tee "$AUDIT_TIMER" >/dev/null <<EOF
[Unit]
Description=Run Flow Finance financial audit every day

[Timer]
OnCalendar=*-*-* 04:15:00
Persistent=true
RandomizedDelaySec=10m
Unit=flow-finance-audit.service

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now flow-finance-update.service
sudo systemctl restart flow-finance-update.service
sudo systemctl enable --now flow-finance-audit.timer

echo "Flow update helper installé depuis le repo: $HELPER"
echo "Service: flow-finance-update.service"
echo "Tests: recette pytest complète avant chaque redémarrage"
echo "Audit: flow-finance-audit.timer, quotidien à partir de 04:15"
echo "État: sudo systemctl status flow-finance-update.service --no-pager"
