#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="pluto-motors-test"

echo "Installing Pluto motor website service..."
"${APP_DIR}/install.sh"

echo "Enabling Pluto website on boot..."
sudo systemctl enable "${SERVICE_NAME}"
sudo systemctl restart "${SERVICE_NAME}"

echo "Creating Pluto WiFi hotspot and enabling it on boot..."
sudo "${APP_DIR}/setup_hotspot.sh"

echo
echo "Pluto auto-start is ON."
echo "When the Raspberry Pi powers up:"
echo "  1. WiFi hotspot starts: Pluto-Motors"
echo "  2. Website starts:      http://10.42.0.1:8080"
echo
echo "To undo this later:"
echo "  sudo ./unauto_system.sh"

