#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="pluto-motors-test"
HOTSPOT_SERVICE="pluto-hotspot"

if [ ! -x "${APP_DIR}/setup_hotspot.sh" ]; then
  chmod +x "${APP_DIR}/setup_hotspot.sh"
fi

echo "Installing Pluto motor website service..."
"${APP_DIR}/install.sh"

echo "Creating Pluto WiFi hotspot and enabling it on boot..."
sudo "${APP_DIR}/setup_hotspot.sh"

echo "Installing forced hotspot boot service..."
sudo tee "/etc/systemd/system/${HOTSPOT_SERVICE}.service" >/dev/null <<EOF
[Unit]
Description=Force Pluto WiFi Hotspot
After=NetworkManager.service
Wants=NetworkManager.service

[Service]
Type=oneshot
ExecStart=/usr/bin/nmcli connection up pluto-hotspot
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

echo "Enabling Pluto hotspot and website on boot..."
sudo systemctl daemon-reload
sudo systemctl enable "${HOTSPOT_SERVICE}"
sudo systemctl enable "${SERVICE_NAME}"
sudo systemctl restart "${HOTSPOT_SERVICE}"
sudo systemctl restart "${SERVICE_NAME}"

echo
echo "Pluto auto-start is ON."
echo "When the Raspberry Pi powers up:"
echo "  1. WiFi hotspot starts: Pluto-Motors"
echo "  2. Website starts:      http://10.42.0.1:8080"
echo
echo "To undo this later:"
echo "  sudo ./unauto_system.sh"
