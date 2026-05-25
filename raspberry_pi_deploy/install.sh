#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="pluto-motors-test"
RUN_USER="${SUDO_USER:-${USER}}"

sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip network-manager
sudo systemctl enable --now NetworkManager
sudo usermod -aG dialout "${RUN_USER}" || true
sudo usermod -aG plugdev "${RUN_USER}" || true

cd "$APP_DIR"
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

sudo tee "/etc/systemd/system/${SERVICE_NAME}.service" >/dev/null <<EOF
[Unit]
Description=Pluto Motors Test Manual Website
After=pluto-hotspot.service network.target
Wants=pluto-hotspot.service

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/.venv/bin/python ${APP_DIR}/app.py
Restart=always
RestartSec=2
User=${RUN_USER}
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload

echo "Installed ${SERVICE_NAME}."
echo "Serial permissions set for user: ${RUN_USER}"
echo "If this was the first install, reboot once so group permissions apply."
echo "Run now:     ./run.sh"
echo "Enable boot: sudo systemctl enable ${SERVICE_NAME}"
echo "Start boot:  sudo systemctl start ${SERVICE_NAME}"
