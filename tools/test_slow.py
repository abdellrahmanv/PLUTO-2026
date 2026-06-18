import serial
import time

ser = serial.Serial('COM8', 115200, timeout=1)
time.sleep(0.5)
print("Sending slow move (200 steps @ 20 sps)...")
ser.write(b'CMD:ARM:200,20\n')

start = time.time()
while time.time() - start < 12:
    line = ser.readline().decode(errors="replace").strip()
    if line:
        print(f"  RX: {line}")
        if "ARM_DONE" in line:
            break
ser.close()
print("Done.")
