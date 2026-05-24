#!/usr/bin/env bash
set -euo pipefail

SSID="${PLUTO_WIFI_SSID:-Pluto-Motors}"
PASSWORD="${PLUTO_WIFI_PASSWORD:-pluto1234}"
IFACE="${PLUTO_WIFI_IFACE:-wlan0}"
CON_NAME="pluto-hotspot"

if [ "$EUID" -ne 0 ]; then
  echo "Run with sudo: sudo ./setup_hotspot.sh"
  exit 1
fi

if [ ${#PASSWORD} -lt 8 ]; then
  echo "Hotspot password must be at least 8 characters."
  exit 1
fi

nmcli connection delete "$CON_NAME" >/dev/null 2>&1 || true

nmcli connection add type wifi ifname "$IFACE" con-name "$CON_NAME" autoconnect yes ssid "$SSID"
nmcli connection modify "$CON_NAME" 802-11-wireless.mode ap 802-11-wireless.band bg ipv4.method shared
nmcli connection modify "$CON_NAME" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PASSWORD"
nmcli connection up "$CON_NAME"

echo "Pluto hotspot is running."
echo "SSID: $SSID"
echo "PASS: $PASSWORD"
echo "Website: http://10.42.0.1:8080"

