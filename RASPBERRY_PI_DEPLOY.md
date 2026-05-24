# Raspberry Pi Deploy

This folder is the Raspberry Pi side of Pluto's first motor test.

It creates:

- A local website for manual motor control.
- A Flask backend that sends commands to the STM32 over USB serial.
- A WiFi hotspot so a phone/laptop can join Pluto directly.
- Install scripts for the Raspberry Pi.

Main app:

```text
raspberry_pi_deploy/app.py
```

Default website:

```text
http://10.42.0.1:8080
```

Default hotspot:

```text
SSID: Pluto-Motors
PASS: pluto1234
```

Important safety rule:

Test with the hoverboard lifted off the ground first.

