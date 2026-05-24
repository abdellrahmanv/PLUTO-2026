#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
IFACE="${PLUTO_WIFI_IFACE:-wlan0}"
HOTSPOT_IP="${PLUTO_HOTSPOT_IP:-10.42.0.1}"

cd "$APP_DIR"

echo "[pluto] boot start"
echo "[pluto] forcing WiFi radio on"
nmcli radio wifi on || true

echo "[pluto] starting hotspot"
"${APP_DIR}/setup_hotspot.sh"

echo "[pluto] waiting for ${IFACE} to get ${HOTSPOT_IP}"
for _ in $(seq 1 30); do
  if ip -4 addr show "$IFACE" | grep -q "${HOTSPOT_IP}"; then
    echo "[pluto] hotspot IP ready: ${HOTSPOT_IP}"
    break
  fi
  sleep 1
done

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
exec "${APP_DIR}/.venv/bin/python" "${APP_DIR}/app.py"
