#!/usr/bin/env python3
"""
Pluto Phase 2 Uno/LCD serial validation probe.

This tool proves the Raspberry Pi can identify and command the LCD/face
controller. It is safe by design: it never talks to STM32 and never sends motor
commands.
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


UNO_ID = "ID:UNO_LCD"
IDENTITY_COMMANDS = ("ID?", "PING")
COMMAND_SEQUENCE = (
    ("MODE:BOOT", ("ACK:MODE", "ACK:MODE:BOOT")),
    ("FACE:IDLE", ("ACK:FACE", "ACK:FACE:IDLE")),
    ("FACE:HAPPY", ("ACK:FACE", "ACK:FACE:HAPPY")),
    ("FACE:THINKING", ("ACK:FACE", "ACK:FACE:THINKING")),
    ("TEXT:PLUTO PHASE 2", ("ACK:TEXT", "ACK:TEXT:PLUTO PHASE 2")),
    ("MODE:IDLE", ("ACK:MODE", "ACK:MODE:IDLE")),
)


@dataclass
class CommandResult:
    command: str
    ok: bool
    ack_line: str | None = None
    latency_ms: float | None = None
    lines: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class UnoProbeResult:
    port: str | None = None
    detected: bool = False
    identity_line: str | None = None
    command_results: list[CommandResult] = field(default_factory=list)
    scanned_ports: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def pass_phase_2(self) -> bool:
        return (
            self.detected
            and self.identity_line == UNO_ID
            and bool(self.command_results)
            and all(item.ok for item in self.command_results)
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


def drain_input(ser, seconds: float = 0.2) -> list[str]:
    deadline = time.monotonic() + seconds
    lines: list[str] = []
    while time.monotonic() < deadline:
        line = read_line(ser)
        if line:
            lines.append(line)
    return lines


def is_uno_line(line: str) -> bool:
    return line == UNO_ID or line.startswith("ACK:FACE") or line.startswith("ACK:MODE") or line.startswith("ACK:TEXT")


def wait_for_identity(ser, timeout_s: float) -> tuple[str | None, list[str]]:
    lines = drain_input(ser, min(0.5, timeout_s))
    identity = next((line for line in lines if line == UNO_ID), None)
    if identity:
        return identity, lines

    deadline = time.monotonic() + timeout_s
    for command in IDENTITY_COMMANDS:
        try:
            write_command(ser, command)
        except Exception:
            pass

        while time.monotonic() < deadline:
            line = read_line(ser)
            if not line:
                continue
            lines.append(line)
            if line == UNO_ID:
                return line, lines
            if is_uno_line(line):
                return UNO_ID, lines

    return None, lines


def send_command_and_wait(ser, command: str, expected_acks: tuple[str, ...], timeout_ms: int) -> CommandResult:
    lines: list[str] = []
    try:
        drain_input(ser, 0.05)
        started = time.monotonic()
        write_command(ser, command)
        deadline = started + timeout_ms / 1000.0

        while time.monotonic() <= deadline:
            line = read_line(ser)
            if not line:
                continue
            lines.append(line)
            if line in expected_acks or line == f"ACK:{command}" or line == f"ACK:{command.split(':', 1)[0]}":
                return CommandResult(
                    command=command,
                    ok=True,
                    ack_line=line,
                    latency_ms=(time.monotonic() - started) * 1000.0,
                    lines=lines,
                )
            if line.startswith("ERR:") or line.startswith("ERROR:"):
                return CommandResult(command=command, ok=False, ack_line=line, lines=lines, error=line)

        return CommandResult(
            command=command,
            ok=False,
            lines=lines,
            error=f"missing ACK for {command} within {timeout_ms} ms",
        )
    except Exception as exc:  # noqa: BLE001 - hardware probe must report exact failure
        return CommandResult(command=command, ok=False, lines=lines, error=str(exc))


def probe_port(port: str, baud: int, probe_timeout_s: float) -> tuple[bool, str | None, list[str], str | None]:
    try:
        with open_serial(port, baud) as ser:
            time.sleep(1.8)  # Uno resets when USB serial opens.
            identity, lines = wait_for_identity(ser, probe_timeout_s)
            return identity == UNO_ID, identity, lines, None
    except Exception as exc:  # noqa: BLE001 - hardware probe must continue scanning
        return False, None, [], str(exc)


def validate_uno(port: str, baud: int, command_timeout_ms: int) -> UnoProbeResult:
    result = UnoProbeResult(port=port, detected=True, identity_line=UNO_ID)

    try:
        with open_serial(port, baud) as ser:
            time.sleep(1.8)
            identity, lines = wait_for_identity(ser, 2.0)
            if identity != UNO_ID:
                result.detected = False
                result.identity_line = identity
                result.failures.append("Uno identity was not confirmed during validation")
                if lines:
                    result.warnings.append("Validation saw: " + "; ".join(lines[:5]))
                return result

            result.identity_line = identity
            for command, expected in COMMAND_SEQUENCE:
                item = send_command_and_wait(ser, command, expected, command_timeout_ms)
                result.command_results.append(item)
                if not item.ok:
                    result.failures.append(item.error or f"{command} was not acknowledged")
                time.sleep(0.1)

    except Exception as exc:  # noqa: BLE001
        result.detected = False
        result.failures.append(f"Failed to validate Uno on {port}: {exc}")

    return result


def find_uno(args) -> UnoProbeResult:
    ports = candidate_ports(args.port)
    result = UnoProbeResult(scanned_ports=ports)

    if not ports:
        result.failures.append("No serial ports found")
        return result

    for port in ports:
        detected, identity, lines, error = probe_port(port, args.baud, args.probe_timeout)
        if error:
            result.warnings.append(f"{port}: {error}")
            continue

        if detected:
            validated = validate_uno(port, args.baud, args.command_timeout_ms)
            validated.scanned_ports = ports
            return validated

        if lines:
            preview = "; ".join(lines[:3])
            result.warnings.append(f"{port}: not Uno LCD, saw: {preview}")
        else:
            result.warnings.append(f"{port}: no recognizable Uno LCD response")

    result.failures.append("Uno LCD controller was not detected")
    return result


def result_to_dict(result: UnoProbeResult) -> dict:
    return {
        "pass": result.pass_phase_2,
        "port": result.port,
        "detected": result.detected,
        "identity_line": result.identity_line,
        "command_results": [
            {
                "command": item.command,
                "ok": item.ok,
                "ack_line": item.ack_line,
                "latency_ms": item.latency_ms,
                "lines": item.lines,
                "error": item.error,
            }
            for item in result.command_results
        ],
        "scanned_ports": result.scanned_ports,
        "warnings": result.warnings,
        "failures": result.failures,
    }


def print_human(result: UnoProbeResult) -> None:
    print("PLUTO PHASE 2 - UNO LCD SERIAL VALIDATION")
    print("=" * 45)
    print(f"Scanned ports: {', '.join(result.scanned_ports) if result.scanned_ports else 'none'}")
    print(f"Uno port:      {result.port or 'not found'}")
    print(f"Identity:      {result.identity_line or 'missing'}")

    if result.command_results:
        print("Commands:")
        for item in result.command_results:
            if item.ok:
                print(f"  {item.command:<20} PASS {item.latency_ms:.1f} ms ({item.ack_line})")
            else:
                print(f"  {item.command:<20} FAIL {item.error}")
    else:
        print("Commands:      not run")

    if result.warnings:
        print("Warnings:")
        for warning in result.warnings:
            print(f"  - {warning}")

    if result.failures:
        print("Failures:")
        for failure in result.failures:
            print(f"  - {failure}")

    print("=" * 45)
    print(f"PHASE 2 RESULT: {'PASS' if result.pass_phase_2 else 'FAIL'}")

    if not result.pass_phase_2:
        print("Next checks:")
        print("  1. Confirm the Uno is connected by USB.")
        print("  2. Confirm the Uno firmware prints ID:UNO_LCD on boot or ID? command.")
        print("  3. Confirm commands return ACK:MODE, ACK:FACE, and ACK:TEXT.")
        print("  4. Run again with --port <device> if auto-scan finds the wrong device.")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Pluto Uno LCD controller serial link.")
    parser.add_argument("--port", help="Serial port to test directly, for example /dev/ttyACM1 or COM8.")
    parser.add_argument("--baud", type=int, default=115200, help="Serial baud rate. Default: 115200.")
    parser.add_argument("--probe-timeout", type=float, default=3.0, help="Seconds to probe each serial port.")
    parser.add_argument("--command-timeout-ms", type=int, default=500, help="Maximum allowed command ACK latency.")
    parser.add_argument("--list", action="store_true", help="List candidate serial ports and exit.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON result.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    if args.list:
        for port in candidate_ports(args.port):
            print(port)
        return 0

    result = find_uno(args)

    if args.json:
        print(json.dumps(result_to_dict(result), indent=2))
    else:
        print_human(result)

    return 0 if result.pass_phase_2 else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
