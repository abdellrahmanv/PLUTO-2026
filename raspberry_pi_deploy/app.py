#!/usr/bin/env python3
import glob
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field

import serial
from flask import Flask, jsonify, request


APP_HOST = os.getenv("PLUTO_WEB_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("PLUTO_WEB_PORT", "8080"))
SERIAL_BAUD = int(os.getenv("PLUTO_STM32_BAUD", "115200"))
SERIAL_PORT = os.getenv("PLUTO_STM32_PORT", "")

MAX_SPEED = int(os.getenv("PLUTO_MAX_SPEED", "250"))
MAX_STEER = int(os.getenv("PLUTO_MAX_STEER", "250"))
PING_INTERVAL_S = 0.4
RECONNECT_INTERVAL_S = 1.0


@dataclass
class MotorState:
    connected: bool = False
    port: str = ""
    last_line: str = ""
    last_error: str = ""
    last_seen_s: float = 0.0
    telemetry: dict = field(default_factory=dict)
    obstacles: dict = field(default_factory=dict)
    alerts: deque = field(default_factory=lambda: deque(maxlen=20))
    log: deque = field(default_factory=lambda: deque(maxlen=80))


class STM32Bridge:
    def __init__(self):
        self.state = MotorState()
        self.lock = threading.Lock()
        self.ser = None
        self.stop_event = threading.Event()
        self.last_ping = 0.0

    def start(self):
        threading.Thread(target=self._worker, daemon=True).start()

    def stop(self):
        self.stop_event.set()
        self.send("CMD:STOP")
        self._close()

    def send(self, command: str):
        line = command.strip() + "\n"
        with self.lock:
            ser = self.ser
        if not ser or not ser.is_open:
            self._log(f"DROP:{command}")
            return False
        try:
            ser.write(line.encode("ascii"))
            ser.flush()
            self._log(f"TX:{command}")
            return True
        except serial.SerialException as exc:
            self._set_error(str(exc))
            self._close()
            return False

    def status(self):
        with self.lock:
            return {
                "connected": self.state.connected,
                "port": self.state.port,
                "last_line": self.state.last_line,
                "last_error": self.state.last_error,
                "last_seen_s": self.state.last_seen_s,
                "telemetry": dict(self.state.telemetry),
                "obstacles": dict(self.state.obstacles),
                "alerts": list(self.state.alerts),
                "log": list(self.state.log),
                "max_speed": MAX_SPEED,
                "max_steer": MAX_STEER,
            }

    def _worker(self):
        while not self.stop_event.is_set():
            if not self.ser or not self.ser.is_open:
                self._connect()
                time.sleep(RECONNECT_INTERVAL_S)
                continue

            now = time.time()
            if now - self.last_ping >= PING_INTERVAL_S:
                self.send("CMD:PING")
                self.last_ping = now

            try:
                raw = self.ser.readline()
                if raw:
                    line = raw.decode("utf-8", errors="replace").strip()
                    self._handle_line(line)
            except serial.SerialException as exc:
                self._set_error(str(exc))
                self._close()

            time.sleep(0.01)

    def _connect(self):
        ports = [SERIAL_PORT] if SERIAL_PORT else self._candidate_ports()
        for port in ports:
            if not port:
                continue
            try:
                ser = serial.Serial(port, SERIAL_BAUD, timeout=0.05, write_timeout=0.2)
                with self.lock:
                    self.ser = ser
                    self.state.connected = True
                    self.state.port = port
                    self.state.last_error = ""
                self._log(f"CONNECTED:{port}")
                self.send("CMD:PING")
                return
            except serial.SerialException as exc:
                self._set_error(f"{port}: {exc}")

        with self.lock:
            self.state.connected = False
            self.state.port = ""

    def _candidate_ports(self):
        ports = []
        for pattern in ("/dev/ttyACM*", "/dev/ttyUSB*"):
            ports.extend(sorted(glob.glob(pattern)))
        return ports

    def _close(self):
        with self.lock:
            ser = self.ser
            self.ser = None
            self.state.connected = False
        if ser:
            try:
                ser.close()
            except serial.SerialException:
                pass

    def _handle_line(self, line: str):
        if not line:
            return
        with self.lock:
            self.state.last_line = line
            self.state.last_seen_s = time.time()
            self.state.log.appendleft(f"RX:{line}")

            if line.startswith("TEL:"):
                self.state.telemetry = self._parse_key_values(line[4:])
            elif line.startswith("OBS:"):
                self.state.obstacles = self._parse_key_values(line[4:])
            elif line.startswith("ALERT:"):
                self.state.alerts.appendleft(line)

    def _parse_key_values(self, text: str):
        result = {}
        for part in text.split(","):
            if ":" not in part:
                continue
            key, value = part.split(":", 1)
            try:
                result[key] = float(value)
            except ValueError:
                result[key] = value
        return result

    def _set_error(self, message: str):
        with self.lock:
            self.state.last_error = message
            self.state.log.appendleft(f"ERR:{message}")

    def _log(self, message: str):
        with self.lock:
            self.state.log.appendleft(message)


app = Flask(__name__)
bridge = STM32Bridge()


def clamp(value, low, high):
    return max(low, min(high, int(value)))


@app.get("/")
def index():
    return HTML_PAGE


@app.get("/health")
def health():
    return "PLUTO_OK\n", 200, {"Content-Type": "text/plain"}


@app.get("/api/status")
def api_status():
    return jsonify(bridge.status())


@app.post("/api/drive")
def api_drive():
    data = request.get_json(force=True, silent=True) or {}
    speed = clamp(data.get("speed", 0), -MAX_SPEED, MAX_SPEED)
    steer = clamp(data.get("steer", 0), -MAX_STEER, MAX_STEER)
    ok = bridge.send(f"CMD:DRIVE:{speed},{steer}")
    return jsonify({"ok": ok, "speed": speed, "steer": steer})


@app.post("/api/stop")
def api_stop():
    ok = bridge.send("CMD:STOP")
    return jsonify({"ok": ok})


@app.post("/api/return")
def api_return():
    ok = bridge.send("CMD:RETURN")
    return jsonify({"ok": ok})


@app.post("/api/reset_odom")
def api_reset_odom():
    ok = bridge.send("CMD:RESET_ODOM")
    return jsonify({"ok": ok})


@app.post("/api/arm")
def api_arm():
    data = request.get_json(force=True, silent=True) or {}
    steps = clamp(data.get("steps", 0), -20000, 20000)
    speed = clamp(data.get("speed", 200), 1, 2000)
    ok = bridge.send(f"CMD:ARM:{steps},{speed}")
    return jsonify({"ok": ok, "steps": steps, "speed": speed})


HTML_PAGE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
  <title>Pluto Motors Test</title>
  <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🤖</text></svg>">
  <style>
    :root {
      color-scheme: dark;
      --bg: #111412;
      --panel: #1b211d;
      --panel-2: #222a24;
      --text: #f3f7f0;
      --muted: #a9b3aa;
      --accent: #46d37d;
      --danger: #ff5c5c;
      --warn: #f7c948;
      --line: #39433b;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: system-ui, -apple-system, Segoe UI, sans-serif;
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
      background: #0d100e;
      position: sticky;
      top: 0;
      z-index: 2;
    }
    h1 { font-size: 18px; margin: 0; letter-spacing: 0; }
    .status {
      display: flex;
      gap: 8px;
      align-items: center;
      font-size: 13px;
      color: var(--muted);
    }
    .dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: var(--danger);
    }
    .dot.on { background: var(--accent); }
    main {
      display: grid;
      grid-template-columns: minmax(280px, 420px) 1fr;
      gap: 16px;
      padding: 16px;
      max-width: 1100px;
      margin: 0 auto;
    }
    section {
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
      padding: 14px;
    }
    h2 { font-size: 15px; margin: 0 0 12px; color: var(--muted); }
    .pad {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 10px;
      max-width: 330px;
      margin: 0 auto;
      touch-action: none;
      user-select: none;
      -webkit-user-select: none;
    }
    button {
      appearance: none;
      border: 1px solid var(--line);
      background: var(--panel-2);
      color: var(--text);
      min-height: 62px;
      border-radius: 8px;
      font-size: 18px;
      font-weight: 700;
      cursor: pointer;
      touch-action: manipulation;
      transition: background-color 0.1s, transform 0.1s;
    }
    button:active { transform: scale(0.98); }
    button.active-drive {
      background: var(--accent) !important;
      color: #0d100e !important;
      border-color: var(--accent) !important;
      transform: scale(0.95);
      box-shadow: 0 0 12px rgba(70, 211, 125, 0.4);
    }
    .stop {
      background: var(--danger);
      border-color: var(--danger);
      color: #fff;
    }
    .stop.active-drive {
      background: #ff3333 !important;
      color: #fff !important;
      border-color: #ff3333 !important;
    }
    .secondary { font-size: 14px; min-height: 46px; }
    .wide { grid-column: 1 / span 3; }
    label {
      display: grid;
      gap: 8px;
      font-size: 13px;
      color: var(--muted);
      margin: 12px 0;
    }
    input[type="range"], input[type="number"] { width: 100%; }
    input[type="number"] {
      background: #101411;
      border: 1px solid var(--line);
      border-radius: 6px;
      color: var(--text);
      padding: 10px;
      font-size: 16px;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 10px;
    }
    .metric {
      background: #101411;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      min-height: 64px;
    }
    .metric b { display: block; font-size: 13px; color: var(--muted); }
    .metric span { font-size: 21px; font-weight: 800; }
    pre {
      margin: 0;
      max-height: 310px;
      overflow: auto;
      white-space: pre-wrap;
      font-size: 12px;
      color: #dce7dd;
    }
    @media (max-width: 820px) {
      main { grid-template-columns: 1fr; padding: 10px; }
      header { align-items: flex-start; gap: 8px; flex-direction: column; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Pluto Motors Test</h1>
    <div class="status"><span id="dot" class="dot"></span><span id="conn">Disconnected</span></div>
  </header>
  <main>
    <section>
      <h2>Manual Drive</h2>
      <div class="pad">
        <div></div>
        <button data-drive="fwd">FWD</button>
        <div></div>
        <button data-drive="left">LEFT</button>
        <button class="stop" id="stop">STOP</button>
        <button data-drive="right">RIGHT</button>
        <div></div>
        <button data-drive="back">BACK</button>
        <div></div>
      </div>
      <label>Speed <span id="speedValue">120</span>
        <input id="speed" type="range" min="30" max="250" value="120">
      </label>
      <label>Steer <span id="steerValue">120</span>
        <input id="steer" type="range" min="30" max="250" value="120">
      </label>
      <div class="grid">
        <button class="secondary" id="return">Return</button>
        <button class="secondary" id="reset">Reset Odom</button>
        <button class="secondary" id="arm">Arm Test</button>
      </div>
      <label>Arm steps
        <input id="armSteps" type="number" value="800">
      </label>
      <label>Arm speed
        <input id="armSpeed" type="number" value="300">
      </label>
    </section>
    <section>
      <h2>Telemetry</h2>
      <div class="grid">
        <div class="metric"><b>Battery</b><span id="bat">--</span></div>
        <div class="metric"><b>Speed</b><span id="spd">--</span></div>
        <div class="metric"><b>Distance</b><span id="dist">--</span></div>
        <div class="metric"><b>Front Left</b><span id="fl">--</span></div>
        <div class="metric"><b>Front</b><span id="front">--</span></div>
        <div class="metric"><b>Front Right</b><span id="fr">--</span></div>
      </div>
      <h2 style="margin-top:16px">Log</h2>
      <pre id="log"></pre>
    </section>
  </main>
  <script>
    const speed = document.querySelector("#speed");
    const steer = document.querySelector("#steer");
    const speedValue = document.querySelector("#speedValue");
    const steerValue = document.querySelector("#steerValue");

    const driveButtons = {};
    document.querySelectorAll("[data-drive]").forEach(btn => {
      driveButtons[btn.dataset.drive] = btn;
    });

    function setButtonActive(kind, active) {
      const btn = driveButtons[kind];
      if (btn) btn.classList.toggle("active-drive", active);
    }

    function post(path, body = {}) {
      return fetch(path, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body)
      }).catch(() => {});
    }

    function drive(kind) {
      const s = Number(speed.value);
      const t = Number(steer.value);
      let payload = {speed: 0, steer: 0};
      if (kind === "fwd") payload = {speed: -s, steer: 0};
      if (kind === "back") payload = {speed: s, steer: 0};
      if (kind === "left") payload = {speed: 0, steer: -t};
      if (kind === "right") payload = {speed: 0, steer: t};
      post("/api/drive", payload);
    }

    let activeDriveType = null;

    function handleStart(kind, e) {
      if (e) e.preventDefault();
      if (activeDriveType === kind) return;
      if (activeDriveType) handleRelease();
      activeDriveType = kind;
      setButtonActive(kind, true);
      drive(kind);
    }

    function handleRelease(e) {
      if (e) e.preventDefault();
      if (!activeDriveType) return;
      setButtonActive(activeDriveType, false);
      activeDriveType = null;
      post("/api/stop");
    }

    /* --- touch / pointer controls --- */
    document.querySelectorAll("[data-drive]").forEach(btn => {
      const kind = btn.dataset.drive;
      
      // Support both pointer and touch events
      btn.addEventListener("pointerdown", (e) => handleStart(kind, e));
      btn.addEventListener("touchstart", (e) => handleStart(kind, e), { passive: false });
      
      btn.addEventListener("pointerup", (e) => handleRelease(e));
      btn.addEventListener("touchend", (e) => handleRelease(e), { passive: false });
      
      btn.addEventListener("pointerleave", (e) => handleRelease(e));
      btn.addEventListener("pointercancel", (e) => handleRelease(e));
      btn.addEventListener("touchcancel", (e) => handleRelease(e), { passive: false });
      
      btn.addEventListener("contextmenu", (e) => e.preventDefault());
    });

    /* --- keyboard arrow controls --- */
    const keyMap = {ArrowUp:"fwd", ArrowDown:"back", ArrowLeft:"left", ArrowRight:"right"};
    const keysDown = new Set();
    document.addEventListener("keydown", (e) => {
      if (!keyMap[e.key] || keysDown.has(e.key)) return;
      keysDown.add(e.key);
      const kind = keyMap[e.key];
      setButtonActive(kind, true);
      drive(kind);
    });
    document.addEventListener("keyup", (e) => {
      if (!keyMap[e.key]) return;
      keysDown.delete(e.key);
      const kind = keyMap[e.key];
      setButtonActive(kind, false);
      if (keysDown.size === 0) post("/api/stop");
    });

    document.querySelector("#stop").onclick   = () => {
      const stopBtn = document.querySelector("#stop");
      stopBtn.classList.add("active-drive");
      setTimeout(() => stopBtn.classList.remove("active-drive"), 150);
      post("/api/stop");
    };
    document.querySelector("#return").onclick = () => post("/api/return");
    document.querySelector("#reset").onclick  = () => post("/api/reset_odom");
    document.querySelector("#arm").onclick    = () => post("/api/arm", {
      steps: Number(document.querySelector("#armSteps").value),
      speed: Number(document.querySelector("#armSpeed").value)
    });
    speed.oninput = () => speedValue.textContent = speed.value;
    steer.oninput = () => steerValue.textContent = steer.value;

    /* --- safe getter: prevents crash when telemetry/obstacles is empty --- */
    function get(obj, key, fallback) {
      if (obj && obj[key] !== undefined && obj[key] !== null) return obj[key];
      return fallback;
    }

    async function refresh() {
      try {
        const res = await fetch("/api/status");
        const data = await res.json();
        const tel = data.telemetry || {};
        const obs = data.obstacles || {};

        document.querySelector("#dot").classList.toggle("on", data.connected);
        document.querySelector("#conn").textContent = data.connected ? `Connected ${data.port}` : "Disconnected";

        document.querySelector("#bat").textContent   = get(tel, "BAT", "--");
        document.querySelector("#spd").textContent   = get(tel, "SPD", "--");
        document.querySelector("#dist").textContent  = get(tel, "DIST", "--");
        document.querySelector("#fl").textContent    = get(obs, "FL", "--");
        document.querySelector("#front").textContent = get(obs, "F", "--");
        document.querySelector("#fr").textContent    = get(obs, "FR", "--");

        document.querySelector("#log").textContent = (data.log || []).join("\n");

        /* sync slider max with server config */
        if (data.max_speed) {
          speed.max = data.max_speed;
          steer.max = data.max_steer || data.max_speed;
        }
      } catch (err) {
        /* network glitch — will retry automatically */
      }
    }
    setInterval(refresh, 400);
    refresh();
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    try:
        bridge.start()
        app.run(host=APP_HOST, port=APP_PORT, threaded=True)
    finally:
        bridge.stop()
