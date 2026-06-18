import serial, time

ser = serial.Serial('COM8', 115200, timeout=0.1)
time.sleep(0.5)
ser.reset_input_buffer()

print("=== FINAL MOTOR TEST ===")
print("Sending CMD:ARM:200,20 (200 steps, 20 sps, ~10 seconds)")
ser.write(b"CMD:ARM:200,20\n")

start = time.time()
while time.time() - start < 15:
    line = ser.readline().decode(errors="replace").strip()
    if line and ("ACK" in line):
        print(f"  [{time.time()-start:.1f}s] {line}")
        if "ARM_DONE" in line:
            break

ser.close()
print("=== TEST COMPLETE ===")
