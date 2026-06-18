import serial
import time

ser = serial.Serial('COM8', 115200, timeout=1)
time.sleep(1.5)
ser.reset_input_buffer()

print("Sending fast move (1000 steps @ 500 sps)...")
ser.write(b'CMD:ARM:1000,500\n')

start = time.time()
while time.time() - start < 5:
    line = ser.readline().decode(errors="replace").strip()
    if line:
        print(f"  RX: {line}")
        if "ARM_DONE" in line:
            break
ser.close()
print("Done.")
