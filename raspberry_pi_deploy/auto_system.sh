#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="pluto-motors-test"
HOTSPOT_SERVICE="pluto-hotspot"
SYSTEM_SERVICE="pluto-system"

if [ ! -x "${APP_DIR}/setup_hotspot.sh" ]; then
  chmod +x "${APP_DIR}/setup_hotspot.sh"
fi
chmod +x "${APP_DIR}/pluto_system_boot.sh"

echo "Installing Pluto motor website service..."
"${APP_DIR}/install.sh"
sudo systemctl enable --now NetworkManager

echo "Installing one-shot Pluto system boot service..."
sudo tee "/etc/systemd/system/${SYSTEM_SERVICE}.service" >/dev/null <<EOF
[Unit]
Description=Pluto Full Boot: Hotspot + Motors Website
After=NetworkManager.service NetworkManager-wait-online.service
Wants=NetworkManager.service NetworkManager-wait-online.service

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/pluto_system_boot.sh
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

echo "Disabling old split services if they exist..."
sudo systemctl stop "${SERVICE_NAME}" >/dev/null 2>&1 || true
sudo systemctl disable "${SERVICE_NAME}" >/dev/null 2>&1 || true
sudo systemctl stop "${HOTSPOT_SERVICE}" >/dev/null 2>&1 || true
sudo systemctl disable "${HOTSPOT_SERVICE}" >/dev/null 2>&1 || true
sudo rm -f "/etc/systemd/system/${HOTSPOT_SERVICE}.service"

echo "Enabling Pluto system on boot..."
sudo systemctl daemon-reload
sudo systemctl enable "${SYSTEM_SERVICE}"
sudo systemctl restart "${SYSTEM_SERVICE}"

echo
echo "Pluto auto-start is ON."
echo "When the Raspberry Pi powers up:"
echo "  1. WiFi hotspot starts: Pluto-Motors"
echo "  2. Website starts:      http://192.168.4.1:8080"
echo
echo "Check it with:"
echo "  sudo systemctl status pluto-system"
echo "  sudo journalctl -u pluto-system -f"
echo
echo "To undo this later:"
echo "  sudo ./unauto_system.sh"
