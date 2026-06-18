# FAST RUN

Fast path for starting the PLUTO Raspberry Pi website.

## 1. Connect to the Pi

```bash
ssh pi@192.168.137.2
```

## 2. Repair or Update the Repo

```bash
cd /home/pi/PLUTO-2026
git fetch origin
git checkout arch/v2-real
git pull --ff-only
```

If Git is broken or says local files block the pull, use this clean repair:

```bash
cd /home/pi
mv PLUTO-2026 "PLUTO-2026.backup.$(date +%Y%m%d-%H%M%S)"
git clone --branch arch/v2-real https://github.com/abdellrahmanv/PLUTO-2026.git PLUTO-2026
```

## 3. Start the Website

Foreground mode:

```bash
cd /home/pi/PLUTO-2026
/home/pi/yolo/env/bin/python -m pluto_runtime.web_shell --host 0.0.0.0 --port 8080
```

Background mode:

```bash
cd /home/pi/PLUTO-2026
kill "$(cat /tmp/pluto_web.pid)" 2>/dev/null || true
: > /tmp/pluto_web.log
nohup /home/pi/yolo/env/bin/python -m pluto_runtime.web_shell --host 0.0.0.0 --port 8080 >> /tmp/pluto_web.log 2>&1 < /dev/null &
echo $! > /tmp/pluto_web.pid
```

## 4. Open the Website

```text
http://192.168.137.2:8080
```

## 5. Verify

```bash
ss -ltnp | grep 8080
curl -s http://127.0.0.1:8080/api/status | head
tail -f /tmp/pluto_web.log
```

## 6. Stop

```bash
kill "$(cat /tmp/pluto_web.pid)" 2>/dev/null || true
```

## 7. Manual NEMA Test

From the website:

1. Select `MANUAL`.
2. Use Arm 1.
3. Test with:

```text
steps = 5000
speed = 800
accel = 0
```

Expected command:

```text
CMD:ARM:5000,800
```

Expected replies:

```text
ACK:ARM
ACK:ARM_DONE
```

If the ACKs happen but the NEMA does not move, debug hardware first: TB6600 power, common ground, PUL/DIR/ENA wiring, DIP switches, motor coil pairs, and flashed STM32 firmware.
