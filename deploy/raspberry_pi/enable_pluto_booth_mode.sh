#!/usr/bin/env bash
set -euo pipefail

START_NOW=1
INSTALL_APT=1

usage() {
  cat <<'USAGE'
Enable PLUTO booth mode on Raspberry Pi.

This installs and enables the full PLUTO website autostart, creates the PLUTO
Wi-Fi access point, and starts the captive portal that opens the website when a
phone or laptop joins the network.

Usage:
  sudo deploy/raspberry_pi/enable_pluto_booth_mode.sh [options]

Options:
  --no-start-now       Install and enable services, but do not restart them now.
  --skip-apt           Do not install hostapd/dnsmasq packages.
  --ssid NAME          Wi-Fi SSID. Default: PLUTO-OPS
  --password VALUE     Wi-Fi password. Default: pluto2026
  --iface NAME         Wi-Fi interface. Default: wlan0
  --ap-ip IP           Pi AP IP. Default: 192.168.50.1
  --port PORT          Website port. Default: 8080
  --user USER          Service user. Default: sudo user, then pi.
  --python PATH        Python executable. Default: /home/pi/yolo/env/bin/python, then python3.
  --repo PATH          Repo root. Default: detected repo root.
  --dance-audio PATH   Billie Jean cut song path for Dance Mode.
                       Default: /home/pi/PLUTO-2026/audio/billie-jean-cut.mp3
  -h, --help           Show this help.
USAGE
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

PLUTO_REPO="${PLUTO_REPO:-$REPO_ROOT}"
PLUTO_WEB_HOST="${PLUTO_WEB_HOST:-0.0.0.0}"
PLUTO_WEB_PORT="${PLUTO_WEB_PORT:-8080}"
PLUTO_WEB_EXTRA_ARGS="${PLUTO_WEB_EXTRA_ARGS---fast-start}"
PLUTO_DANCE_AUDIO="${PLUTO_DANCE_AUDIO:-/home/pi/PLUTO-2026/audio/billie-jean-cut.mp3}"
PLUTO_SSID="${PLUTO_SSID:-PLUTO-OPS}"
PLUTO_WIFI_PASSWORD="${PLUTO_WIFI_PASSWORD:-pluto2026}"
PLUTO_WIFI_IFACE="${PLUTO_WIFI_IFACE:-wlan0}"
PLUTO_AP_IP="${PLUTO_AP_IP:-192.168.50.1}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-start-now) START_NOW=0; shift ;;
    --skip-apt) INSTALL_APT=0; shift ;;
    --ssid) PLUTO_SSID="${2:?missing ssid}"; shift 2 ;;
    --password) PLUTO_WIFI_PASSWORD="${2:?missing password}"; shift 2 ;;
    --iface) PLUTO_WIFI_IFACE="${2:?missing interface}"; shift 2 ;;
    --ap-ip) PLUTO_AP_IP="${2:?missing ap ip}"; shift 2 ;;
    --port) PLUTO_WEB_PORT="${2:?missing port}"; shift 2 ;;
    --user) PLUTO_USER="${2:?missing user}"; shift 2 ;;
    --python) PLUTO_PYTHON="${2:?missing python path}"; shift 2 ;;
    --repo) PLUTO_REPO="${2:?missing repo path}"; shift 2 ;;
    --dance-audio) PLUTO_DANCE_AUDIO="${2:?missing dance audio path}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  exec sudo -E bash "$0" "$@"
fi

export PLUTO_REPO
export PLUTO_WEB_HOST
export PLUTO_WEB_PORT
export PLUTO_WEB_EXTRA_ARGS
export PLUTO_DANCE_AUDIO
export PLUTO_SSID
export PLUTO_WIFI_PASSWORD
export PLUTO_WIFI_IFACE
export PLUTO_AP_IP
export PLUTO_PORTAL_TARGET="${PLUTO_PORTAL_TARGET:-http://${PLUTO_AP_IP}:${PLUTO_WEB_PORT}/}"

INSTALL_ARGS=()
if [[ "$START_NOW" -eq 1 ]]; then
  INSTALL_ARGS+=(--start-now)
fi
if [[ "$INSTALL_APT" -eq 0 ]]; then
  INSTALL_ARGS+=(--skip-apt)
fi
if [[ -n "${PLUTO_USER:-}" ]]; then
  INSTALL_ARGS+=(--user "$PLUTO_USER")
fi
if [[ -n "${PLUTO_PYTHON:-}" ]]; then
  INSTALL_ARGS+=(--python "$PLUTO_PYTHON")
fi

bash "$SCRIPT_DIR/install_pluto_wifi_portal.sh" \
  "${INSTALL_ARGS[@]}" \
  --repo "$PLUTO_REPO" \
  --ssid "$PLUTO_SSID" \
  --password "$PLUTO_WIFI_PASSWORD" \
  --iface "$PLUTO_WIFI_IFACE" \
  --ap-ip "$PLUTO_AP_IP"

cat <<EOF

PLUTO booth mode is enabled.

Full website:
  http://${PLUTO_AP_IP}:${PLUTO_WEB_PORT}/

Wi-Fi:
  SSID:     ${PLUTO_SSID}
  Password: ${PLUTO_WIFI_PASSWORD}

Captive portal:
  Joining the PLUTO Wi-Fi should open the full website automatically.

Dance audio:
  ${PLUTO_DANCE_AUDIO}

Useful checks:
  systemctl status pluto-web
  systemctl status pluto-hostapd
  systemctl status pluto-dnsmasq
  systemctl status pluto-captive-portal
  curl http://127.0.0.1:${PLUTO_WEB_PORT}/healthz

EOF
