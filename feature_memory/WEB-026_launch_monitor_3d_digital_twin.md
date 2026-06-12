# Feature Memory: Launch Monitor 3D Digital Twin

Status: implemented, local browser validated, awaiting Raspberry Pi validation

Last updated: 2026-06-09

Last validated: 2026-06-09 local browser render and smoke test

Owner: Pluto systems engineering

## Requirement Trace

Implemented requirements:

```text
SYS-011
WEB-012
WEB-026
WEB-SAFE-001
WEB-SAFE-002
```

Verification tests:

```text
VER-WEB-011
tools/web_shell_smoke.py
local browser WebGL render inspection
```

## Design Intent

The operator console should feel like a real launch and monitor unit, not a
generic dashboard. The 3D view must make Pluto's live state, heading, obstacle
envelope, sensor confidence, and robot body readable at a glance while keeping
all motion authority inside the existing safety gates.

## Design Decision

The launch monitor is implemented as a local Three.js module served by the
Python web shell. Runtime assets are local under `pluto_runtime/static`, so the
view can load during Raspberry Pi deployment without depending on an external
CDN.

The view loads the Simulink/ROS robot STL meshes from
`C:\Users\Asus\Downloads\gradsimulink\my_robot\meshes`, copied into
`pluto_runtime/static/robot_meshes`. ROS mesh coordinates are converted into
Three.js coordinates, and each CAD part uses its URDF-style origin and `rpy`
rotation so the base, wheels, and arms sit in the correct place.

A generated proxy robot remains only as a fallback if the CAD mesh fails. When
the CAD mesh loads, the proxy body and proxy tablet/head panel are hidden. This
prevents the oversized red tablet panel from appearing behind the real robot.
The previous debug `AxesHelper` was removed from the production viewport.

## Interfaces

Inputs:

- Browser loads `/` from the Pluto web shell.
- Browser loads `/static/pluto_3d.js`.
- Browser loads local Three.js/STL assets from `/static`.
- Runtime polling reads `/api/status`.
- Sensor telemetry uses STM32 obstacle, IMU, and dance-envelope fields when
  available.

Outputs:

- 3D canvas in the Launch & Monitor Unit section.
- CAD robot mesh or fallback proxy robot.
- Front range cones, obstacle marker points, dance envelope, prediction line,
  heading, mode color, and sensor confidence status.

External dependencies:

- Browser with WebGL support.
- Local static Three.js files.
- Local robot STL mesh files.

## Configuration

Configuration values, defaults, limits, and files:

| Name | Default | Allowed Range | Reason |
| --- | --- | --- | --- |
| 3D module | `/static/pluto_3d.js` | fixed static route | Stable frontend entry point |
| Three.js module | `/static/three.module.min.js` | local file | Offline/Pi deployment |
| STL loader | `/static/STLLoader.js` | local file | CAD mesh loading |
| CAD meshes | `/static/robot_meshes/*.STL` | copied robot STL files | Use actual Pluto model |
| Camera flag | `--camera-disabled` optional | on/off | Let operator reserve camera for another process |

## Runtime Behavior

Normal behavior:

1. The home page mounts `#pluto3dCanvas`.
2. `pluto_3d.js` initializes the WebGL scene, floor, grid, lights, and sensor
   overlays.
3. CAD STL meshes load from local static files.
4. If CAD loading succeeds, the proxy body and proxy tablet/head are hidden.
5. If CAD loading fails, the proxy robot remains visible and the status text
   reports the fallback.
6. `/api/status` updates mode color, heading, obstacle cones, envelope, and
   sensor confidence.

Blocked behavior:

- The 3D view does not expose raw motor commands.
- The 3D view does not grant MANUAL, WELCOME, or DANCE authority.
- Camera disabling only affects camera acquisition; it does not affect safety
  gates or mode availability.

## How To Run

Run locally with the camera reserved for other software:

```bash
python3 -m pluto_runtime.web_shell --host 127.0.0.1 --port 8080 --camera-disabled --wave-pose-disabled
```

Open:

```text
http://127.0.0.1:8080/
```

Run smoke test:

```bash
python3 tools/web_shell_smoke.py
```

## How To Debug

Checklist:

1. Confirm `/static/pluto_3d.js` returns 200.
2. Confirm `/static/three.module.min.js` and `/static/STLLoader.js` return 200.
3. Confirm `/static/robot_meshes/base_link.STL` returns 200.
4. Confirm the visual status says `CAD robot mesh`.
5. If a large red panel appears, check that CAD load hides `head.visible`.
6. If arms are misplaced, inspect CAD part `origin` and `rpy` in
   `pluto_3d.js`.
7. If WebGL is blank, check browser console errors and local static asset paths.

Useful commands:

```bash
python3 tools/web_shell_smoke.py
curl http://127.0.0.1:8080/static/pluto_3d.js
curl http://127.0.0.1:8080/static/robot_meshes/base_link.STL
```

## Expected Evidence

Smoke test:

```text
WEB_SHELL_SMOKE PASS
```

Browser render:

```text
PLUTO Mission Control title visible
Launch & Monitor Unit visible
visualStatus includes CAD robot mesh
cameraStatus shows camera disabled by operator when --camera-disabled is used
WebGL canvas renders nonblank
No large red proxy tablet panel behind the CAD robot
No browser console errors
```

## Verification Tests

| Test ID | Method | Expected Result | Last Result |
| --- | --- | --- | --- |
| VER-WEB-011 | Open launch monitor page with local static assets | 3D robot visualization and launch gate render | local browser pass |
| WEB-026-SMOKE | Run `tools/web_shell_smoke.py` | Static JS, Three.js, STL assets, and `/face` routes pass | 2026-06-09 pass |
| WEB-026-CAD | Inspect browser visual status | Status includes `CAD robot mesh` | 2026-06-09 pass |
| WEB-026-CLEAN | Inspect 3D viewport | Debug axes and red proxy tablet panel are absent | 2026-06-09 pass |

## Failure Modes

| Failure | Likely Cause | Diagnostic | Recovery |
| --- | --- | --- | --- |
| Blank 3D canvas | WebGL unsupported or module load error | Browser console logs | Use supported browser, check static paths |
| Proxy robot appears | STL asset missing or loader failed | Visual status says proxy/fallback | Restore `robot_meshes` files |
| Arms appear detached | CAD origin or `rpy` transform mismatch | Inspect part transforms | Correct `cadParts` origin/rotation |
| Large red panel behind robot | Proxy tablet/head still visible after CAD load | Check `head.visible` on CAD success | Hide proxy head when CAD is loaded |
| Camera device unavailable | Camera is intentionally disabled or busy | `/api/camera/status` | Run with or without `--camera-disabled` based on operator need |

## Safety Notes

The 3D launch monitor is observational. It never bypasses emergency stop,
mode-manager rules, STM32 safety, or missing-hardware gates. Visual confidence
does not imply permission to move.

## Open Questions

- Should the final Pi deployment use kiosk fullscreen mode for the operator
  console?
- Should the CAD model include a final Samsung tablet mesh once the physical
  head mount dimensions are fixed?

## Change History

| Date | Change | Reason |
| --- | --- | --- |
| 2026-06-09 | Removed debug axes and hid proxy tablet/head after CAD load | User saw a large red object in the 3D viewport |
| 2026-06-09 | Added CAD part `rpy` transform handling | Place arms and wheels correctly |
| 2026-06-08 | Added local Three.js CAD digital twin | Make operator console feel like a real launch monitor |
