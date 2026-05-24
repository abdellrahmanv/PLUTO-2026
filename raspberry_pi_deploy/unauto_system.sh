#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="pluto-motors-test"
HOTSPOT_NAME="pluto-hotspot"

if [ "$EUID" -ne 0 ]; then
  echo "Run with sudo: sudo ./unauto_system.sh"
  exit 1
fi

echo "Stopping Pluto website service..."
systemctl stop "${SERVICE_NAME}" >/dev/null 2>&1 || true

echo "Disabling Pluto website auto-start..."
systemctl disable "${SERVICE_NAME}" >/dev/null 2>&1 || true

echo "Removing Pluto WiFi hotspot..."
nmcli connection down "${HOTSPOT_NAME}" >/dev/null 2>&1 || true
nmcli connection delete "${HOTSPOT_NAME}" >/dev/null 2>&1 || true

echo "Reloading systemd..."
systemctl daemon-reload

echo
echo "Pluto auto-start is OFF."
echo "The Raspberry Pi is back to normal network/startup behavior."
echo
echo "Manual start is still available:"
echo "  ./run.sh"

