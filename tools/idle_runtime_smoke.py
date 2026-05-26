#!/usr/bin/env python3
"""Smoke test for Phase 6 IDLE STM32 heartbeat runtime."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pluto_runtime.stm32_link import Stm32SerialLink, parse_obs_line, parse_tel_line
from pluto_runtime.web_shell import candidate_ports, probe_stm32


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Phase 6 IDLE STM32 runtime.")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--duration", type=float, default=3.0)
    parser.add_argument("--port", help="Explicit STM32 serial port.")
    parser.add_argument("--require-hardware", action="store_true", help="Fail if STM32 is not found.")
    return parser.parse_args()


def parser_self_test() -> None:
    tel = parse_tel_line("TEL:BAT:38.1,SPD:0.0,DIST:12,TEMP:24.5")
    obs = parse_obs_line("OBS:FL:80,F:120,FR:95")
    assert tel["BAT"] == 38.1
    assert tel["SPD"] == 0.0
    assert obs["FL"] == 80.0
    assert obs["FR"] == 95.0


def main() -> int:
    args = parse_args()
    parser_self_test()

    port = args.port
    if not port:
        stm32 = probe_stm32(candidate_ports(), args.baud)
        if stm32.connected:
            port = stm32.port

    if not port:
        message = "IDLE_RUNTIME_SMOKE SKIP: STM32 not found"
        if args.require_hardware:
            print(message)
            return 1
        print(message)
        return 0

    link = Stm32SerialLink(port=port, baud=args.baud, heartbeat_interval_s=0.4)
    link.start()
    try:
        deadline = time.monotonic() + args.duration
        while time.monotonic() < deadline:
            time.sleep(0.1)
        status = link.get_status()
    finally:
        link.stop()

    assert status.ping_count >= 2, f"expected heartbeat pings, got {status.ping_count}"
    assert status.ack_ping_count >= 1, f"expected ACK:PING, got {status.ack_ping_count}"
    assert status.stop_count >= 1, "expected startup CMD:STOP guard"
    if status.last_ping_latency_ms is not None:
        assert status.last_ping_latency_ms <= 100.0, f"ping latency too high: {status.last_ping_latency_ms:.1f} ms"

    print(
        "IDLE_RUNTIME_SMOKE PASS "
        f"port={port} ping={status.ping_count} ack={status.ack_ping_count} "
        f"latency_ms={status.last_ping_latency_ms}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
