#!/usr/bin/env python3
"""Smoke test for Raspberry Pi autostart and Wi-Fi captive portal assets."""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOST = "127.0.0.1"
PORT = 18082
TARGET = "http://192.168.50.1:8080/"
BASE = f"http://{HOST}:{PORT}"


REQUIRED_FILES = [
    "deploy/raspberry_pi/enable_pluto_booth_mode.sh",
    "deploy/raspberry_pi/disable_pluto_booth_mode.sh",
    "deploy/raspberry_pi/install_pluto_wifi_portal.sh",
    "deploy/raspberry_pi/pluto_ap_network.sh",
    "deploy/raspberry_pi/hostapd.conf.in",
    "deploy/raspberry_pi/dnsmasq.conf.in",
    "deploy/raspberry_pi/systemd/pluto-web.service",
    "deploy/raspberry_pi/systemd/pluto-ap-network.service",
    "deploy/raspberry_pi/systemd/pluto-hostapd.service",
    "deploy/raspberry_pi/systemd/pluto-dnsmasq.service",
    "deploy/raspberry_pi/systemd/pluto-captive-portal.service",
    "pluto_runtime/captive_portal.py",
]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(path: str, follow_redirects: bool = True) -> tuple[int, bytes, dict[str, str]]:
    opener = urllib.request.build_opener() if follow_redirects else urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(BASE + path)
    try:
        with opener.open(req, timeout=5) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def wait_ready() -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            status, raw, _ = request("/healthz")
            if status == 200 and json.loads(raw.decode("utf-8"))["ok"] is True:
                return
        except Exception:
            pass
        time.sleep(0.1)
    raise RuntimeError("captive portal did not become ready")


def assert_assets() -> None:
    for rel in REQUIRED_FILES:
        path = ROOT / rel
        assert path.exists(), f"missing {rel}"

    installer = (ROOT / "deploy/raspberry_pi/install_pluto_wifi_portal.sh").read_text(encoding="utf-8")
    assert "pluto-web.service" in installer
    assert "pluto-captive-portal.service" in installer
    assert "systemctl enable" in installer
    assert "--start-now" in installer
    assert "PLUTO_DANCE_AUDIO" in installer
    assert "--fast-start" in installer
    assert "nmcli dev set" in installer

    ap_network = (ROOT / "deploy/raspberry_pi/pluto_ap_network.sh").read_text(encoding="utf-8")
    assert "rfkill unblock wifi" in ap_network
    assert "managed no" in ap_network
    assert "wpa_supplicant" in ap_network
    assert 'ip addr add "$AP_IP/24"' in ap_network

    enable_booth = (ROOT / "deploy/raspberry_pi/enable_pluto_booth_mode.sh").read_text(encoding="utf-8")
    assert "install_pluto_wifi_portal.sh" in enable_booth
    assert "PLUTO booth mode is enabled" in enable_booth
    assert "PLUTO_DANCE_AUDIO" in enable_booth
    assert "--fast-start" in enable_booth

    disable_booth = (ROOT / "deploy/raspberry_pi/disable_pluto_booth_mode.sh").read_text(encoding="utf-8")
    assert "pluto-captive-portal.service" in disable_booth
    assert "PLUTO booth mode is disabled" in disable_booth
    assert "pluto_runtime.web_shell" in disable_booth

    hostapd = (ROOT / "deploy/raspberry_pi/hostapd.conf.in").read_text(encoding="utf-8")
    assert "wpa=2" in hostapd
    assert "{{PLUTO_SSID}}" in hostapd
    assert "ignore_broadcast_ssid=0" in hostapd

    dnsmasq = (ROOT / "deploy/raspberry_pi/dnsmasq.conf.in").read_text(encoding="utf-8")
    assert "address=/#/{{PLUTO_AP_IP}}" in dnsmasq
    assert "dhcp-range={{PLUTO_DHCP_START}},{{PLUTO_DHCP_END}}" in dnsmasq
    assert "dhcp-option=114,http://{{PLUTO_AP_IP}}/" in dnsmasq

    web_service = (ROOT / "deploy/raspberry_pi/systemd/pluto-web.service").read_text(encoding="utf-8")
    assert "pluto_runtime.web_shell" in web_service
    assert "Restart=always" in web_service
    assert "network-online.target" not in web_service

    ap_service = (ROOT / "deploy/raspberry_pi/systemd/pluto-ap-network.service").read_text(encoding="utf-8")
    assert "pluto_ap_network.sh start" in ap_service

    portal_service = (ROOT / "deploy/raspberry_pi/systemd/pluto-captive-portal.service").read_text(encoding="utf-8")
    assert "pluto_runtime.captive_portal" in portal_service
    assert "--port 80" in portal_service

    web_shell = (ROOT / "pluto_runtime/web_shell.py").read_text(encoding="utf-8")
    assert "--fast-start" in web_shell
    assert "def lite_page" in web_shell
    assert "def is_legacy_ipad" in web_shell


def assert_portal_runtime() -> None:
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "pluto_runtime.captive_portal",
            "--host",
            HOST,
            "--port",
            str(PORT),
            "--target-url",
            TARGET,
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        wait_ready()

        status, body, _ = request("/")
        assert status == 200, status
        assert b"PLUTO Mission Control" in body
        assert TARGET.encode("utf-8") in body

        for path in ("/generate_204", "/hotspot-detect.html", "/connecttest.txt", "/ncsi.txt"):
            code, _, headers = request(path, follow_redirects=False)
            assert code == 302, (path, code)
            assert headers.get("Location") == TARGET, (path, headers)

        code, _, headers = request("/anything-else", follow_redirects=False)
        assert code == 302, code
        assert headers.get("Location") == TARGET, headers
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def main() -> int:
    assert_assets()
    assert_portal_runtime()
    print("PI_DEPLOYMENT_SMOKE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
