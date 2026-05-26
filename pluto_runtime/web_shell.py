#!/usr/bin/env python3
"""
Phase 4 PLUTO operator website shell.

This is intentionally not the final app. It provides the first safe operator
console surface: project identity, state/status display, hardware status,
events, blocked state requests, and emergency stop wiring.
"""

from __future__ import annotations

import argparse
import glob
import json
import platform
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterable
from urllib.parse import urlparse

from .camera import CameraService, status_to_dict


PROJECT_NAME = "PLUTO"
STM32_ID = "ID:STM32_MOTOR"
UNO_ID = "ID:UNO_LCD"
VALID_STATES = ("BOOTSTRAP", "IDLE", "MANUAL", "WELCOME", "DANCE", "ERROR", "GAME_LATER")
MOTION_STATES = {"MANUAL", "WELCOME", "DANCE"}


@dataclass
class HardwareDevice:
    name: str
    required: bool
    connected: bool = False
    port: str | None = None
    status: str = "unknown"
    detail: str = "not checked"
    latency_ms: float | None = None
    last_seen: float | None = None


@dataclass
class Event:
    timestamp: float
    level: str
    message: str


@dataclass
class PlutoStatus:
    project: str = PROJECT_NAME
    current_state: str = "BOOTSTRAP"
    current_substate: str = "WEB_SHELL"
    fault_reason: str | None = None
    git_commit: str = "unknown"
    started_at: float = field(default_factory=time.time)
    hardware: dict[str, HardwareDevice] = field(default_factory=dict)
    allowed_next_states: list[dict[str, Any]] = field(default_factory=list)
    bootstrap_report: dict[str, Any] = field(default_factory=dict)
    camera: dict[str, Any] = field(default_factory=dict)
    events: list[Event] = field(default_factory=list)


class PlutoWebContext:
    def __init__(
        self,
        serial_baud: int = 115200,
        camera_device: str | None = None,
        camera_resolution: tuple[int, int] = (320, 320),
        camera_fps: int = 30,
        camera_stream_fps: int = 8,
        camera_frame_skip: int = 1,
        camera_detection_hold: float = 2.0,
        camera_confidence: float = 0.30,
        yolo_model: str | None = None,
    ) -> None:
        self.serial_baud = serial_baud
        self.lock = threading.RLock()
        self.events: deque[Event] = deque(maxlen=80)
        self.started_at = time.time()
        self.current_state = "BOOTSTRAP"
        self.current_substate = "WEB_SHELL"
        self.fault_reason: str | None = None
        self.git_commit = read_git_commit()
        self.hardware = {
            "stm32": HardwareDevice("STM32 motor safety controller", True),
            "uno": HardwareDevice("Uno LCD face controller", False),
            "camera": HardwareDevice("Camera", False, status="starting", detail="Phase 4"),
            "speaker": HardwareDevice("Speaker", False, status="not_implemented", detail="Future audio phase"),
            "microphone": HardwareDevice("Microphone", False, status="not_implemented", detail="Future speech phase"),
        }
        self.log("info", "PLUTO web shell starting")
        self.camera_service = CameraService(
            device=camera_device,
            resolution=camera_resolution,
            framerate=camera_fps,
            stream_fps=camera_stream_fps,
            frame_skip=camera_frame_skip,
            detection_hold_s=camera_detection_hold,
            confidence_threshold=camera_confidence,
            model_path=yolo_model,
        )
        if self.camera_service.start():
            self.log("pass", "Camera service started")
        else:
            self.log("warn", f"Camera unavailable: {self.camera_service.get_status().error}")
        self.refresh_hardware()

    def log(self, level: str, message: str) -> None:
        with self.lock:
            self.events.appendleft(Event(time.time(), level, message))

    def refresh_hardware(self) -> None:
        ports = candidate_ports()
        self.log("info", f"Scanning serial ports: {', '.join(ports) if ports else 'none'}")

        stm32 = probe_stm32(ports, self.serial_baud)
        uno = probe_uno(ports, self.serial_baud, skip_port=stm32.port if stm32.connected else None)

        with self.lock:
            self.hardware["stm32"] = stm32
            self.hardware["uno"] = uno
            camera_status = self.camera_service.get_status()
            self.hardware["camera"] = HardwareDevice(
                "Camera",
                False,
                connected=camera_status.available,
                port=str(camera_status.device) if camera_status.device is not None else None,
                status="connected" if camera_status.available else "unavailable",
                detail=camera_status.error or f"{camera_status.backend} {camera_status.resolution}",
                last_seen=time.time() if camera_status.available else None,
            )
            self.bootstrap_report = {
                "phase": "Phase 4 camera feed and human detection",
                "serial_ports": ports,
                "required_hardware": {"stm32": asdict(stm32)},
                "optional_hardware": {
                    "uno": asdict(uno),
                    "camera": status_to_dict(camera_status),
                },
                "notes": [
                    "Website shell does not enable motion states.",
                    "Emergency stop sends CMD:STOP when STM32 is available.",
                    "Camera feed uses threaded capture, frame skipping, MJPG, low resolution, and warmup suppression.",
                ],
            }
            if stm32.connected:
                self.current_state = "IDLE"
                self.fault_reason = None
                self.log("pass", f"STM32 detected on {stm32.port}")
            else:
                self.current_state = "ERROR"
                self.fault_reason = "STM32 motor safety controller missing"
                self.log("error", self.fault_reason)

    def emergency_stop(self) -> dict[str, Any]:
        started = time.monotonic()
        stm32 = self.hardware["stm32"]
        stop = send_stm32_stop(stm32.port, self.serial_baud) if stm32.port else {"ok": False, "detail": "STM32 port unknown"}
        elapsed_ms = (time.monotonic() - started) * 1000.0

        with self.lock:
            self.current_state = "ERROR"
            self.fault_reason = "Emergency stop requested from website"
            self.log("stop", f"Emergency stop requested, serial result: {stop['detail']}")

        return {
            "ok": bool(stop["ok"]),
            "elapsed_ms": elapsed_ms,
            "serial": stop,
            "state": "ERROR",
        }

    def request_state(self, requested_state: str) -> dict[str, Any]:
        requested_state = requested_state.strip().upper()
        if requested_state not in VALID_STATES:
            self.log("warn", f"Rejected unknown state request: {requested_state}")
            return {"accepted": False, "reason": "unknown state"}

        reason = "Phase 5 mode manager is not implemented yet"
        if requested_state in MOTION_STATES and not self.hardware["stm32"].connected:
            reason = "STM32 unavailable; motion states are blocked"
        elif requested_state in MOTION_STATES:
            reason = f"{requested_state} is blocked until its own phase is validated"
        elif requested_state == "GAME_LATER":
            reason = "GAME_LATER is documented but not implemented in v1"

        self.log("info", f"State request {requested_state} blocked: {reason}")
        return {"accepted": False, "requested_state": requested_state, "reason": reason}

    def shutdown(self, confirm: str | None) -> dict[str, Any]:
        if confirm != "PLUTO SHUTDOWN":
            self.log("warn", "Shutdown rejected because confirmation text was missing")
            return {"accepted": False, "reason": "confirmation required"}

        stop = self.emergency_stop()
        self.log("warn", "Shutdown command acknowledged as dry-run in Phase 3")
        return {
            "accepted": False,
            "reason": "Real shutdown is disabled in Phase 3 shell",
            "stop": stop,
        }

    def snapshot(self) -> PlutoStatus:
        with self.lock:
            hardware = {key: value for key, value in self.hardware.items()}
            events = list(self.events)
            status = PlutoStatus(
                current_state=self.current_state,
                current_substate=self.current_substate,
                fault_reason=self.fault_reason,
                git_commit=self.git_commit,
                started_at=self.started_at,
                hardware=hardware,
                allowed_next_states=build_allowed_states(self.current_state, hardware["stm32"].connected),
                bootstrap_report=self.bootstrap_report,
                camera=status_to_dict(self.camera_service.get_status()),
                events=events,
            )
            return status


def read_git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=1,
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def candidate_ports() -> list[str]:
    ports: list[str] = []
    try:
        import serial.tools.list_ports  # type: ignore

        ports.extend(port.device for port in serial.tools.list_ports.comports())
    except Exception:
        pass

    system = platform.system().lower()
    if system == "linux":
        ports.extend(glob.glob("/dev/ttyACM*"))
        ports.extend(glob.glob("/dev/ttyUSB*"))
        ports.extend(glob.glob("/dev/serial/by-id/*"))
    elif system == "darwin":
        ports.extend(glob.glob("/dev/tty.usbmodem*"))
        ports.extend(glob.glob("/dev/tty.usbserial*"))
    elif system == "windows" and not ports:
        ports.extend(f"COM{i}" for i in range(1, 33))

    return unique(ports)


def serial_open(port: str, baud: int):
    import serial  # type: ignore

    return serial.Serial(port=port, baudrate=baud, timeout=0.02, write_timeout=0.1)


def serial_write(ser, command: str) -> None:
    ser.write((command.strip() + "\n").encode("ascii"))
    ser.flush()


def serial_read_line(ser) -> str | None:
    raw = ser.readline()
    if not raw:
        return None
    return raw.decode("utf-8", errors="replace").strip()


def probe_stm32(ports: list[str], baud: int) -> HardwareDevice:
    if not ports:
        return HardwareDevice("STM32 motor safety controller", True, status="missing", detail="no serial ports found")

    for port in ports:
        try:
            with serial_open(port, baud) as ser:
                time.sleep(0.15)
                started = time.monotonic()
                serial_write(ser, "CMD:PING")
                deadline = started + 0.25
                seen: list[str] = []
                while time.monotonic() < deadline:
                    line = serial_read_line(ser)
                    if not line:
                        continue
                    seen.append(line)
                    if line == "ACK:PING" or line == STM32_ID or line.startswith("TEL:") or line.startswith("OBS:"):
                        serial_write(ser, "CMD:STOP")
                        return HardwareDevice(
                            "STM32 motor safety controller",
                            True,
                            connected=True,
                            port=port,
                            status="connected",
                            detail=line,
                            latency_ms=(time.monotonic() - started) * 1000.0,
                            last_seen=time.time(),
                        )
        except Exception:
            continue

    return HardwareDevice("STM32 motor safety controller", True, status="missing", detail="STM32 identity not found")


def probe_uno(ports: list[str], baud: int, skip_port: str | None = None) -> HardwareDevice:
    for port in ports:
        if skip_port and port == skip_port:
            continue
        try:
            with serial_open(port, baud) as ser:
                time.sleep(1.2)
                serial_write(ser, "ID?")
                deadline = time.monotonic() + 0.8
                while time.monotonic() < deadline:
                    line = serial_read_line(ser)
                    if line == UNO_ID:
                        return HardwareDevice(
                            "Uno LCD face controller",
                            False,
                            connected=True,
                            port=port,
                            status="connected",
                            detail=line,
                            last_seen=time.time(),
                        )
        except Exception:
            continue

    return HardwareDevice("Uno LCD face controller", False, status="unavailable", detail="optional hardware not detected")


def send_stm32_stop(port: str | None, baud: int) -> dict[str, Any]:
    if not port:
        return {"ok": False, "detail": "STM32 port unknown"}

    try:
        with serial_open(port, baud) as ser:
            started = time.monotonic()
            serial_write(ser, "CMD:STOP")
            deadline = started + 0.15
            lines: list[str] = []
            while time.monotonic() < deadline:
                line = serial_read_line(ser)
                if not line:
                    continue
                lines.append(line)
                if line == "ACK:STOP":
                    return {
                        "ok": True,
                        "detail": "ACK:STOP",
                        "latency_ms": (time.monotonic() - started) * 1000.0,
                        "lines": lines,
                    }
            return {"ok": False, "detail": "STOP sent but ACK:STOP not received within 150 ms", "lines": lines}
    except Exception as exc:
        return {"ok": False, "detail": str(exc)}


def build_allowed_states(current_state: str, stm32_connected: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for state in VALID_STATES:
        allowed = False
        reason = "Mode manager begins in Phase 5"
        if state == current_state:
            reason = "current state"
        elif state in MOTION_STATES and not stm32_connected:
            reason = "blocked because STM32 is unavailable"
        elif state in MOTION_STATES:
            reason = f"blocked until {state} phase is validated"
        elif state == "GAME_LATER":
            reason = "documented for later, not v1"
        rows.append({"state": state, "allowed": allowed, "reason": reason})
    return rows


def encode_json(data: Any) -> bytes:
    def default(value: Any) -> Any:
        if hasattr(value, "__dataclass_fields__"):
            return asdict(value)
        return str(value)

    return json.dumps(data, default=default, indent=2).encode("utf-8")


def html_page() -> str:
    states = "".join(f'<button class="state" data-state="{state}">{state}</button>' for state in VALID_STATES)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PLUTO Operator Console</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f5f7f8;
      --panel: #ffffff;
      --ink: #172026;
      --muted: #66737c;
      --line: #d7dee3;
      --good: #1f7a4d;
      --warn: #9a6500;
      --bad: #b42318;
      --accent: #255c99;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font: 15px/1.45 system-ui, -apple-system, Segoe UI, sans-serif;
      color: var(--ink);
      background: var(--bg);
    }}
    header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 18px clamp(16px, 4vw, 40px);
      background: #111820;
      color: white;
      border-bottom: 4px solid var(--accent);
    }}
    h1, h2 {{ margin: 0; letter-spacing: 0; }}
    h1 {{ font-size: clamp(28px, 6vw, 54px); line-height: 1; }}
    h2 {{ font-size: 17px; }}
    main {{
      width: min(1180px, 100%);
      margin: 0 auto;
      padding: 20px clamp(14px, 3vw, 28px) 36px;
      display: grid;
      gap: 16px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(12, 1fr);
      gap: 16px;
    }}
    section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      min-width: 0;
    }}
    .span-4 {{ grid-column: span 4; }}
    .span-6 {{ grid-column: span 6; }}
    .span-8 {{ grid-column: span 8; }}
    .span-12 {{ grid-column: span 12; }}
    .metric {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      padding: 10px 0;
      border-bottom: 1px solid var(--line);
    }}
    .metric:last-child {{ border-bottom: 0; }}
    .label {{ color: var(--muted); }}
    .value {{ font-weight: 700; text-align: right; overflow-wrap: anywhere; }}
    .status-good {{ color: var(--good); }}
    .status-warn {{ color: var(--warn); }}
    .status-bad {{ color: var(--bad); }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 10px; }}
    button {{
      min-height: 42px;
      border: 1px solid var(--line);
      background: white;
      color: var(--ink);
      border-radius: 8px;
      padding: 10px 13px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
    }}
    button:hover {{ border-color: var(--accent); }}
    .danger {{ background: var(--bad); color: white; border-color: var(--bad); }}
    .primary {{ background: var(--accent); color: white; border-color: var(--accent); }}
    .state {{ min-width: 118px; }}
    .state[disabled] {{ opacity: 0.55; cursor: not-allowed; }}
    .events {{
      min-height: 180px;
      max-height: 320px;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfd;
    }}
    .event {{
      display: grid;
      grid-template-columns: 86px 70px 1fr;
      gap: 8px;
      padding: 8px 10px;
      border-bottom: 1px solid var(--line);
      font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
      font-size: 13px;
    }}
    .event:last-child {{ border-bottom: 0; }}
    .cameraBox {{
      position: relative;
      width: 100%;
      aspect-ratio: 4 / 3;
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      background: #101820;
      margin: 12px 0;
      display: grid;
      place-items: center;
    }}
    #cameraFeed {{
      width: 100%;
      height: 100%;
      object-fit: contain;
      display: none;
    }}
    #cameraUnavailable {{
      color: #d8e2ea;
      padding: 16px;
      text-align: center;
      font-weight: 700;
    }}
    pre {{
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      margin: 0;
      padding: 12px;
      background: #111820;
      color: #e8eef3;
      border-radius: 8px;
      max-height: 280px;
      overflow: auto;
    }}
    @media (max-width: 860px) {{
      header {{ align-items: flex-start; flex-direction: column; }}
      .span-4, .span-6, .span-8 {{ grid-column: span 12; }}
      .event {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>PLUTO</h1>
      <div>Operator Console</div>
    </div>
    <button class="danger" id="estop">Emergency Stop</button>
  </header>
  <main>
    <div class="grid">
      <section class="span-4">
        <h2>State</h2>
        <div class="metric"><span class="label">Current</span><span class="value" id="state">...</span></div>
        <div class="metric"><span class="label">Substate</span><span class="value" id="substate">...</span></div>
        <div class="metric"><span class="label">Fault</span><span class="value" id="fault">none</span></div>
        <div class="metric"><span class="label">Commit</span><span class="value" id="commit">...</span></div>
      </section>
      <section class="span-8">
        <h2>Allowed Next States</h2>
        <div class="actions" id="states">{states}</div>
        <div id="stateReasons" style="margin-top: 12px;"></div>
      </section>
      <section class="span-6">
        <h2>Hardware</h2>
        <div id="hardware"></div>
        <div class="actions" style="margin-top: 14px;">
          <button class="primary" id="refresh">Refresh Hardware</button>
        </div>
      </section>
      <section class="span-6">
        <h2>Camera</h2>
        <div class="cameraBox">
          <img id="cameraFeed" alt="PLUTO camera feed">
          <div id="cameraUnavailable">Camera feed unavailable</div>
        </div>
        <div class="metric"><span class="label">Status</span><span class="value" id="cameraStatus">...</span></div>
        <div class="metric"><span class="label">Humans</span><span class="value" id="humanCount">0</span></div>
        <div class="metric"><span class="label">FPS</span><span class="value" id="cameraFps">0</span></div>
        <div class="metric"><span class="label">Inference</span><span class="value" id="cameraInference">0 ms</span></div>
      </section>
      <section class="span-12">
        <h2>Events</h2>
        <div class="events" id="events"></div>
      </section>
      <section class="span-12">
        <h2>Bootstrap Report</h2>
        <pre id="report">{{}}</pre>
      </section>
    </div>
  </main>
  <script>
    async function api(path, options) {{
      const res = await fetch(path, options);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || res.statusText);
      return data;
    }}
    function clsFor(status) {{
      if (status === 'connected') return 'status-good';
      if (status === 'missing' || status === 'error') return 'status-bad';
      return 'status-warn';
    }}
    function render(data) {{
      document.getElementById('state').textContent = data.current_state;
      document.getElementById('substate').textContent = data.current_substate || 'none';
      document.getElementById('fault').textContent = data.fault_reason || 'none';
      document.getElementById('commit').textContent = data.git_commit || 'unknown';
      const hardware = document.getElementById('hardware');
      hardware.innerHTML = Object.entries(data.hardware).map(([key, item]) => `
        <div class="metric">
          <span class="label">${{item.name}}</span>
          <span class="value ${{clsFor(item.status)}}">${{item.status}}${{item.port ? ' - ' + item.port : ''}}</span>
        </div>
      `).join('');
      const allowed = Object.fromEntries(data.allowed_next_states.map(item => [item.state, item]));
      document.querySelectorAll('.state').forEach(btn => {{
        const item = allowed[btn.dataset.state];
        btn.disabled = !item || !item.allowed;
        btn.title = item ? item.reason : 'unavailable';
      }});
      document.getElementById('stateReasons').innerHTML = data.allowed_next_states.map(item => `
        <div class="metric">
          <span class="label">${{item.state}}</span>
          <span class="value ${{item.allowed ? 'status-good' : 'status-warn'}}">${{item.reason}}</span>
        </div>
      `).join('');
      document.getElementById('events').innerHTML = data.events.map(item => {{
        const t = new Date(item.timestamp * 1000).toLocaleTimeString();
        return `<div class="event"><span>${{t}}</span><span>${{item.level}}</span><span>${{item.message}}</span></div>`;
      }}).join('');
      document.getElementById('report').textContent = JSON.stringify(data.bootstrap_report, null, 2);
      const camera = data.camera || {{}};
      const feed = document.getElementById('cameraFeed');
      const unavailable = document.getElementById('cameraUnavailable');
      if (camera.available && camera.running) {{
        if (!feed.src.includes('/camera.mjpg')) feed.src = '/camera.mjpg';
        feed.style.display = 'block';
        unavailable.style.display = 'none';
      }} else {{
        feed.removeAttribute('src');
        feed.style.display = 'none';
        unavailable.style.display = 'grid';
        unavailable.textContent = camera.error || 'Camera feed unavailable';
      }}
      document.getElementById('cameraStatus').textContent = camera.running ? `${{camera.backend}} ${{camera.resolution}}` : (camera.error || 'unavailable');
      document.getElementById('humanCount').textContent = camera.human_count || 0;
      document.getElementById('cameraFps').textContent = `${{(camera.stream_fps || 0).toFixed(1)}} stream / ${{(camera.capture_fps || 0).toFixed(1)}} capture`;
      document.getElementById('cameraInference').textContent = `${{(camera.inference_ms || 0).toFixed(1)}} ms`;
    }}
    async function refresh() {{
      try {{ render(await api('/api/status')); }}
      catch (err) {{ console.error(err); }}
    }}
    document.getElementById('refresh').addEventListener('click', async () => {{
      await api('/api/refresh-hardware', {{method: 'POST'}});
      await refresh();
    }});
    document.getElementById('estop').addEventListener('click', async () => {{
      await api('/api/emergency-stop', {{method: 'POST'}});
      await refresh();
    }});
    document.querySelectorAll('.state').forEach(btn => btn.addEventListener('click', async () => {{
      await api('/api/request-state', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{state: btn.dataset.state}})
      }});
      await refresh();
    }}));
    refresh();
    setInterval(refresh, 1000);
  </script>
</body>
</html>"""


class PlutoRequestHandler(BaseHTTPRequestHandler):
    server_version = "PlutoWebShell/0.1"

    @property
    def context(self) -> PlutoWebContext:
        return self.server.context  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        if self.path not in {"/api/status", "/healthz"}:
            self.context.log("http", fmt % args)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def send_bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status: int, payload: Any) -> None:
        self.send_bytes(status, encode_json(payload), "application/json; charset=utf-8")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self.send_bytes(HTTPStatus.OK, html_page().encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/api/status":
            self.send_json(HTTPStatus.OK, self.context.snapshot())
            return
        if path == "/api/camera/status":
            self.send_json(HTTPStatus.OK, self.context.snapshot().camera)
            return
        if path == "/camera.jpg":
            frame = self.context.camera_service.get_jpeg()
            if frame is None:
                self.send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "camera frame unavailable"})
                return
            self.send_bytes(HTTPStatus.OK, frame, "image/jpeg")
            return
        if path == "/camera.mjpg":
            self.send_response(HTTPStatus.OK)
            self.send_header("Age", "0")
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            for frame in self.context.camera_service.stream_frames():
                try:
                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii"))
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
                except (BrokenPipeError, ConnectionResetError):
                    break
            return
        if path == "/healthz":
            self.send_json(HTTPStatus.OK, {"ok": True, "project": PROJECT_NAME})
            return
        self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/refresh-hardware":
                self.context.refresh_hardware()
                self.send_json(HTTPStatus.OK, self.context.snapshot())
                return
            if path == "/api/emergency-stop":
                self.send_json(HTTPStatus.OK, self.context.emergency_stop())
                return
            if path == "/api/request-state":
                body = self.read_json()
                self.send_json(HTTPStatus.OK, self.context.request_state(str(body.get("state", ""))))
                return
            if path == "/api/shutdown":
                body = self.read_json()
                self.send_json(HTTPStatus.OK, self.context.shutdown(body.get("confirm")))
                return
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except Exception as exc:
            self.context.log("error", f"API failure on {path}: {exc}")
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})


class PlutoWebServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], handler, context: PlutoWebContext) -> None:
        super().__init__(address, handler)
        self.context = context


def local_addresses(port: int) -> list[str]:
    addresses = [f"http://127.0.0.1:{port}"]
    try:
        hostname = socket.gethostname()
        for item in socket.getaddrinfo(hostname, None, family=socket.AF_INET):
            ip = item[4][0]
            if ip != "127.0.0.1":
                addresses.append(f"http://{ip}:{port}")
    except Exception:
        pass
    return unique(addresses)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Phase 4 PLUTO operator website shell.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host. Use 0.0.0.0 on Raspberry Pi.")
    parser.add_argument("--port", type=int, default=8080, help="Bind port. Default: 8080.")
    parser.add_argument("--baud", type=int, default=115200, help="Serial baud for hardware probes.")
    parser.add_argument("--camera-device", help="Camera device, for example /dev/video0.")
    parser.add_argument("--camera-resolution", default="320x320", help="Capture resolution WIDTHxHEIGHT. Default: 320x320.")
    parser.add_argument("--camera-fps", type=int, default=30, help="Requested camera FPS. Default: 30.")
    parser.add_argument("--camera-stream-fps", type=int, default=8, help="MJPEG stream FPS. Default: 8.")
    parser.add_argument("--camera-frame-skip", type=int, default=1, help="Run human detection every Nth frame. Default: 1.")
    parser.add_argument("--camera-detection-hold", type=float, default=2.0, help="Seconds to keep last human detection visible after missed frames.")
    parser.add_argument("--camera-confidence", type=float, default=0.30, help="Human detection confidence threshold. Default: 0.30.")
    parser.add_argument("--yolo-model", help="TFLite YOLO model path. Defaults to PLUTO_YOLO_MODEL or /home/pi/yolo/model/yolov8n-fp16.tflite.")
    return parser.parse_args(argv)


def parse_resolution(value: str) -> tuple[int, int]:
    try:
        left, right = value.lower().split("x", 1)
        width = int(left)
        height = int(right)
    except Exception as exc:
        raise argparse.ArgumentTypeError("resolution must look like WIDTHxHEIGHT, for example 320x320") from exc
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("resolution dimensions must be positive")
    return width, height


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    context = PlutoWebContext(
        serial_baud=args.baud,
        camera_device=args.camera_device,
        camera_resolution=parse_resolution(args.camera_resolution),
        camera_fps=args.camera_fps,
        camera_stream_fps=args.camera_stream_fps,
        camera_frame_skip=args.camera_frame_skip,
        camera_detection_hold=args.camera_detection_hold,
        camera_confidence=args.camera_confidence,
        yolo_model=args.yolo_model,
    )
    server = PlutoWebServer((args.host, args.port), PlutoRequestHandler, context)
    print(f"PLUTO web shell running on {args.host}:{args.port}")
    for address in local_addresses(args.port):
        print(f"Open {address}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping PLUTO web shell")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
