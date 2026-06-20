#!/usr/bin/env bash
set -euo pipefail

LAUNCH_NORMAL=0

usage() {
  cat <<'USAGE'
Disable PLUTO booth mode on Raspberry Pi.

This stops and disables the automatic full website service, PLUTO Wi-Fi access
point, DHCP/DNS, and captive portal. It leaves the repo files in place so the
website can still be launched normally by command.

Usage:
  sudo deploy/raspberry_pi/disable_pluto_booth_mode.sh [options]

Options:
  --launch-normal      After disabling booth mode, launch the website normally
                       in this terminal.
  --repo PATH          Repo root for --launch-normal. Default: detected repo root.
  --python PATH        Python executable for --launch-normal.
  --host HOST          Normal launch host. Default: 0.0.0.0
  --port PORT          Normal launch port. Default: 8080
  -h, --help           Show this help.
USAGE
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

PLUTO_REPO="${PLUTO_REPO:-$REPO_ROOT}"
PLUTO_PYTHON="${PLUTO_PYTHON:-/home/pi/yolo/env/bin/python}"
PLUTO_WEB_HOST="${PLUTO_WEB_HOST:-0.0.0.0}"
PLUTO_WEB_PORT="${PLUTO_WEB_PORT:-8080}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --launch-normal) LAUNCH_NORMAL=1; shift ;;
    --repo) PLUTO_REPO="${2:?missing repo path}"; shift 2 ;;
    --python) PLUTO_PYTHON="${2:?missing python path}"; shift 2 ;;
    --host) PLUTO_WEB_HOST="${2:?missing host}"; shift 2 ;;
    --port) PLUTO_WEB_PORT="${2:?missing port}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  exec sudo -E bash "$0" "$@"
fi

SERVICES=(
  pluto-captive-portal.service
  pluto-dnsmasq.service
  pluto-hostapd.service
  pluto-ap-network.service
  pluto-web.service
)

systemctl stop "${SERVICES[@]}" 2>/dev/null || true
systemctl disable "${SERVICES[@]}" 2>/dev/null || true

systemctl stop hostapd dnsmasq 2>/dev/null || true
systemctl disable hostapd dnsmasq 2>/dev/null || true

if [[ -f /etc/NetworkManager/conf.d/90-pluto-ap-unmanaged.conf ]]; then
  rm -f /etc/NetworkManager/conf.d/90-pluto-ap-unmanaged.conf
  systemctl reload NetworkManager 2>/dev/null || true
fi

if [[ -f /etc/pluto/pluto.env ]]; then
  PLUTO_WIFI_IFACE="$(grep -E '^PLUTO_WIFI_IFACE=' /etc/pluto/pluto.env | tail -1 | cut -d= -f2- || true)"
  if [[ -n "$PLUTO_WIFI_IFACE" ]]; then
    ip addr flush dev "$PLUTO_WIFI_IFACE" 2>/dev/null || true
    ip link set "$PLUTO_WIFI_IFACE" down 2>/dev/null || true
    ip link set "$PLUTO_WIFI_IFACE" up 2>/dev/null || true
  fi
fi

systemctl daemon-reload

cat <<EOF

PLUTO booth mode is disabled.

Stopped/disabled:
  pluto-web
  pluto-ap-network
  pluto-hostapd
  pluto-dnsmasq
  pluto-captive-portal

Normal manual launch:
  cd "$PLUTO_REPO"
  "$PLUTO_PYTHON" -m pluto_runtime.web_shell --host "$PLUTO_WEB_HOST" --port "$PLUTO_WEB_PORT"

EOF

if [[ "$LAUNCH_NORMAL" -eq 1 ]]; then
  if [[ ! -x "$PLUTO_PYTHON" ]]; then
    PLUTO_PYTHON="$(command -v python3 || true)"
  fi
  if [[ -z "$PLUTO_PYTHON" || ! -x "$PLUTO_PYTHON" ]]; then
    echo "Python was not found. Pass --python /path/to/python." >&2
    exit 1
  fi
  cd "$PLUTO_REPO"
  exec "$PLUTO_PYTHON" -m pluto_runtime.web_shell --host "$PLUTO_WEB_HOST" --port "$PLUTO_WEB_PORT"
fi
