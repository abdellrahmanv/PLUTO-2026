# Feature Memory: Deployment Wi-Fi Captive Portal

Status: repo implementation added, awaiting Raspberry Pi field validation

Last updated: 2026-06-18

Last validated: 2026-06-18 repo smoke test only; not yet validated on Raspberry Pi network hardware

Owner: Pi / deployment

## Requirement Trace

Implemented requirements:

```text
WEB-027
WEB-SAFE-005
```

Verification tests:

```text
VER-WEB-012
```

## Design Intent

Final deployment should feel like joining a dedicated PLUTO operations network.
When an operator connects to the Raspberry Pi Wi-Fi network, the device should
open or redirect to the PLUTO website in the same style as campus or university
Wi-Fi login pages.

## Design Decision

The repo now includes an installable Raspberry Pi deployment path. The installer
configures the web shell as a boot service, configures the Pi Wi-Fi interface as
an access point, serves DHCP/DNS for joined devices, and runs a small captive
portal redirect helper on port 80.

The captive portal is only a navigation helper. It must not grant motion
authority, bypass any configured authentication, or bypass mode-manager and
STM32 safety gates.

## Interfaces

Inputs:

- Operator phone/tablet/laptop joins the PLUTO Wi-Fi network.
- Captive portal detection request from the client operating system.

Outputs:

- Browser opens or redirects to the PLUTO operator website.
- Motion controls remain governed by the normal website, mode manager, and STM32.

External dependencies:

- Raspberry Pi access point service.
- DNS/HTTP captive portal redirect service.
- PLUTO web shell running on the Raspberry Pi.

Repo artifacts:

- `DEPLOY_RASPBERRY_PI_WIFI.md`
- `deploy/raspberry_pi/install_pluto_wifi_portal.sh`
- `deploy/raspberry_pi/systemd/*.service`
- `deploy/raspberry_pi/hostapd.conf.in`
- `deploy/raspberry_pi/dnsmasq.conf.in`
- `pluto_runtime/captive_portal.py`
- `tools/pi_deployment_smoke.py`

## Runtime Behavior

During final deployment, the Raspberry Pi should advertise the robot operations
network. A newly joined device should land on the PLUTO website automatically or
through the operating system's captive portal prompt. If the portal fails, the
operator must still be able to open the website manually by Pi IP or hostname.

## Expected Evidence

```text
Phone/tablet joins PLUTO Wi-Fi -> captive portal appears -> PLUTO website loads
without external internet -> emergency stop remains visible -> unsafe mode
requests remain blocked.
```

## Verification Tests

| Test ID | Method | Expected Result | Last Result |
| --- | --- | --- | --- |
| VER-WEB-012 | Join Raspberry Pi deployment Wi-Fi from phone/tablet | PLUTO website auto-opens or redirects; motion authority is not granted by join alone | not run |
| VER-WEB-012A | Run `python3 tools/pi_deployment_smoke.py` | Captive portal assets exist and local redirect helper handles probe URLs | PASS on repo smoke, 2026-06-18 |

## Failure Modes

| Failure | Likely Cause | Diagnostic | Recovery |
| --- | --- | --- | --- |
| Portal does not open | Client OS captive portal probe not intercepted | Check DNS/HTTP redirect logs | Open website manually and fix portal service |
| Website opens but controls fail | Web shell/API not running | Check `/healthz` | Restart PLUTO web shell |
| Portal grants too much access | Incorrect auth/control gating | Try unsafe mode request before validation | Keep safety gate in mode manager and STM32 |

## Safety Notes

Captive portal auto-open is not a control authorization mechanism. Joining Wi-Fi
must never move the robot, enter a motion mode, clear ERROR, or bypass e-stop.

## Open Questions

- What final SSID name should the robot advertise?
- Should deployment require a password or local operator PIN?
- Should the tablet face and operator console use separate portal landing pages?

## Change History

| Date | Change | Reason |
| --- | --- | --- |
| 2026-06-08 | Added deployment captive-portal requirement memory | User requested final Raspberry Pi Wi-Fi auto-open behavior |
| 2026-06-18 | Added systemd/AP/DNS/captive portal installer and smoke test | Prepare repo before Raspberry Pi field install |
