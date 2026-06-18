# Deploy PLUTO Raspberry Pi Wi-Fi Portal

This installs the final Raspberry Pi behavior:

- PLUTO website starts automatically on boot.
- Raspberry Pi advertises a PLUTO Wi-Fi network.
- Phones, tablets, and laptops that join the Wi-Fi are redirected to the PLUTO website.
- Motion authority still stays inside the website, mode manager, emergency stop, and STM32 safety gates.

## Default Network

```text
SSID: PLUTO-OPS
Password: pluto2026
Console: http://192.168.50.1:8080/
```

## Install On The Pi

From the repo root on the Raspberry Pi:

```bash
git pull --ff-only
sudo deploy/raspberry_pi/install_pluto_wifi_portal.sh
sudo reboot
```

After reboot, join `PLUTO-OPS` from a phone/tablet/laptop. The captive portal prompt should open the PLUTO console. If the prompt does not appear, open:

```text
http://192.168.50.1:8080/
```

## Start Immediately

Only use this when it is safe for the Pi Wi-Fi interface to become an access point immediately:

```bash
sudo deploy/raspberry_pi/install_pluto_wifi_portal.sh --start-now
```

If you are SSH-connected over the same Wi-Fi interface, `--start-now` can disconnect the session.

## Custom Settings

```bash
sudo deploy/raspberry_pi/install_pluto_wifi_portal.sh \
  --ssid PLUTO-OPS \
  --password pluto2026 \
  --iface wlan0 \
  --ap-ip 192.168.50.1
```

You can also pass:

```bash
PLUTO_PYTHON=/home/pi/yolo/env/bin/python
PLUTO_WEB_EXTRA_ARGS="--camera-disabled --wave-pose-disabled"
```

## Services

```text
pluto-web.service              runs pluto_runtime.web_shell on port 8080
pluto-ap-network.service       assigns the Pi access-point IP
pluto-hostapd.service          advertises the PLUTO Wi-Fi network
pluto-dnsmasq.service          provides DHCP and captive DNS
pluto-captive-portal.service   redirects port 80 portal probes to the console
```

Check status:

```bash
systemctl status pluto-web
systemctl status pluto-hostapd
systemctl status pluto-dnsmasq
systemctl status pluto-captive-portal
```

## Verify

On the Pi:

```bash
curl http://127.0.0.1:8080/healthz
curl -I http://192.168.50.1/generate_204
```

From a joined phone/tablet/laptop:

```text
Join Wi-Fi -> captive portal opens -> PLUTO Mission Control appears
```

Safety check:

```text
Joining Wi-Fi must not move the robot, clear ERROR, enter MANUAL, or bypass emergency stop.
```

## Repo Smoke Test

On a laptop or Pi:

```bash
python3 tools/pi_deployment_smoke.py
```
