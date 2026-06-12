# PLUTO sensor dashboard design research

Last updated: 2026-06-08

This branch keeps the production console redesign traceable to outside HMI,
telemetry, and robot-interface references. The goal is an operator dashboard
that answers useful questions quickly:

- Is PLUTO alive?
- Can PLUTO move safely?
- What do the sensors actually say?
- What should the operator do next?
- Does the current mode change how the same data should be interpreted?

## Sources consulted

- Grafana dashboard best practices:
  https://grafana.com/docs/grafana/latest/visualizations/dashboards/build-dashboards/best-practices/
- Grafana thresholds:
  https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/configure-thresholds/
- ISA-101 HMI standards overview:
  https://www.isa.org/standards-and-publications/isa-standards/isa-101-standards
- EEMUA 191 alarm-system contents, 2024 edition:
  https://www.eemua.org/getattachment/9d3f8071-55c3-49bf-a74a-3bf6ad4a2e0f/Contents-EEMUA-Publication-191-Edition4-November-2024.pdf
- NASA JSC Human Engineering Displays and Controls:
  https://www.nasa.gov/wp-content/uploads/2023/07/jsc-hhp-humansystemsintegrationdisplaydevelopment-2023-1.pdf
- Human-robot trust and physical-zone visualization:
  https://arxiv.org/abs/2112.00779

## Design translation for PLUTO

Grafana guidance says dashboards should answer a clear question and reduce
cognitive load. For PLUTO, the top of the console now asks and answers four
operator questions: telemetry truth, robot decision, mode personality, and
next operator action.

Grafana threshold guidance maps naturally to the range sensors: ultrasonic
data is not shown only as numbers. It is converted into STOP, SLOW, CLEAR,
with the actual centimeters still visible for verification.

ISA-101 and alarm-management references support a restrained HMI: neutral
surfaces for normal operation, and red/amber/green used only for safety and
attention. PLUTO keeps color attached to meaning instead of decoration.

NASA human-factors material emphasizes iterative, user-centered operational
displays. The console therefore shows the same data in layers: mission strip,
operator summary, interpreted sensor pipeline, then raw details.

The robot trust paper supports clear visualization of physical zones. PLUTO's
old flat map became a range radar and occupancy corridor: green for known
clear space, amber for caution, red for obstacle returns, and gray for
unknown or untrusted areas.

## Current branch implementation

- `Launch & Monitor Unit`: full console band with a local Three.js digital
  twin, launch gate, and go/no-go checklist. The 3D scene now loads the
  Simulink/ROS CAD STL meshes from `my_robot` for the robot base, wheels, and
  arms, with the generated proxy robot kept as fallback.
- `Operations Readiness`: top-level decision cards.
- `Sensor Intelligence`: raw range, filtered IMU, odometry, and final guard
  decision as a pipeline.
- `Sensor Confidence`: a simple weighted score from STM32 link, ultrasonic
  live count, MPU parse, filtered IMU, and hall odometry.
- `Mode-Adaptive Guard`: IDLE, WELCOME, MANUAL, DANCE, ERROR, and BOOTSTRAP
  each get different operator guidance from the same sensor data.
- `Range Radar & Occupancy Corridor`: advanced canvas map that shows clear,
  caution, stop, and unknown zones.

Three.js is pinned locally at `0.184.0` and served from the Python web shell
with the STL loader and CAD meshes, so the robot dashboard does not depend on
an external CDN at runtime.

The backend telemetry contract was intentionally left unchanged in this pass.
