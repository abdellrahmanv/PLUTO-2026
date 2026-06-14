# Run PLUTO Website on Raspberry Pi

Use this when the Pi is connected by LAN or Wi-Fi and you want the PLUTO website open fast.

## Default Address

Current lab LAN address:

```text
http://192.168.137.2:8080
```

If the Pi IP changes, run this on the Pi:

```bash
hostname -I
```

Then open:

```text
http://<PI_IP>:8080
```

## Fast Start

SSH into the Pi:

```bash
ssh pi@192.168.137.2
```

Go to the repo and start the website:

```bash
cd /home/pi/PLUTO-2026
/home/pi/yolo/env/bin/python -m pluto_runtime.web_shell --host 0.0.0.0 --port 8080
```

Leave that terminal open. The website stops when this command stops.

## Start in Background

Use this when you want the website to keep running after closing the SSH terminal:

```bash
cd /home/pi/PLUTO-2026
kill "$(cat /tmp/pluto_web.pid)" 2>/dev/null || true
: > /tmp/pluto_web.log
nohup /home/pi/yolo/env/bin/python -m pluto_runtime.web_shell --host 0.0.0.0 --port 8080 >> /tmp/pluto_web.log 2>&1 < /dev/null &
echo $! > /tmp/pluto_web.pid
```

Then open:

```text
http://192.168.137.2:8080
```

## Check That It Is Really Running

```bash
ss -ltnp | grep 8080
curl -s http://127.0.0.1:8080/api/status | head
tail -f /tmp/pluto_web.log
```

## Stop Website

```bash
kill "$(cat /tmp/pluto_web.pid)" 2>/dev/null || true
```

## Update Code Before Running

Use the active architecture branch:

```bash
cd /home/pi/PLUTO-2026
git fetch origin
git checkout arch/v2-real
git pull --ff-only
```

If Git says local changes would be overwritten, save them first:

```bash
git stash push -u -m "pi backup before fast run"
git pull --ff-only
```

## Manual NEMA Test From Website

1. Open the website.
2. Select `MANUAL`.
3. Use Arm 1.
4. Start with:

```text
steps = 5000
speed = 800
accel = 0
```

Expected STM32 command:

```text
CMD:ARM:5000,800
```

Expected STM32 replies:

```text
ACK:ARM
ACK:ARM_DONE
```

If `ACK:ARM_DONE` appears but the motor does not move, the Pi and website are sending correctly. Check TB6600 wiring, motor power, common ground, DIP switches, and that the newest STM32 firmware is flashed.

## Important Serial Note

The STM32 is:

```text
/dev/ttyACM0
/dev/serial/by-id/usb-STMicroelectronics_STM32_Virtual_ComPort_3793324D3238-if00
```

The Arduino Uno LCD is usually:

```text
/dev/ttyACM1
```

Do not assume `/dev/ttyACM0` forever. Prefer the `/dev/serial/by-id/...` path when debugging.
