#!/usr/bin/env bash
set -euo pipefail

SSID="${PLUTO_WIFI_SSID:-Pluto-Motors}"
PASSWORD="${PLUTO_WIFI_PASSWORD:-pluto1234}"
IFACE="${PLUTO_WIFI_IFACE:-wlan0}"
HOTSPOT_IP="${PLUTO_HOTSPOT_IP:-192.168.4.1}"
CON_NAME="pluto-hotspot"

if [ "$EUID" -ne 0 ]; then
  echo "Run with sudo: sudo ./setup_hotspot.sh"
  exit 1
fi

if [ ${#PASSWORD} -lt 8 ]; then
  echo "Hotspot password must be at least 8 characters."
  exit 1
fi

echo "Creating Pluto hotspot on ${IFACE}..."
nmcli radio wifi on || true
nmcli connection down "$CON_NAME" >/dev/null 2>&1 || true
nmcli connection delete "$CON_NAME" >/dev/null 2>&1 || true

nmcli connection add type wifi ifname "$IFACE" con-name "$CON_NAME" autoconnect yes ssid "$SSID"
nmcli connection modify "$CON_NAME" connection.autoconnect yes connection.autoconnect-priority 999
nmcli connection modify "$CON_NAME" 802-11-wireless.mode ap 802-11-wireless.band bg
nmcli connection modify "$CON_NAME" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PASSWORD"
nmcli connection modify "$CON_NAME" ipv4.method shared ipv4.addresses "${HOTSPOT_IP}/24" ipv6.method disabled
nmcli connection up "$CON_NAME"

for _ in $(seq 1 15); do
  if ip -4 addr show "$IFACE" | grep -q "${HOTSPOT_IP}"; then
    break
  fi
  sleep 1
done

echo "Pluto hotspot is running."
echo "SSID: $SSID"
echo "PASS: $PASSWORD"
echo "Website: http://${HOTSPOT_IP}:8080"
