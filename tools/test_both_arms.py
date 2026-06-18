#!/usr/bin/env python3
"""Test both ARM1 and ARM2 stepper channels to check for pin mapping mismatch."""
import serial
import time

PORT = "COM8"
BAUD = 115200

print(f"Opening {PORT}...")
ser = serial.Serial(PORT, BAUD, timeout=0.1, write_timeout=0.5)
time.sleep(0.5)
ser.reset_input_buffer()

# 1. Test ARM1
print("\n[1] Testing ARM1 (PB8/PB9)...")
ser.write(b"CMD:ARM:400,2000\n")
start = time.monotonic()
while time.monotonic() - start < 6:
    line = ser.readline().decode(errors="replace").strip()
    if line and (line.startswith("ACK:") or line.startswith("ALERT:")):
        print(f"  [{time.monotonic()-start:.2f}s] {line}")
        if "ARM_DONE" in line:
            break

# 2. Test ARM2
print("\n[2] Testing ARM2 (PB12/PB13)...")
ser.write(b"CMD:ARM2:400,2000\n")
start = time.monotonic()
while time.monotonic() - start < 6:
    line = ser.readline().decode(errors="replace").strip()
    if line and (line.startswith("ACK:") or line.startswith("ALERT:")):
        print(f"  [{time.monotonic()-start:.2f}s] {line}")
        if "ARM2_DONE" in line:
            break

ser.close()
print("\nTest completed.")
