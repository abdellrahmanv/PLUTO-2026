import serial
import time

ser = serial.Serial('COM8', 115200, timeout=1)
time.sleep(1.5)
ser.reset_input_buffer()

# 5000 steps at 800 sps will take 6.25 seconds
print("Sending long move (5000 steps @ 800 sps)...")
ser.write(b'CMD:ARM:5000,2000\n')

start = time.time()
while time.time() - start < 10:
    line = ser.readline().decode(errors="replace").strip()
    if line:
        print(f"  RX: {line}")
        if "ARM_DONE" in line:
            break
ser.close()
print("Done.")
