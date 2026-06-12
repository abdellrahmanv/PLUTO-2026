from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import math


OUT_DIR = Path(__file__).resolve().parents[1] / "docs" / "figures"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PNG = OUT_DIR / "pluto_runtime_flowchart_professional.png"
PDF = OUT_DIR / "pluto_runtime_flowchart_professional.pdf"

W, H = 4200, 2800
BG = "#f8fafc"
INK = "#0f172a"
MUTED = "#475569"
LINE = "#334155"

PALETTE = {
    "boot": ("#dbeafe", "#1d4ed8"),
    "idle": ("#dcfce7", "#15803d"),
    "manual": ("#fef3c7", "#b45309"),
    "dance": ("#ede9fe", "#6d28d9"),
    "welcome": ("#cffafe", "#0e7490"),
    "error": ("#fee2e2", "#b91c1c"),
    "safety": ("#fff1f2", "#e11d48"),
    "neutral": ("#ffffff", "#334155"),
    "disabled": ("#e2e8f0", "#64748b"),
}


def get_font(size, bold=False):
    candidates = [
        ("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
        ("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        ("C:/Windows/Fonts/calibrib.ttf" if bold else "C:/Windows/Fonts/calibri.ttf"),
    ]
    for c in candidates:
        if Path(c).exists():
            return ImageFont.truetype(c, size)
    return ImageFont.load_default()


img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)

F_TITLE = get_font(72, True)
F_SUB = get_font(36)
F_SECTION = get_font(34, True)
F_BOX = get_font(29, True)
F_TEXT = get_font(27)
F_SMALL = get_font(23)
F_TINY = get_font(20)


def bbox(text, font, spacing=6):
    b = d.multiline_textbbox((0, 0), text, font=font, spacing=spacing)
    return b[2] - b[0], b[3] - b[1]


def wrap(text, chars):
    lines = []
    cur = ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if len(trial) <= chars:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return "\n".join(lines)


def rounded_rect(x0, y0, x1, y1, fill, outline, r=24, width=4):
    d.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=fill, outline=outline, width=width)


def shadow_rect(x0, y0, x1, y1, r=24):
    d.rounded_rectangle([x0 + 8, y0 + 10, x1 + 8, y1 + 10], radius=r, fill="#dbe4ee")


def card(x, y, w, h, title, body, theme="neutral", title_size=F_BOX, body_size=F_SMALL):
    fill, outline = PALETTE[theme]
    shadow_rect(x, y, x + w, y + h)
    rounded_rect(x, y, x + w, y + h, fill, outline, r=26, width=4)
    d.rounded_rectangle([x, y, x + 18, y + h], radius=18, fill=outline)
    tw, th = bbox(title, title_size)
    d.multiline_text((x + 38, y + 24), title, font=title_size, fill=INK, spacing=5)
    if body:
        d.multiline_text((x + 38, y + 24 + th + 16), body, font=body_size, fill=MUTED, spacing=7)
    return (x, y, x + w, y + h)


def decision(cx, cy, w, h, text, theme="neutral"):
    fill, outline = PALETTE[theme]
    pts = [(cx, cy - h / 2), (cx + w / 2, cy), (cx, cy + h / 2), (cx - w / 2, cy)]
    d.polygon(pts, fill=fill)
    d.line(pts + [pts[0]], fill=outline, width=4)
    tw, th = bbox(text, F_SMALL, spacing=5)
    d.multiline_text((cx - tw / 2, cy - th / 2), text, font=F_SMALL, fill=INK, align="center", spacing=5)
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def arrow(start, end, color=LINE, width=4, label=None, label_shift=(0, 0)):
    x1, y1 = start
    x2, y2 = end
    d.line([start, end], fill=color, width=width)
    angle = math.atan2(y2 - y1, x2 - x1)
    length = 22
    a1 = angle + math.pi * 0.82
    a2 = angle - math.pi * 0.82
    head = [
        (x2, y2),
        (x2 + length * math.cos(a1), y2 + length * math.sin(a1)),
        (x2 + length * math.cos(a2), y2 + length * math.sin(a2)),
    ]
    d.polygon(head, fill=color)
    if label:
        lx = (x1 + x2) / 2 + label_shift[0]
        ly = (y1 + y2) / 2 + label_shift[1]
        tw, th = bbox(label, F_TINY)
        d.rounded_rectangle([lx - tw / 2 - 12, ly - th / 2 - 6, lx + tw / 2 + 12, ly + th / 2 + 6],
                            radius=10, fill="#ffffff", outline="#cbd5e1", width=2)
        d.text((lx - tw / 2, ly - th / 2), label, font=F_TINY, fill=color)


def poly_arrow(points, color=LINE, width=4, label=None, label_at=0):
    for a, b in zip(points, points[1:]):
        d.line([a, b], fill=color, width=width)
    arrow(points[-2], points[-1], color=color, width=width)
    if label:
        lx, ly = points[label_at]
        tw, th = bbox(label, F_TINY)
        d.rounded_rectangle([lx - tw / 2 - 12, ly - th / 2 - 6, lx + tw / 2 + 12, ly + th / 2 + 6],
                            radius=10, fill="#ffffff", outline="#cbd5e1", width=2)
        d.text((lx - tw / 2, ly - th / 2), label, font=F_TINY, fill=color)


def section(x, y, w, h, title, theme):
    fill, outline = PALETTE[theme]
    d.rounded_rectangle([x, y, x + w, y + h], radius=38, fill=fill, outline=outline, width=5)
    d.text((x + 30, y + 22), title, font=F_SECTION, fill=outline)


# Title
title = "PLUTO Runtime Software State Machine"
tw, _ = bbox(title, F_TITLE)
d.text(((W - tw) / 2, 52), title, font=F_TITLE, fill=INK)
subtitle = "Book-ready overview of boot validation, idle supervision, operating modes, and safety recovery"
tw, _ = bbox(subtitle, F_SUB)
d.text(((W - tw) / 2, 140), subtitle, font=F_SUB, fill=MUTED)

# Column sections
section(120, 240, 760, 2180, "Boot & Validation", "boot")
section(980, 240, 760, 2180, "Idle Supervisor", "idle")
section(1840, 240, 1040, 2180, "Motion Modes", "neutral")
section(2980, 240, 1100, 2180, "Welcome Interaction", "welcome")

# Global safety band
rounded_rect(120, 2480, 4080, 2710, "#fff7ed", "#ea580c", r=34, width=5)
d.text((160, 2516), "Global safety rule", font=F_SECTION, fill="#c2410c")
d.multiline_text(
    (160, 2570),
    "Any critical fault from any state forces CMD:STOP, enters ERROR, rejects motion requests, and requires operator reset before returning to IDLE.",
    font=F_TEXT,
    fill=INK,
    spacing=8,
)

# Boot flow
b1 = card(230, 330, 540, 120, "Power ON / Pi Boot", "System starts with motion disabled.", "boot")
b2 = card(230, 510, 540, 145, "Bootstrap", "Set all motion intent to zero.\nLoad Python runtime and services.", "boot")
b3 = card(230, 720, 540, 145, "Hardware Detection", "Find STM32, camera, mic, speaker,\nand optional Uno face controller.", "boot")
d1 = decision(500, 990, 420, 160, "Required\nhardware OK?", "boot")
b4 = card(230, 1160, 540, 125, "Pre-IDLE Stop", "Send CMD:STOP to STM32 before enabling modes.", "boot")
d2 = decision(500, 1430, 400, 150, "Battery\ncritical?", "boot")
arrow((500, 450), (500, 510), PALETTE["boot"][1])
arrow((500, 655), (500, 720), PALETTE["boot"][1])
arrow((500, 865), (500, 910), PALETTE["boot"][1])
arrow((500, 1070), (500, 1160), PALETTE["boot"][1], label="Yes", label_shift=(55, -6))
arrow((500, 1285), (500, 1355), PALETTE["boot"][1])

# Idle
i0 = card(1090, 330, 540, 115, "IDLE", "Default safe waiting state.", "idle", F_SECTION, F_SMALL)
i1 = card(1090, 510, 540, 130, "Heartbeat + Telemetry", "Keep STM32 alive.\nRead TEL / OBS / ALERT.", "idle")
i2 = card(1090, 700, 540, 130, "Update Interface", "Show idle face, website status,\ncamera and audio health.", "idle")
d_idle = decision(1360, 990, 450, 170, "Operator or\ntrigger request?", "idle")
i3 = card(1090, 1220, 540, 125, "No Request", "Remain in IDLE and continue supervision.", "idle")
i4 = card(1090, 1440, 540, 125, "GAME_LATER", "Show unavailable response,\nthen return to IDLE.", "disabled")
arrow((1360, 445), (1360, 510), PALETTE["idle"][1])
arrow((1360, 640), (1360, 700), PALETTE["idle"][1])
arrow((1360, 830), (1360, 905), PALETTE["idle"][1])
arrow((1360, 1075), (1360, 1220), PALETTE["idle"][1], label="No")
poly_arrow([(1360, 1345), (1360, 1390), (1360, 1440)], PALETTE["disabled"][1], label="Game request", label_at=1)
poly_arrow([(1360, 1565), (1360, 1660), (1060, 1660), (1060, 390), (1090, 390)], PALETTE["idle"][1])

# Error lock
err = card(230, 1730, 540, 145, "ERROR Safe Lock", "Send CMD:STOP.\nShow fault reason.\nReject all motion requests.", "error")
derr = decision(500, 2050, 430, 160, "Operator reset\nand fault cleared?", "error")
arrow((500, 1505), (500, 1730), PALETTE["error"][1], label="Yes")
arrow((500, 1875), (500, 1970), PALETTE["error"][1])
poly_arrow([(715, 2050), (920, 2050), (920, 390), (1090, 390)], PALETTE["idle"][1], label="Yes", label_at=1)
poly_arrow([(285, 990), (130, 990), (130, 1800), (230, 1800)], PALETTE["error"][1], label="No", label_at=1)
poly_arrow([(700, 1430), (840, 1430), (840, 1800), (770, 1800)], PALETTE["error"][1], label="Yes", label_at=1)
poly_arrow([(500, 2210), (500, 2320), (215, 2320), (215, 2050), (285, 2050)], PALETTE["error"][1], label="No", label_at=2)

# Mode cards
m1 = card(1940, 365, 820, 380, "MANUAL Mode", "1. Send CMD:STOP before enabling controls.\n2. Accept only held operator input.\n3. Clamp speed and steering.\n4. Send CMD:DRIVE only while input is held.\n5. Input released, STOP pressed, STM32 alert, or E-stop → CMD:STOP.", "manual")
m2 = card(1940, 875, 820, 410, "DANCE Mode", "1. Verify STM32 and audio output.\n2. Send CMD:STOP before dance.\n3. Play preloaded audio.\n4. Execute bounded moonwalk pattern inside the safe area.\n5. Obstacle, audio fault, STM32 alert, E-stop, song end, or operator stop → CMD:STOP.", "dance")
m3 = card(1940, 1420, 820, 260, "Unavailable / Future Modes", "GAME is documented but not implemented in v1.\nA request receives a clear unavailable response and returns to IDLE.", "disabled")
poly_arrow([(1585, 990), (1840, 990), (1840, 500), (1940, 500)], PALETTE["manual"][1], label="Manual", label_at=1)
poly_arrow([(1585, 990), (1795, 990), (1795, 1070), (1940, 1070)], PALETTE["dance"][1], label="Dance", label_at=1)
poly_arrow([(1585, 990), (1780, 990), (1780, 1520), (1940, 1520)], PALETTE["disabled"][1], label="Game", label_at=1)
for y, theme in [(685, "manual"), (1245, "dance"), (1640, "disabled")]:
    poly_arrow([(2760, y), (2870, y), (2870, 2280), (1360, 2280), (1360, 445)], PALETTE["idle"][1], label="Exit to IDLE", label_at=1)

# Welcome detailed flow
w0 = card(3090, 330, 760, 115, "WELCOME Mode", "Triggered by confirmed wave / welcome request.", "welcome", F_SECTION, F_SMALL)
w1 = card(3090, 515, 760, 120, "Save Base Reference", "Reset or store odometry home before approach.", "welcome")
w2 = card(3090, 695, 760, 125, "WELCOME_DETECT", "Detect humans and select one active target.", "welcome")
w3 = card(3090, 885, 760, 135, "WELCOME_APPROACH", "Slow bounded movement toward target.\nObstacle and uncertainty checks stay active.", "welcome")
dw1 = decision(3470, 1185, 470, 170, "Obstacle, target lost,\nor uncertainty?", "error")
dw2 = decision(3470, 1450, 440, 160, "Greeting distance\nreached?", "welcome")
w4 = card(3090, 1625, 760, 110, "WELCOME_ARRIVED", "Send CMD:STOP at greeting distance.", "welcome")
w5 = card(3090, 1815, 760, 135, "WELCOME_TALK", "Greet the user and answer with simple fast responses.", "welcome")
w6 = card(3090, 2025, 760, 130, "WELCOME_RETURN Locked", "Return to base. All other mode requests are blocked.", "welcome")
dw3 = decision(3470, 2310, 430, 150, "Return\ncomplete?", "welcome")
arrow((3470, 445), (3470, 515), PALETTE["welcome"][1])
arrow((3470, 635), (3470, 695), PALETTE["welcome"][1])
arrow((3470, 820), (3470, 885), PALETTE["welcome"][1])
arrow((3470, 1020), (3470, 1100), PALETTE["welcome"][1])
arrow((3470, 1270), (3470, 1370), PALETTE["welcome"][1], label="No")
arrow((3470, 1530), (3470, 1625), PALETTE["welcome"][1], label="Yes")
arrow((3470, 1735), (3470, 1815), PALETTE["welcome"][1])
arrow((3470, 1950), (3470, 2025), PALETTE["welcome"][1])
arrow((3470, 2155), (3470, 2235), PALETTE["welcome"][1])
poly_arrow([(3235, 1185), (2960, 1185), (2960, 2090), (3090, 2090)], PALETTE["error"][1], label="Yes: STOP then return/error", label_at=1)
poly_arrow([(3685, 2310), (3930, 2310), (3930, 390), (1630, 390)], PALETTE["idle"][1], label="Yes", label_at=1)
poly_arrow([(3470, 2385), (3470, 2470), (2780, 2470), (2780, 1800), (770, 1800)], PALETTE["error"][1], label="No / timeout / fault", label_at=1)
poly_arrow([(1585, 990), (1810, 990), (1810, 260), (3470, 260), (3470, 330)], PALETTE["welcome"][1], label="Welcome trigger", label_at=1)

# Critical alert arrows to error, with thin red lines
for start in [(1360, 510), (1940, 580), (1940, 1090), (3090, 955)]:
    poly_arrow([start, (start[0] - 30, start[1]), (start[0] - 30, 1800), (770, 1800)],
               PALETTE["error"][1], width=3)

# Legend
d.text((160, 2650), "Legend:", font=F_BOX, fill=INK)
legend = [
    ("Boot / validation", "boot"),
    ("Idle supervisor", "idle"),
    ("Manual motion", "manual"),
    ("Dance motion", "dance"),
    ("Welcome interaction", "welcome"),
    ("Error / safe stop", "error"),
]
x = 310
for label, theme in legend:
    fill, outline = PALETTE[theme]
    d.rounded_rectangle([x, 2652, x + 38, 2690], radius=8, fill=fill, outline=outline, width=3)
    d.text((x + 52, 2654), label, font=F_TINY, fill=INK)
    x += 520

img.save(PNG, quality=96)
img.convert("RGB").save(PDF, "PDF", resolution=300.0)
print(PNG)
print(PDF)
