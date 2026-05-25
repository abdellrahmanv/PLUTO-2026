#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
IFACE="${PLUTO_WIFI_IFACE:-wlan0}"
HOTSPOT_IP="${PLUTO_HOTSPOT_IP:-192.168.4.1}"

cd "$APP_DIR"

echo "[pluto] boot start"

echo "[pluto] waiting for NetworkManager to be ready..."
nm_ready=0
for i in $(seq 1 30); do
  if nmcli general status >/dev/null 2>&1; then
    echo "[pluto] NetworkManager ready after ${i}s"
    nm_ready=1
    break
  fi
  sleep 1
done
if [ "$nm_ready" != "1" ]; then
  echo "[pluto] WARNING: NetworkManager not responding, trying anyway..."
fi

echo "[pluto] waiting for WiFi device ${IFACE}..."
wifi_ready=0
for i in $(seq 1 20); do
  if nmcli device status 2>/dev/null | grep -q "$IFACE"; then
    echo "[pluto] WiFi device ${IFACE} found after ${i}s"
    wifi_ready=1
    break
  fi
  sleep 1
done
if [ "$wifi_ready" != "1" ]; then
  echo "[pluto] WARNING: ${IFACE} not found, trying anyway..."
fi

echo "[pluto] forcing WiFi radio on"
nmcli radio wifi on || true
nmcli device set "$IFACE" managed yes || true
sleep 2

echo "[pluto] starting hotspot"
hotspot_ok=0
for attempt in 1 2 3; do
  echo "[pluto] hotspot attempt ${attempt}/3"
  if "${APP_DIR}/setup_hotspot.sh"; then
    hotspot_ok=1
    break
  fi
  echo "[pluto] hotspot failed, retrying in 3s..."
  sleep 3
done
if [ "$hotspot_ok" != "1" ]; then
  echo "[pluto] ERROR: hotspot failed after 3 attempts"
fi

echo "[pluto] waiting for ${IFACE} to get ${HOTSPOT_IP}"
ip_ready=0
for _ in $(seq 1 30); do
  if ip -4 addr show "$IFACE" | grep -q "${HOTSPOT_IP}"; then
    echo "[pluto] hotspot IP ready: ${HOTSPOT_IP}"
    ip_ready=1
    break
  fi
  sleep 1
done

if [ "$ip_ready" != "1" ]; then
  echo "[pluto] ERROR: hotspot IP ${HOTSPOT_IP} did not appear on ${IFACE}"
  ip -4 addr show "$IFACE" || true
  nmcli connection show --active || true
  exit 1
fi

echo "[pluto] network state:"
ip -4 addr show "$IFACE" || true
nmcli connection show --active || true

if [ ! -d "${APP_DIR}/.venv" ]; then
  echo "[pluto] creating Python venv"
  python3 -m venv "${APP_DIR}/.venv"
  echo "[pluto] installing Python requirements"
  "${APP_DIR}/.venv/bin/pip" install -q -r "${APP_DIR}/requirements.txt"
fi

echo "[pluto] starting website on 0.0.0.0:8080"
export PLUTO_WEB_HOST="0.0.0.0"
export PLUTO_WEB_PORT="8080"
echo "[pluto] open: http://${HOTSPOT_IP}:8080"
exec "${APP_DIR}/.venv/bin/python" "${APP_DIR}/app.py"
