#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-start}"
IFACE="${PLUTO_WIFI_IFACE:-wlan0}"
AP_IP="${PLUTO_AP_IP:-192.168.50.1}"

wait_for_iface() {
  local i=0
  while ! ip link show "$IFACE" >/dev/null 2>&1; do
    i=$((i + 1))
    if [[ "$i" -ge 25 ]]; then
      echo "Timed out waiting for $IFACE" >&2
      exit 1
    fi
    sleep 1
  done
}

free_wifi_manager() {
  command -v rfkill >/dev/null 2>&1 && rfkill unblock wifi || true
  if command -v nmcli >/dev/null 2>&1; then
    nmcli radio wifi on >/dev/null 2>&1 || true
    nmcli dev set "$IFACE" managed no >/dev/null 2>&1 || true
    nmcli dev disconnect "$IFACE" >/dev/null 2>&1 || true
  fi
  systemctl stop "wpa_supplicant@$IFACE.service" >/dev/null 2>&1 || true
  command -v wpa_cli >/dev/null 2>&1 && wpa_cli -i "$IFACE" terminate >/dev/null 2>&1 || true
  pkill -f "wpa_supplicant.*(^|[ =])${IFACE}([ $]|$)" >/dev/null 2>&1 || true
}

start_ap_network() {
  wait_for_iface
  free_wifi_manager
  ip link set "$IFACE" down || true
  ip addr flush dev "$IFACE" || true
  command -v iw >/dev/null 2>&1 && iw dev "$IFACE" set power_save off >/dev/null 2>&1 || true
  ip addr add "$AP_IP/24" dev "$IFACE"
  ip link set "$IFACE" up
  ip -o addr show "$IFACE"
}

stop_ap_network() {
  if ip link show "$IFACE" >/dev/null 2>&1; then
    ip addr flush dev "$IFACE" || true
    ip link set "$IFACE" down || true
    ip link set "$IFACE" up || true
  fi
}

case "$ACTION" in
  start) start_ap_network ;;
  stop) stop_ap_network ;;
  *) echo "Usage: $0 {start|stop}" >&2; exit 2 ;;
esac
