#!/usr/bin/env python3
"""Tiny PLUTO captive portal redirect helper.

This server is intentionally small: dnsmasq points HTTP captive-portal probes
at the Raspberry Pi, and this process sends the operator to the real PLUTO
console. It does not proxy API traffic or grant any robot authority.
"""

from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


DEFAULT_TARGET_URL = "http://192.168.50.1:8080/"
CAPTIVE_PROBE_PATHS = {
    "/generate_204",
    "/gen_204",
    "/hotspot-detect.html",
    "/library/test/success.html",
    "/connecttest.txt",
    "/ncsi.txt",
    "/fwlink",
    "/success.txt",
    "/canonical.html",
}


def normalize_target_url(value: str) -> str:
    value = (value or DEFAULT_TARGET_URL).strip()
    if not value.startswith(("http://", "https://")):
        value = "http://" + value
    return value if value.endswith("/") else value + "/"


def portal_page(target_url: str) -> bytes:
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="0; url={target_url}">
  <title>PLUTO Wi-Fi</title>
  <style>
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      font-family: Arial, sans-serif;
      background: #101820;
      color: #f4fbff;
    }}
    main {{
      width: min(92vw, 520px);
      border: 1px solid rgba(255,255,255,0.16);
      border-radius: 8px;
      padding: 24px;
      background: #17232e;
    }}
    a {{ color: #84d7ff; font-weight: 700; }}
    small {{ color: #b8c7d1; }}
  </style>
</head>
<body>
  <main>
    <h1>PLUTO Mission Control</h1>
    <p>Opening the PLUTO operator console.</p>
    <p><a href="{target_url}">Open PLUTO console</a></p>
    <small>Joining Wi-Fi does not authorize motion. All safety gates remain active.</small>
  </main>
  <script>window.location.replace({json.dumps(target_url)});</script>
</body>
</html>"""
    return html.encode("utf-8")


class CaptivePortalHandler(BaseHTTPRequestHandler):
    target_url = DEFAULT_TARGET_URL

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def send_no_store(self) -> None:
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Connection", "close")

    def redirect_to_console(self) -> None:
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", self.target_url)
        self.send_no_store()
        self.end_headers()

    def send_portal_page(self, include_body: bool = True) -> None:
        body = portal_page(self.target_url)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body) if include_body else 0))
        self.send_no_store()
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def send_health(self) -> None:
        body = json.dumps({"ok": True, "target_url": self.target_url}).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_no_store()
        self.end_headers()
        self.wfile.write(body)

    def handle_request(self, include_body: bool = True) -> None:
        path = urlparse(self.path).path or "/"
        if path == "/healthz":
            self.send_health()
            return
        if path in CAPTIVE_PROBE_PATHS or path.startswith("/redirect"):
            self.redirect_to_console()
            return
        if path == "/":
            self.send_portal_page(include_body=include_body)
            return
        self.redirect_to_console()

    def do_GET(self) -> None:
        self.handle_request(include_body=True)

    def do_HEAD(self) -> None:
        self.handle_request(include_body=False)

    def do_POST(self) -> None:
        self.redirect_to_console()


def run(host: str, port: int, target_url: str) -> None:
    CaptivePortalHandler.target_url = normalize_target_url(target_url)
    server = ThreadingHTTPServer((host, port), CaptivePortalHandler)
    print(f"PLUTO captive portal on {host}:{port} -> {CaptivePortalHandler.target_url}")
    server.serve_forever()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the PLUTO captive portal redirect helper.")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host. Default: 0.0.0.0")
    parser.add_argument("--port", type=int, default=80, help="Bind port. Default: 80")
    parser.add_argument("--target-url", default=DEFAULT_TARGET_URL, help="PLUTO console URL.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run(args.host, args.port, args.target_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
