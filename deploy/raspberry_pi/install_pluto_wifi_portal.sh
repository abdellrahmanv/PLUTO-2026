#!/usr/bin/env bash
set -euo pipefail

START_NOW=0
INSTALL_APT=1

usage() {
  cat <<'USAGE'
Install PLUTO Raspberry Pi autostart + Wi-Fi captive portal.

Usage:
  sudo deploy/raspberry_pi/install_pluto_wifi_portal.sh [options]

Options:
  --start-now          Start services immediately after installing.
  --skip-apt           Do not run apt-get install hostapd dnsmasq.
  --ssid NAME          Wi-Fi SSID. Default: PLUTO-OPS
  --password VALUE     Wi-Fi WPA2 password. Default: pluto2026
  --iface NAME         Wi-Fi interface. Default: wlan0
  --ap-ip IP           Pi AP IP. Default: 192.168.50.1
  --user USER          Service user. Default: sudo user, then pi.
  --python PATH        Python executable. Default: /home/pi/yolo/env/bin/python, then python3.
  --repo PATH          Repo root. Default: detected repo root.
  -h, --help           Show this help.

Environment variables with the same PLUTO_* names may also be used.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --start-now) START_NOW=1; shift ;;
    --skip-apt) INSTALL_APT=0; shift ;;
    --ssid) PLUTO_SSID="${2:?missing ssid}"; shift 2 ;;
    --password) PLUTO_WIFI_PASSWORD="${2:?missing password}"; shift 2 ;;
    --iface) PLUTO_WIFI_IFACE="${2:?missing interface}"; shift 2 ;;
    --ap-ip) PLUTO_AP_IP="${2:?missing ap ip}"; shift 2 ;;
    --user) PLUTO_USER="${2:?missing user}"; shift 2 ;;
    --python) PLUTO_PYTHON="${2:?missing python path}"; shift 2 ;;
    --repo) PLUTO_REPO="${2:?missing repo path}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  exec sudo -E bash "$0" "$@"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

PLUTO_REPO="${PLUTO_REPO:-$REPO_ROOT}"
PLUTO_USER="${PLUTO_USER:-${SUDO_USER:-pi}}"
PLUTO_PYTHON="${PLUTO_PYTHON:-/home/pi/yolo/env/bin/python}"
PLUTO_WEB_HOST="${PLUTO_WEB_HOST:-0.0.0.0}"
PLUTO_WEB_PORT="${PLUTO_WEB_PORT:-8080}"
PLUTO_WEB_EXTRA_ARGS="${PLUTO_WEB_EXTRA_ARGS:-}"
PLUTO_SPEAKER_DEVICE="${PLUTO_SPEAKER_DEVICE:-plughw:CARD=Headphones,DEV=0}"
PLUTO_DANCE_AUDIO="${PLUTO_DANCE_AUDIO:-}"
PLUTO_WIFI_IFACE="${PLUTO_WIFI_IFACE:-wlan0}"
PLUTO_SSID="${PLUTO_SSID:-PLUTO-OPS}"
PLUTO_WIFI_PASSWORD="${PLUTO_WIFI_PASSWORD:-pluto2026}"
PLUTO_COUNTRY="${PLUTO_COUNTRY:-EG}"
PLUTO_CHANNEL="${PLUTO_CHANNEL:-6}"
PLUTO_AP_IP="${PLUTO_AP_IP:-192.168.50.1}"
PLUTO_DHCP_START="${PLUTO_DHCP_START:-192.168.50.20}"
PLUTO_DHCP_END="${PLUTO_DHCP_END:-192.168.50.80}"
PLUTO_PORTAL_TARGET="${PLUTO_PORTAL_TARGET:-http://${PLUTO_AP_IP}:${PLUTO_WEB_PORT}/}"

if [[ ! -x "$PLUTO_PYTHON" ]]; then
  PLUTO_PYTHON="$(command -v python3 || true)"
fi

if [[ -z "$PLUTO_PYTHON" || ! -x "$PLUTO_PYTHON" ]]; then
  echo "Python was not found. Pass --python /path/to/python." >&2
  exit 1
fi

if ! id "$PLUTO_USER" >/dev/null 2>&1; then
  echo "User does not exist: $PLUTO_USER" >&2
  exit 1
fi

if (( ${#PLUTO_WIFI_PASSWORD} < 8 || ${#PLUTO_WIFI_PASSWORD} > 63 )); then
  echo "Wi-Fi password must be 8-63 characters for WPA2." >&2
  exit 1
fi

if [[ "$PLUTO_SSID" == *"|"* || "$PLUTO_WIFI_PASSWORD" == *"|"* ]]; then
  echo "SSID/password may not contain the | character." >&2
  exit 1
fi

sed_escape() {
  printf '%s' "$1" | sed -e 's/[\/&|]/\\&/g'
}

render_template() {
  local source="$1"
  local target="$2"
  sed \
    -e "s|{{PLUTO_WIFI_IFACE}}|$(sed_escape "$PLUTO_WIFI_IFACE")|g" \
    -e "s|{{PLUTO_SSID}}|$(sed_escape "$PLUTO_SSID")|g" \
    -e "s|{{PLUTO_WIFI_PASSWORD}}|$(sed_escape "$PLUTO_WIFI_PASSWORD")|g" \
    -e "s|{{PLUTO_COUNTRY}}|$(sed_escape "$PLUTO_COUNTRY")|g" \
    -e "s|{{PLUTO_CHANNEL}}|$(sed_escape "$PLUTO_CHANNEL")|g" \
    -e "s|{{PLUTO_AP_IP}}|$(sed_escape "$PLUTO_AP_IP")|g" \
    -e "s|{{PLUTO_DHCP_START}}|$(sed_escape "$PLUTO_DHCP_START")|g" \
    -e "s|{{PLUTO_DHCP_END}}|$(sed_escape "$PLUTO_DHCP_END")|g" \
    "$source" > "$target"
}

render_service() {
  local source="$1"
  local target="$2"
  sed \
    -e "s|__PLUTO_USER__|$(sed_escape "$PLUTO_USER")|g" \
    -e "s|__PLUTO_REPO__|$(sed_escape "$PLUTO_REPO")|g" \
    "$source" > "$target"
}

if [[ "$INSTALL_APT" -eq 1 ]]; then
  apt-get update
  apt-get install -y hostapd dnsmasq
fi

mkdir -p /etc/pluto
cat > /etc/pluto/pluto.env <<EOF
PLUTO_REPO=$PLUTO_REPO
PLUTO_PYTHON=$PLUTO_PYTHON
PLUTO_WEB_HOST=$PLUTO_WEB_HOST
PLUTO_WEB_PORT=$PLUTO_WEB_PORT
PLUTO_WEB_EXTRA_ARGS=$PLUTO_WEB_EXTRA_ARGS
PLUTO_SPEAKER_DEVICE=$PLUTO_SPEAKER_DEVICE
PLUTO_DANCE_AUDIO=$PLUTO_DANCE_AUDIO
PLUTO_WIFI_IFACE=$PLUTO_WIFI_IFACE
PLUTO_AP_IP=$PLUTO_AP_IP
PLUTO_PORTAL_TARGET=$PLUTO_PORTAL_TARGET
EOF
chmod 0600 /etc/pluto/pluto.env

render_template "$SCRIPT_DIR/hostapd.conf.in" /etc/pluto/hostapd.conf
render_template "$SCRIPT_DIR/dnsmasq.conf.in" /etc/pluto/dnsmasq.conf
chmod 0600 /etc/pluto/hostapd.conf
chmod 0644 /etc/pluto/dnsmasq.conf

render_service "$SCRIPT_DIR/systemd/pluto-web.service" /etc/systemd/system/pluto-web.service
render_service "$SCRIPT_DIR/systemd/pluto-ap-network.service" /etc/systemd/system/pluto-ap-network.service
render_service "$SCRIPT_DIR/systemd/pluto-hostapd.service" /etc/systemd/system/pluto-hostapd.service
render_service "$SCRIPT_DIR/systemd/pluto-dnsmasq.service" /etc/systemd/system/pluto-dnsmasq.service
render_service "$SCRIPT_DIR/systemd/pluto-captive-portal.service" /etc/systemd/system/pluto-captive-portal.service
chmod 0644 /etc/systemd/system/pluto-*.service

if command -v nmcli >/dev/null 2>&1 && systemctl list-unit-files NetworkManager.service >/dev/null 2>&1; then
  mkdir -p /etc/NetworkManager/conf.d
  cat > /etc/NetworkManager/conf.d/90-pluto-ap-unmanaged.conf <<EOF
[keyfile]
unmanaged-devices=interface-name:$PLUTO_WIFI_IFACE
EOF
  systemctl reload NetworkManager 2>/dev/null || true
fi

systemctl stop hostapd dnsmasq 2>/dev/null || true
systemctl disable hostapd dnsmasq 2>/dev/null || true
systemctl daemon-reload
systemctl enable \
  pluto-web.service \
  pluto-ap-network.service \
  pluto-hostapd.service \
  pluto-dnsmasq.service \
  pluto-captive-portal.service

if [[ "$START_NOW" -eq 1 ]]; then
  systemctl restart pluto-web.service
  systemctl restart pluto-ap-network.service pluto-hostapd.service pluto-dnsmasq.service pluto-captive-portal.service
fi

cat <<EOF

PLUTO Raspberry Pi deployment installed.

SSID:       $PLUTO_SSID
Password:   $PLUTO_WIFI_PASSWORD
Console:    $PLUTO_PORTAL_TARGET
Web check:  curl http://127.0.0.1:$PLUTO_WEB_PORT/healthz
Portal:     curl -I http://$PLUTO_AP_IP/generate_204

Services:
  systemctl status pluto-web
  systemctl status pluto-hostapd
  systemctl status pluto-dnsmasq
  systemctl status pluto-captive-portal

If you did not pass --start-now, reboot the Pi or run:
  sudo systemctl restart pluto-web pluto-ap-network pluto-hostapd pluto-dnsmasq pluto-captive-portal

EOF
