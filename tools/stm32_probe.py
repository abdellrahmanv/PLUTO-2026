#!/usr/bin/env python3
"""
Pluto Phase 1 STM32 serial validation probe.

This tool is intentionally narrow:
- find the STM32 motor/safety controller without assuming /dev/ttyACM0
- prove CMD:PING -> ACK:PING timing
- prove CMD:STOP is accepted
- prove TEL: and OBS: lines are visible

It never sends movement commands.
"""

from __future__ import annotations

import argparse
import glob
import json
import platform
import sys
import time
from dataclasses import dataclass, field
from typing import Iterable


STM32_ID = "ID:STM32_MOTOR"
PING_COMMAND = "CMD:PING"
STOP_COMMAND = "CMD:STOP"
PING_ACK = "ACK:PING"
STOP_ACK = "ACK:STOP"


@dataclass
class PingResult:
    ok: bool
    latency_ms: float | None
    lines: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class ProbeResult:
    port: str | None = None
    detected: bool = False
    identity_line: str | None = None
    ping_results: list[PingResult] = field(default_factory=list)
    stop_ack: bool = False
    tel_line: str | None = None
    obs_line: str | None = None
    scanned_ports: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def pass_phase_1(self) -> bool:
        return (
            self.detected
            and bool(self.ping_results)
            and all(p.ok for p in self.ping_results)
            and self.stop_ack
            and self.tel_line is not None
            and self.obs_line is not None
            and not self.failures
        )


def import_serial():
    try:
        import serial  # type: ignore
        from serial.tools import list_ports  # type: ignore
    except ImportError as exc:
        print("ERROR: pyserial is not installed.", file=sys.stderr)
        print("Install it with: python3 -m pip install pyserial", file=sys.stderr)
        raise SystemExit(3) from exc
    return serial, list_ports


def unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def candidate_ports(explicit_port: str | None = None) -> list[str]:
    if explicit_port:
        return [explicit_port]

    _, list_ports = import_serial()
    ports = [p.device for p in list_ports.comports()]

    system = platform.system().lower()
    if system == "linux":
        ports.extend(glob.glob("/dev/ttyACM*"))
        ports.extend(glob.glob("/dev/ttyUSB*"))
        ports.extend(glob.glob("/dev/serial/by-id/*"))
    elif system == "darwin":
        ports.extend(glob.glob("/dev/tty.usbmodem*"))
        ports.extend(glob.glob("/dev/tty.usbserial*"))
    elif system == "windows" and not ports:
        ports.extend(f"COM{i}" for i in range(1, 33))

    return unique(ports)


def open_serial(port: str, baud: int):
    serial, _ = import_serial()
    return serial.Serial(
        port=port,
        baudrate=baud,
        timeout=0.02,
        write_timeout=0.2,
        rtscts=False,
        dsrdtr=False,
    )


def write_command(ser, command: str) -> None:
    ser.write((command.strip() + "\n").encode("ascii"))
    ser.flush()


def read_line(ser) -> str | None:
    raw = ser.readline()
    if not raw:
        return None
    return raw.decode("utf-8", errors="replace").strip()


def drain_input(ser, seconds: float = 0.15) -> list[str]:
    deadline = time.monotonic() + seconds
    lines: list[str] = []
    while time.monotonic() < deadline:
        line = read_line(ser)
        if line:
            lines.append(line)
    return lines


def is_stm32_line(line: str) -> bool:
    return (
        line == STM32_ID
        or line == PING_ACK
        or line.startswith("TEL:")
        or line.startswith("OBS:")
        or line.startswith("ALERT:")
    )


def send_ping_and_measure(ser, timeout_ms: int) -> PingResult:
    lines: list[str] = []
    try:
        drain_input(ser, 0.05)
        started = time.monotonic()
        write_command(ser, PING_COMMAND)
        deadline = started + timeout_ms / 1000.0

        while time.monotonic() <= deadline:
            line = read_line(ser)
            if not line:
                continue
            lines.append(line)
            if line == PING_ACK:
                latency_ms = (time.monotonic() - started) * 1000.0
                return PingResult(True, latency_ms, lines)

        return PingResult(False, None, lines, f"missing {PING_ACK} within {timeout_ms} ms")
    except Exception as exc:  # noqa: BLE001 - hardware probe must report exact failure
        return PingResult(False, None, lines, str(exc))


def wait_for_lines(ser, seconds: float, heartbeat_interval_s: float = 0.5) -> list[str]:
    deadline = time.monotonic() + seconds
    next_ping = time.monotonic() + heartbeat_interval_s
    lines: list[str] = []

    while time.monotonic() < deadline:
        now = time.monotonic()
        if now >= next_ping:
            try:
                write_command(ser, PING_COMMAND)
            except Exception:
                pass
            next_ping = now + heartbeat_interval_s

        line = read_line(ser)
        if line:
            lines.append(line)

    return lines


def probe_port(port: str, baud: int, probe_timeout_s: float, ping_timeout_ms: int) -> tuple[bool, str | None, PingResult | None, list[str], str | None]:
    try:
        with open_serial(port, baud) as ser:
            time.sleep(0.25)
            lines = drain_input(ser, 0.2)
            first_identity = next((line for line in lines if is_stm32_line(line)), None)

            ping = send_ping_and_measure(ser, ping_timeout_ms)
            lines.extend(ping.lines)
            if ping.ok:
                return True, PING_ACK, ping, lines, None

            more_lines = wait_for_lines(ser, max(0.1, probe_timeout_s - 0.45))
            lines.extend(more_lines)
            identity = first_identity or next((line for line in lines if is_stm32_line(line)), None)
            return identity is not None, identity, ping, lines, None
    except Exception as exc:  # noqa: BLE001 - hardware probe must continue scanning
        return False, None, None, [], str(exc)


def validate_stm32(
    port: str,
    baud: int,
    ping_count: int,
    ping_timeout_ms: int,
    telemetry_timeout_s: float,
) -> ProbeResult:
    result = ProbeResult(port=port, detected=True)

    try:
        with open_serial(port, baud) as ser:
            time.sleep(0.25)
            boot_lines = drain_input(ser, 0.3)
            result.identity_line = next((line for line in boot_lines if is_stm32_line(line)), STM32_ID)

            try:
                write_command(ser, STOP_COMMAND)
            except Exception as exc:  # noqa: BLE001
                result.failures.append(f"Failed to send {STOP_COMMAND}: {exc}")
            stop_deadline = time.monotonic() + 0.5
            while time.monotonic() < stop_deadline:
                line = read_line(ser)
                if not line:
                    continue
                if line == STOP_ACK:
                    result.stop_ack = True
                    break
                if line.startswith("TEL:") and result.tel_line is None:
                    result.tel_line = line
                if line.startswith("OBS:") and result.obs_line is None:
                    result.obs_line = line

            if not result.stop_ack:
                result.failures.append(f"Missing {STOP_ACK} after {STOP_COMMAND}")

            for _ in range(ping_count):
                ping = send_ping_and_measure(ser, ping_timeout_ms)
                result.ping_results.append(ping)
                if not ping.ok:
                    result.failures.append(ping.error or f"Missing {PING_ACK}")
                time.sleep(0.5)

            lines = wait_for_lines(ser, telemetry_timeout_s)
            for line in lines:
                if line.startswith("TEL:") and result.tel_line is None:
                    result.tel_line = line
                if line.startswith("OBS:") and result.obs_line is None:
                    result.obs_line = line

            if result.tel_line is None:
                result.failures.append("Missing TEL: telemetry line")
            if result.obs_line is None:
                result.failures.append("Missing OBS: obstacle line")

            try:
                write_command(ser, STOP_COMMAND)
            except Exception as exc:  # noqa: BLE001
                result.warnings.append(f"Final safety STOP failed: {exc}")

    except Exception as exc:  # noqa: BLE001
        result.detected = False
        result.failures.append(f"Failed to validate STM32 on {port}: {exc}")

    return result


def find_stm32(args) -> ProbeResult:
    ports = candidate_ports(args.port)
    result = ProbeResult(scanned_ports=ports)

    if not ports:
        result.failures.append("No serial ports found")
        return result

    for port in ports:
        detected, identity, ping, lines, error = probe_port(
            port,
            args.baud,
            args.probe_timeout,
            args.ping_timeout_ms,
        )
        if error:
            result.warnings.append(f"{port}: {error}")
            continue

        if detected:
            validated = validate_stm32(
                port,
                args.baud,
                args.ping_count,
                args.ping_timeout_ms,
                args.telemetry_timeout,
            )
            validated.scanned_ports = ports
            validated.identity_line = validated.identity_line or identity
            return validated

        if lines:
            preview = "; ".join(lines[:3])
            result.warnings.append(f"{port}: not STM32, saw: {preview}")
        else:
            result.warnings.append(f"{port}: no recognizable STM32 response")

    result.failures.append("STM32 motor controller was not detected")
    return result


def result_to_dict(result: ProbeResult) -> dict:
    return {
        "pass": result.pass_phase_1,
        "port": result.port,
        "detected": result.detected,
        "identity_line": result.identity_line,
        "ping_results": [
            {
                "ok": p.ok,
                "latency_ms": p.latency_ms,
                "error": p.error,
                "lines": p.lines,
            }
            for p in result.ping_results
        ],
        "stop_ack": result.stop_ack,
        "tel_line": result.tel_line,
        "obs_line": result.obs_line,
        "scanned_ports": result.scanned_ports,
        "warnings": result.warnings,
        "failures": result.failures,
    }


def print_human(result: ProbeResult) -> None:
    print("PLUTO PHASE 1 - STM32 SERIAL VALIDATION")
    print("=" * 44)
    print(f"Scanned ports: {', '.join(result.scanned_ports) if result.scanned_ports else 'none'}")
    print(f"STM32 port:    {result.port or 'not found'}")
    print(f"Identity:      {result.identity_line or 'missing'}")
    print(f"STOP ACK:      {'PASS' if result.stop_ack else 'FAIL'}")
    print(f"TEL line:      {result.tel_line or 'missing'}")
    print(f"OBS line:      {result.obs_line or 'missing'}")

    if result.ping_results:
        print("PING timing:")
        for index, ping in enumerate(result.ping_results, start=1):
            if ping.ok:
                print(f"  {index}. PASS {ping.latency_ms:.1f} ms")
            else:
                print(f"  {index}. FAIL {ping.error}")
    else:
        print("PING timing:   not run")

    if result.warnings:
        print("Warnings:")
        for warning in result.warnings:
            print(f"  - {warning}")

    if result.failures:
        print("Failures:")
        for failure in result.failures:
            print(f"  - {failure}")

    print("=" * 44)
    print(f"PHASE 1 RESULT: {'PASS' if result.pass_phase_1 else 'FAIL'}")

    if not result.pass_phase_1:
        print("Next checks:")
        print("  1. Confirm Black Pill USB is connected to the Pi/laptop.")
        print("  2. Confirm firmware is running and heartbeat LED is visible.")
        print("  3. Confirm USB CDC exists as a serial port.")
        print("  4. Run again with --port <device> if auto-scan finds the wrong device.")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Pluto STM32 motor controller serial link.")
    parser.add_argument("--port", help="Serial port to test directly, for example /dev/ttyACM0 or COM7.")
    parser.add_argument("--baud", type=int, default=115200, help="Serial baud rate. Default: 115200.")
    parser.add_argument("--probe-timeout", type=float, default=2.0, help="Seconds to probe each serial port.")
    parser.add_argument("--ping-count", type=int, default=5, help="Number of timed CMD:PING tests.")
    parser.add_argument("--ping-timeout-ms", type=int, default=100, help="Maximum allowed ACK:PING latency.")
    parser.add_argument("--telemetry-timeout", type=float, default=2.0, help="Seconds to wait for TEL: and OBS:.")
    parser.add_argument("--list", action="store_true", help="List candidate serial ports and exit.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON result.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    if args.list:
        for port in candidate_ports(args.port):
            print(port)
        return 0

    result = find_stm32(args)

    if args.json:
        print(json.dumps(result_to_dict(result), indent=2))
    else:
        print_human(result)

    return 0 if result.pass_phase_1 else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
