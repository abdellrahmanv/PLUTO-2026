#!/usr/bin/env python3
"""Local NEMA Arm 1 forward/reverse test for STM32 on Windows.

Keeps CMD:PING alive during motion so the STM32 safety timeout does not stop
the stepper halfway through the test.
"""

from __future__ import annotations

import argparse
import threading
import time

import serial
import serial.tools.list_ports


def find_stm32_port(preferred: str | None) -> str:
    if preferred:
        return preferred
    for port in serial.tools.list_ports.comports():
        text = f"{port.description} {port.hwid}".upper()
        if "0483:5740" in text or "STM" in text:
            return port.device
    raise SystemExit("STM32 serial port not found. Plug STM32 USB in and try again.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default=None, help="Example: COM8")
    parser.add_argument("--steps", type=int, default=5000)
    parser.add_argument("--speed", type=int, default=2000)
    parser.add_argument("--baud", type=int, default=115200)
    args = parser.parse_args()

    port = find_stm32_port(args.port)
    print(f"Opening {port} @ {args.baud}")
    print(f"Test: +{args.steps} steps then -{args.steps} steps at {args.speed} steps/s")
    print("Watch the motor now. Press Ctrl+C to stop.\n")

    ser = serial.Serial(port, args.baud, timeout=0.05, write_timeout=0.5)
    time.sleep(1.0)
    ser.reset_input_buffer()

    running = True

    def heartbeat() -> None:
        while running:
            try:
                ser.write(b"CMD:PING\n")
            except Exception as exc:
                print(f"PING_WRITE_ERROR: {exc}")
                return
            time.sleep(0.25)

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()

    def read_for(seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            line = ser.readline().decode(errors="replace").strip()
            if not line:
                continue
            if line.startswith(("ACK:", "ALERT:")):
                print(f"RX {line}")

    def move(steps: int) -> None:
        speed = max(2000, min(3000, args.speed))
        seconds = abs(steps) / speed + 1.5
        command = f"CMD:ARM:{steps},{speed}"
        print(f"SEND {command}")
        ser.write((command + "\n").encode())
        read_for(seconds)

    try:
        read_for(1.0)
        move(args.steps)
        time.sleep(0.5)
        move(-args.steps)
        print("\nTest complete.")
    finally:
        running = False
        time.sleep(0.3)
        ser.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
