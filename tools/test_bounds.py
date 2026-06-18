#!/usr/bin/env python3
import time
import serial
import serial.tools.list_ports
import threading

def find_stm32_port():
    for port in serial.tools.list_ports.comports():
        text = f"{port.description} {port.hwid}".upper()
        if "0483:5740" in text or "STM" in text:
            return port.device
    raise SystemExit("STM32 serial port not found.")

def main():
    port = find_stm32_port()
    print(f"Opening {port} @ 115200")
    ser = serial.Serial(port, 115200, timeout=0.05, write_timeout=0.5)
    time.sleep(1.0)
    ser.reset_input_buffer()

    running = True
    def heartbeat():
        while running:
            try:
                ser.write(b"CMD:PING\n")
            except:
                pass
            time.sleep(0.25)
    
    t = threading.Thread(target=heartbeat, daemon=True)
    t.start()

    def run_test(cmd, expected_duration):
        print(f"\n--- Testing {cmd} ---")
        print(f"Expected time: ~{expected_duration:.2f} seconds")
        ser.reset_input_buffer()
        start = time.time()
        ser.write((cmd + "\n").encode())
        
        while True:
            line = ser.readline().decode(errors="replace").strip()
            if "ACK:ARM_DONE" in line:
                elapsed = time.time() - start
                print(f"Received ACK:ARM_DONE in {elapsed:.2f} seconds")
                break
            elif "ACK:ARM" in line:
                print("Received ACK:ARM")
            
            if time.time() - start > expected_duration + 5:
                print("Timeout waiting for ARM_DONE")
                break

    try:
        # Test 1: Exceeding max speed (5000, capped at 3000) -> 6000 steps / 3000 sps = 2.0s
        run_test("CMD:ARM:6000,5000", 2.0)
        time.sleep(0.5)
        
        # Test 2: Speed = 0 (defaults to 200) -> 600 steps / 200 sps = 3.0s
        run_test("CMD:ARM:-600,0", 3.0)
        time.sleep(0.5)
        
        # Test 3: Steps = 0 -> should return DONE immediately
        run_test("CMD:ARM:0,1000", 0.0)
        
    finally:
        running = False
        time.sleep(0.3)
        ser.close()

if __name__ == '__main__':
    main()
