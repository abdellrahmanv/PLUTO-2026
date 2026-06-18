import serial
import time

PORT = "COM8"
BAUD = 115200

print(f"Opening {PORT}...")
ser = serial.Serial(PORT, BAUD, timeout=0.1, write_timeout=0.5)
time.sleep(0.5)
ser.reset_input_buffer()

print("=" * 60)
print("STEPPER MOTOR SPEED SWEEP TEST")
print("Press Ctrl+C to stop at any time.")
print("=" * 60)

# We will test speeds from 10 to 300 steps/second
speeds = [2000, 2250, 2500, 2750, 3000]
steps = 200  # 1 revolution at 1/2 step

try:
    for speed in speeds:
        print(f"\n>>> Testing speed: {speed} steps/sec <<<")
        
        # Move forward
        print(f"  Moving {steps} steps forward...")
        ser.write(f"CMD:ARM:{steps},{speed}\n".encode())
        
        start = time.time()
        arm_done = False
        # Calculate maximum expected time + 2s buffer
        timeout = (steps / speed) + 2.0
        
        while time.time() - start < timeout:
            line = ser.readline().decode(errors="replace").strip()
            if line:
                if "ARM_DONE" in line:
                    arm_done = True
                    print("  [OK] ARM1 finished forward move")
                    break
            time.sleep(0.01)
            
        time.sleep(0.5)
        
        # Move backward
        print(f"  Moving {steps} steps backward...")
        ser.write(f"CMD:ARM:{-steps},{speed}\n".encode())
        
        start = time.time()
        arm_done = False
        while time.time() - start < timeout:
            line = ser.readline().decode(errors="replace").strip()
            if line:
                if "ARM_DONE" in line:
                    arm_done = True
                    print("  [OK] ARM1 finished backward move")
                    break
            time.sleep(0.01)
            
        time.sleep(1.0)

except KeyboardInterrupt:
    print("\nStopping motor and exiting...")
    ser.write(b"CMD:STOP\n")
    
ser.close()
print("Sweep completed.")
