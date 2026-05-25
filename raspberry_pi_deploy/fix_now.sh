#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$APP_DIR"
chmod +x ./*.sh

echo "Resetting old Pluto services..."
sudo systemctl stop pluto-motors-test >/dev/null 2>&1 || true
sudo systemctl stop pluto-hotspot >/dev/null 2>&1 || true
sudo systemctl stop pluto-system >/dev/null 2>&1 || true
sudo systemctl disable pluto-motors-test >/dev/null 2>&1 || true
sudo systemctl disable pluto-hotspot >/dev/null 2>&1 || true
sudo systemctl disable pluto-system >/dev/null 2>&1 || true
sudo rm -f /etc/systemd/system/pluto-hotspot.service
sudo rm -f /etc/systemd/system/pluto-system.service
sudo systemctl daemon-reload

echo "Installing fixed Pluto boot system..."
"${APP_DIR}/auto_system.sh"

sleep 3

echo
echo "Local website check:"
if curl -fsS http://127.0.0.1:8080/health; then
  echo "Website is alive."
else
  echo "Website did not answer locally. Showing logs:"
  sudo journalctl -u pluto-system -n 80 --no-pager
  exit 1
fi

echo
echo "WiFi state:"
ip -4 addr show wlan0 || true
nmcli connection show --active || true

echo
echo "Open from your phone/laptop:"
echo "  WiFi: Pluto-Motors"
echo "  Pass: pluto1234"
echo "  Site: http://192.168.4.1:8080"

