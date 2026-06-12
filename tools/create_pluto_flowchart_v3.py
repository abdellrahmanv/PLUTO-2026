from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import math


OUT_DIR = Path(__file__).resolve().parents[1] / "docs" / "figures"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PNG = OUT_DIR / "pluto_runtime_flowchart_professional_v3.png"
PDF = OUT_DIR / "pluto_runtime_flowchart_professional_v3.pdf"

W, H = 4600, 3100
BG = "#f8fafc"
INK = "#0f172a"
MUTED = "#475569"
GRID = "#e2e8f0"

THEME = {
    "boot": ("#eff6ff", "#2563eb", "#dbeafe"),
    "idle": ("#f0fdf4", "#15803d", "#dcfce7"),
    "manual": ("#fffbeb", "#d97706", "#fef3c7"),
    "dance": ("#f5f3ff", "#7c3aed", "#ede9fe"),
    "welcome": ("#ecfeff", "#0891b2", "#cffafe"),
    "error": ("#fff1f2", "#dc2626", "#fee2e2"),
    "neutral": ("#ffffff", "#334155", "#f1f5f9"),
    "future": ("#f8fafc", "#64748b", "#e2e8f0"),
}


def f(size, bold=False):
    paths = [
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for p in paths:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)

FTITLE = f(78, True)
FSUB = f(35)
FSEC = f(36, True)
FH = f(32, True)
FN = f(27)
FS = f(23)
FXS = f(19)


def size(text, font, spacing=6):
    b = d.multiline_textbbox((0, 0), text, font=font, spacing=spacing)
    return b[2] - b[0], b[3] - b[1]


def arrow(a, b, color="#334155", width=4, label=None, label_dx=0, label_dy=0):
    d.line([a, b], fill=color, width=width)
    x1, y1 = a
    x2, y2 = b
    ang = math.atan2(y2 - y1, x2 - x1)
    L = 22
    pts = [
        (x2, y2),
        (x2 + L * math.cos(ang + 2.55), y2 + L * math.sin(ang + 2.55)),
        (x2 + L * math.cos(ang - 2.55), y2 + L * math.sin(ang - 2.55)),
    ]
    d.polygon(pts, fill=color)
    if label:
        mx = (x1 + x2) / 2 + label_dx
        my = (y1 + y2) / 2 + label_dy
        tw, th = size(label, FXS)
        d.rounded_rectangle([mx - tw / 2 - 10, my - th / 2 - 5, mx + tw / 2 + 10, my + th / 2 + 5],
                            radius=10, fill="#ffffff", outline="#cbd5e1", width=2)
        d.text((mx - tw / 2, my - th / 2), label, font=FXS, fill=color)


def poly(points, color="#334155", width=4, label=None, label_point=0):
    for a, b in zip(points, points[1:]):
        d.line([a, b], fill=color, width=width)
    arrow(points[-2], points[-1], color=color, width=width)
    if label:
        x, y = points[label_point]
        tw, th = size(label, FXS)
        d.rounded_rectangle([x - tw / 2 - 10, y - th / 2 - 5, x + tw / 2 + 10, y + th / 2 + 5],
                            radius=10, fill="#ffffff", outline="#cbd5e1", width=2)
        d.text((x - tw / 2, y - th / 2), label, font=FXS, fill=color)


def section(x, y, w, h, title, theme):
    bg, line, _ = THEME[theme]
    d.rounded_rectangle([x, y, x + w, y + h], radius=34, fill=bg, outline=line, width=5)
    d.text((x + 28, y + 22), title, font=FSEC, fill=line)


def card(x, y, w, h, title, body, theme, small=False):
    bg, line, fill = THEME[theme]
    d.rounded_rectangle([x + 7, y + 8, x + w + 7, y + h + 8], radius=24, fill="#dbe4ee")
    d.rounded_rectangle([x, y, x + w, y + h], radius=24, fill="#ffffff", outline=line, width=4)
    d.rounded_rectangle([x, y, x + 18, y + h], radius=18, fill=line)
    d.text((x + 38, y + 22), title, font=FH if not small else FS, fill=INK)
    if body:
        d.multiline_text((x + 38, y + 66), body, font=FS if not small else FXS, fill=MUTED, spacing=7)
    return (x, y, x + w, y + h)


def decision(cx, cy, w, h, text, theme):
    _, line, fill = THEME[theme]
    pts = [(cx, cy - h / 2), (cx + w / 2, cy), (cx, cy + h / 2), (cx - w / 2, cy)]
    d.polygon(pts, fill="#ffffff")
    d.line(pts + [pts[0]], fill=line, width=4)
    tw, th = size(text, FS, spacing=5)
    d.multiline_text((cx - tw / 2, cy - th / 2), text, font=FS, fill=INK, align="center", spacing=5)
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def connector(x, y, label, theme):
    _, line, fill = THEME[theme]
    d.ellipse([x - 34, y - 34, x + 34, y + 34], fill=fill, outline=line, width=4)
    tw, th = size(label, FH)
    d.text((x - tw / 2, y - th / 2 - 2), label, font=FH, fill=line)
    return (x, y)


# Title
title = "PLUTO Runtime Software Flowchart"
tw, _ = size(title, FTITLE)
d.text(((W - tw) / 2, 50), title, font=FTITLE, fill=INK)
subtitle = "A safety-supervised state machine: boot validation, idle supervision, operating modes, and recovery"
tw, _ = size(subtitle, FSUB)
d.text(((W - tw) / 2, 142), subtitle, font=FSUB, fill=MUTED)

# Sections
section(120, 250, 1180, 1060, "1. Boot and Entry Safety", "boot")
section(1380, 250, 1030, 1060, "2. IDLE Supervisor", "idle")
section(2490, 250, 1990, 1060, "3. Safe Error Recovery", "error")
section(120, 1430, 1360, 1180, "4. MANUAL Mode", "manual")
section(1620, 1430, 1360, 1180, "5. DANCE Mode", "dance")
section(3120, 1430, 1360, 1180, "6. WELCOME Mode", "welcome")

# Boot flow
card(220, 370, 440, 120, "Power ON / Pi Boot", "Robot starts with all motion disabled.", "boot", True)
card(220, 550, 440, 130, "Bootstrap", "Set motion intent to zero.\nLoad runtime services.", "boot", True)
card(220, 750, 440, 145, "Hardware Detection", "Detect STM32, camera, mic,\nspeaker, and optional Uno.", "boot", True)
decision(440, 1040, 380, 150, "Required\nhardware OK?", "boot")
card(760, 765, 430, 130, "Pre-IDLE Stop", "Send CMD:STOP to STM32\nbefore enabling modes.", "boot", True)
decision(975, 1040, 350, 140, "Battery\ncritical?", "boot")
connector(210, 1040, "E", "error")
connector(1195, 1185, "E", "error")
arrow((440, 490), (440, 550), THEME["boot"][1])
arrow((440, 680), (440, 750), THEME["boot"][1])
arrow((440, 895), (440, 965), THEME["boot"][1])
arrow((630, 1040), (760, 830), THEME["boot"][1], label="Yes")
arrow((975, 895), (975, 970), THEME["boot"][1])
arrow((250, 1040), (244, 1040), THEME["error"][1], label="No")
poly([(1148, 1040), (1195, 1040), (1195, 1151)], THEME["error"][1], label="Yes", label_point=1)

# Idle supervisor
card(1500, 385, 790, 130, "IDLE", "Default safe waiting state. No autonomous motion is started here.", "idle")
card(1500, 585, 790, 150, "Continuous Supervision", "Keep STM32 heartbeat active.\nRead telemetry, ultrasonic distances, MPU, and alerts.", "idle")
card(1500, 815, 790, 145, "Interface Update", "Update website status, camera preview, idle face,\nand operator controls.", "idle")
decision(1895, 1110, 430, 150, "Valid mode\nrequest?", "idle")
arrow((1895, 515), (1895, 585), THEME["idle"][1])
arrow((1895, 735), (1895, 815), THEME["idle"][1])
arrow((1895, 960), (1895, 1035), THEME["idle"][1])
poly([(1895, 1185), (1895, 1260), (1420, 1260), (1420, 450), (1500, 450)], THEME["idle"][1], label="No: remain IDLE", label_point=1)

# Error recovery
card(2670, 385, 720, 150, "ERROR Safe Lock", "Send CMD:STOP if STM32 is connected.\nShow fault reason and reject motion requests.", "error")
decision(3030, 705, 430, 150, "Operator reset\nrequested?", "error")
decision(3030, 965, 470, 160, "Fault cleared\nand STM32 verified?", "error")
card(3510, 635, 760, 170, "Global Fault Sources", "Emergency stop, critical STM32 alert, battery fault,\ncommunication timeout, unsafe obstacle condition,\nor return timeout from any motion state.", "error")
connector(3820, 1020, "E", "error")
arrow((3030, 535), (3030, 630), THEME["error"][1])
arrow((3030, 780), (3030, 885), THEME["error"][1], label="Yes")
poly([(3265, 965), (3480, 965), (3480, 1020), (3786, 1020)], THEME["error"][1], label="No / still unsafe", label_point=1)
poly([(2795, 965), (2420, 965), (2420, 450), (2290, 450)], THEME["idle"][1], label="Yes: return to IDLE", label_point=1)

# Boot to idle/error connectors
poly([(1150, 1040), (1260, 1040), (1260, 460), (1500, 460)], THEME["idle"][1], label="No", label_point=1)

# Mode request routing
poly([(2110, 1110), (2490, 1110), (2490, 1360), (800, 1360), (800, 1430)], THEME["manual"][1], label="Manual selected", label_point=2)
poly([(2110, 1110), (2490, 1110), (2490, 1360), (2300, 1360), (2300, 1430)], THEME["dance"][1], label="Dance selected", label_point=2)
poly([(2110, 1110), (2490, 1110), (2490, 1360), (3800, 1360), (3800, 1430)], THEME["welcome"][1], label="Welcome trigger confirmed", label_point=2)

# Manual mode
card(250, 1560, 500, 120, "Entry Guard", "Send CMD:STOP before controls activate.", "manual", True)
card(250, 1760, 500, 130, "Operator Input", "Accept only held input.\nNo latched motion.", "manual", True)
card(250, 1980, 500, 130, "Command Limiter", "Clamp base speed and steer\nbefore CMD:DRIVE.", "manual", True)
card(850, 1760, 500, 160, "Exit Conditions", "Input released, STOP pressed,\nSTM32 disconnect, alert, or E-stop.", "manual", True)
connector(1110, 2100, "A", "idle")
connector(1280, 2100, "E", "error")
arrow((500, 1680), (500, 1760), THEME["manual"][1])
arrow((500, 1890), (500, 1980), THEME["manual"][1])
arrow((750, 2045), (850, 1840), THEME["manual"][1])
arrow((1110, 1920), (1110, 2066), THEME["idle"][1], label="Normal STOP")
arrow((1280, 1920), (1280, 2066), THEME["error"][1], label="Fault")

# Dance mode
card(1750, 1560, 500, 120, "Entry Guard", "Verify STM32 and audio output.\nSend CMD:STOP before dance.", "dance", True)
card(1750, 1760, 500, 150, "Bounded Performance", "Play Billie Jean audio.\nRun small moonwalk pattern\ninside the safe dance area.", "dance", True)
card(2350, 1670, 500, 170, "Safety During Dance", "Obstacle, audio fault,\nSTM32 alert, E-stop, song end,\nor operator stop → CMD:STOP.", "dance", True)
connector(2470, 2100, "A", "idle")
connector(2640, 2100, "E", "error")
arrow((2000, 1680), (2000, 1760), THEME["dance"][1])
arrow((2250, 1835), (2350, 1755), THEME["dance"][1])
arrow((2470, 1840), (2470, 2066), THEME["idle"][1], label="Normal end")
arrow((2640, 1840), (2640, 2066), THEME["error"][1], label="Critical fault")

# Welcome mode
card(3260, 1545, 500, 115, "Save Base", "Store odometry reference.", "welcome", True)
card(3260, 1715, 500, 125, "WELCOME_DETECT", "Detect humans and select\none active target.", "welcome", True)
card(3260, 1905, 500, 165, "WELCOME_APPROACH", "Slow bounded approach.\nStop on obstacle, lost target,\nor uncertainty.", "welcome", True)
card(3860, 1715, 500, 125, "WELCOME_TALK", "Greet user and answer\nsimple fast responses.", "welcome", True)
card(3860, 1905, 500, 165, "WELCOME_RETURN", "Locked return to base.\nIgnore new mode requests\nuntil return completes.", "welcome", True)
connector(4110, 2180, "A", "idle")
connector(4280, 2180, "E", "error")
arrow((3510, 1660), (3510, 1715), THEME["welcome"][1])
arrow((3510, 1840), (3510, 1905), THEME["welcome"][1])
arrow((3760, 1975), (3860, 1775), THEME["welcome"][1], label="Arrived")
arrow((4110, 1840), (4110, 1905), THEME["welcome"][1])
arrow((4110, 2070), (4110, 2146), THEME["idle"][1], label="Return complete")
arrow((4280, 2070), (4280, 2146), THEME["error"][1], label="Timeout / fault")

# Connector explanation strip
d.rounded_rectangle([120, 2680, 4480, 2800], radius=28, fill="#ffffff", outline=GRID, width=3)
d.text((160, 2712), "Connectors:", font=FH, fill=INK)
d.text((380, 2716), "A = normal exit back to IDLE", font=FN, fill=THEME["idle"][1])
d.text((960, 2716), "E = enter ERROR safe lock", font=FN, fill=THEME["error"][1])
d.text((1540, 2716), "All motion states pass through STM32 safety supervision before any motor command reaches the hoverboard.", font=FN, fill=MUTED)

# Legend
legend_y = 2880
d.text((160, legend_y), "Color key:", font=FH, fill=INK)
x = 410
for name, key in [
    ("Boot", "boot"),
    ("Idle", "idle"),
    ("Manual", "manual"),
    ("Dance", "dance"),
    ("Welcome", "welcome"),
    ("Error", "error"),
]:
    _, line, fill = THEME[key]
    d.rounded_rectangle([x, legend_y + 4, x + 42, legend_y + 46], radius=8, fill=fill, outline=line, width=3)
    d.text((x + 58, legend_y + 7), name, font=FS, fill=INK)
    x += 520

img.save(PNG, quality=96)
img.convert("RGB").save(PDF, "PDF", resolution=300.0)
print(PNG)
print(PDF)
