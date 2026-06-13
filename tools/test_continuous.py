#!/usr/bin/env python3
"""Send continuous move commands to both stepper channels for hardware probing."""
import serial
import time
import sys

PORT = "COM8"
BAUD = 115200

try:
    print(f"Opening {PORT}...")
    ser = serial.Serial(PORT, BAUD, timeout=0.05, write_timeout=0.5)
except Exception as e:
    print(f"Error opening port: {e}")
    sys.exit(1)

time.sleep(0.5)
ser.reset_input_buffer()

print("=" * 60)
print("CONTINUOUS STEPPER MOTOR JOG TEST")
print("Press Ctrl+C to stop the test at any time.")
print("=" * 60)

direction = 1
steps = 800
speed = 200  # 200 steps/sec = 4 seconds per move

try:
    while True:
        target_steps = steps * direction
        print(f"\n>>> Command: ARM1 = {target_steps} steps, ARM2 = {target_steps} steps @ {speed} sps <<<")
        
        # Send move commands to both channels
        ser.write(f"CMD:ARM:{target_steps},{speed}\n".encode())
        ser.write(f"CMD:ARM2:{target_steps},{speed}\n".encode())
        
        # Wait for both completions
        arm1_done = False
        arm2_done = False
        timeout = time.monotonic() + 10.0  # 10s timeout safety
        
        while (not arm1_done or not arm2_done) and time.monotonic() < timeout:
            line = ser.readline().decode(errors="replace").strip()
            if line:
                if "ARM_DONE" in line:
                    arm1_done = True
                    print("  [OK] ARM1 finished move")
                elif "ARM2_DONE" in line:
                    arm2_done = True
                    print("  [OK] ARM2 finished move")
                elif "ALERT:" in line:
                    # Skip printing HOVERBOARD_ERROR to avoid console spam
                    if "HOVERBOARD" not in line:
                        print(f"  [ALERT] {line}")
            time.sleep(0.01)
            
        if time.monotonic() >= timeout:
            print("  [Warning] Timeout reached waiting for move completion!")
            
        # Swap direction and pause briefly before next move
        direction = -direction
        time.sleep(0.5)

except KeyboardInterrupt:
    print("\nStopping motors and exiting...")
    try:
        ser.write(b"CMD:STOP\n")
    except:
        pass
    ser.close()
    print("Test stopped.")
