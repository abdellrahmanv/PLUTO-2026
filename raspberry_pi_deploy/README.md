# Pluto Raspberry Pi Deploy

This is Pluto's first Raspberry Pi motor test and manual control website.

## What It Does

- Starts a web server on port `8080`.
- Auto-detects the STM32 USB serial port.
- Sends `CMD:PING` heartbeat to keep the STM32 alive.
- Sends manual drive commands:

```text
CMD:DRIVE:<speed>,<steer>
CMD:STOP
CMD:RETURN
CMD:ARM:<steps>,<speed>
```

- Shows STM32 telemetry:

```text
ID:STM32_MOTOR
TEL:...
OBS:...
ALERT:...
ACK:...
```

## Install On Raspberry Pi

From the repo root on the Pi:

```bash
cd raspberry_pi_deploy
chmod +x install.sh setup_hotspot.sh run.sh auto_system.sh unauto_system.sh
./install.sh
```

## Start The Manual Website

```bash
./run.sh
```

Then open:

```text
http://<raspberry-pi-ip>:8080
```

## Create Pluto WiFi Hotspot

This uses NetworkManager `nmcli`.

```bash
sudo ./setup_hotspot.sh
```

Then connect your phone/laptop to:

```text
SSID: Pluto-Motors
PASS: pluto1234
```

Open:

```text
http://192.168.4.1:8080
```

## Run On Boot

The easiest way:

```bash
./auto_system.sh
```

After that, every time the Raspberry Pi powers on:

- The Pluto hotspot starts.
- The motors test website starts.
- You can join `Pluto-Motors` and open `http://192.168.4.1:8080`.

If the Pi still joins your normal WiFi after reboot, pull the latest code and
rerun auto mode:

```bash
git pull
cd raspberry_pi_deploy
chmod +x *.sh
./fix_now.sh
sudo reboot
```

After reboot, verify:

```bash
ip addr show wlan0
sudo systemctl status pluto-system
sudo journalctl -u pluto-system -n 80 --no-pager
```

`wlan0` should show `192.168.4.1`.

To undo auto-start and return the Pi to normal:

```bash
sudo ./unauto_system.sh
```

Manual systemd commands, if needed:

```bash
sudo systemctl enable pluto-motors-test
sudo systemctl start pluto-motors-test
```

Check status:

```bash
sudo systemctl status pluto-motors-test
```

## Safety

First tests must be done with the hoverboard wheels lifted off the ground.

The web app sends heartbeat pings. If the Pi dies or the app stops, the STM32 should stop the motors after its timeout.
