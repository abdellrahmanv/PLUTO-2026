#!/usr/bin/env python3
"""Quick test: send PING to verify firmware is alive, then move motor."""
import serial, time

ser = serial.Serial('COM8', 115200, timeout=0.5)
time.sleep(1.5)  # wait for USB CDC + boot blinks
ser.reset_input_buffer()

# 1. Verify firmware is alive
print("=== FIRMWARE CHECK ===")
ser.write(b"CMD:PING\n")
start = time.monotonic()
while time.monotonic() - start < 2:
    line = ser.readline().decode(errors="replace").strip()
    if line:
        print(f"  RX: {line}")
        if "ACK:PING" in line:
            print("  -> Firmware is alive!")
            break
else:
    print("  -> No PING response! Firmware may not be running.")
    ser.close()
    exit(1)

# 2. Drain any leftover boot messages
time.sleep(0.2)
ser.reset_input_buffer()

# 3. Run motor test - slow speed, lots of steps
print("\n=== MOTOR TEST ===")
print("Sending CMD:ARM:200,20 (200 steps, 20 sps, ~10 seconds)")
ser.write(b"CMD:ARM:200,20\n")
start = time.monotonic()
while time.monotonic() - start < 15:
    line = ser.readline().decode(errors="replace").strip()
    if line:
        elapsed = time.monotonic() - start
        print(f"  [{elapsed:.1f}s] {line}")
        if "ARM_DONE" in line:
            break

print("\n=== TEST COMPLETE ===")
ser.close()
