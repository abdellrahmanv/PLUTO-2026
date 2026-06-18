#!/usr/bin/env python3
"""Diagnostic: send CMD:ARM and also read back emergStop state.
Also tests with raw GPIO toggle command if available."""
import serial
import time

PORT = "COM8"
BAUD = 115200

ser = serial.Serial(PORT, BAUD, timeout=0.1, write_timeout=0.5)
time.sleep(0.5)
ser.reset_input_buffer()

print("=" * 60)
print("STEP PULSE DIAGNOSTIC")
print("=" * 60)

# 1. Check emergency stop state
print("\n[1] Checking emergency stop (PB0) state...")
ser.write(b"CMD:PING\n")
time.sleep(0.5)

emerg_seen = False
while ser.in_waiting:
    line = ser.readline().decode(errors="replace").strip()
    if "ALERT" in line:
        print(f"  ALERT: {line}")
        if "EMERG" in line.upper():
            emerg_seen = True
    elif "ACK" in line:
        print(f"  ACK: {line}")

if not emerg_seen:
    print("  No emergency alert — PB0 seems OK")

# 2. Send ARM command with just 10 steps at speed 50 (should take 0.2s)
print("\n[2] Sending CMD:ARM:10,50 (10 steps only)...")
ser.write(b"CMD:ARM:10,50\n")
start = time.monotonic()

ack_arm = False
ack_done = False
alerts = []
while time.monotonic() - start < 5:
    line = ser.readline().decode(errors="replace").strip()
    if line:
        if line.startswith("ACK:"):
            elapsed = time.monotonic() - start
            print(f"  [{elapsed:.2f}s] {line}")
            if "ACK:ARM_DONE" in line:
                ack_done = True
            elif "ACK:ARM" in line:
                ack_arm = True
        elif line.startswith("ALERT:"):
            elapsed = time.monotonic() - start
            if line not in [a[1] for a in alerts]:  # dedupe
                alerts.append((elapsed, line))
                print(f"  [{elapsed:.2f}s] {line}")

if ack_done:
    elapsed_total = time.monotonic() - start
    print(f"\n  ARM_DONE received in {elapsed_total:.2f}s")
    expected = 10.0 / 50.0  # 0.2 seconds for 10 steps at 50 sps
    print(f"  Expected ~{expected:.2f}s for 10 steps at 50 sps")
    if elapsed_total > 1.0:
        print("  ⚠️  Took WAY too long — emergency stop may be interrupting!")
elif ack_arm:
    print("\n  ⚠️  Got ACK:ARM but no ARM_DONE within 5 seconds!")
else:
    print("\n  ❌ No ACK at all!")

# 3. Try sending a very fast burst — 5 steps at 500 sps
print("\n[3] Sending CMD:ARM:5,500 (5 fast steps)...")
ser.write(b"CMD:ARM:5,500\n")
start = time.monotonic()
while time.monotonic() - start < 3:
    line = ser.readline().decode(errors="replace").strip()
    if line and (line.startswith("ACK:") or line.startswith("ALERT:")):
        elapsed = time.monotonic() - start
        print(f"  [{elapsed:.2f}s] {line}")
        if "ARM_DONE" in line:
            break

# 4. Try negative direction
print("\n[4] Sending CMD:ARM:-10,50 (reverse direction)...")
ser.write(b"CMD:ARM:-10,50\n")
start = time.monotonic()
while time.monotonic() - start < 5:
    line = ser.readline().decode(errors="replace").strip()
    if line and (line.startswith("ACK:") or line.startswith("ALERT:")):
        elapsed = time.monotonic() - start
        print(f"  [{elapsed:.2f}s] {line}")
        if "ARM_DONE" in line:
            break

print("\n" + "=" * 60)
print("DIAGNOSIS:")
print("If ARM_DONE comes back in the expected time but motor")
print("doesn't move, the GPIO pin (PB8) is toggling but the") 
print("signal isn't reaching the TB6600 PUL+ input.")
print("")
print("Check your wiring:")
print("  STM32 PB8  →  TB6600 PUL+")
print("  STM32 GND  →  TB6600 PUL-")
print("  STM32 PB9  →  TB6600 DIR+")
print("  STM32 GND  →  TB6600 DIR-")
print("=" * 60)

ser.close()
