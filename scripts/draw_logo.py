"""The website logo (static/dashboard/img/apwrs-logo.png, 59 x 50 px) redrawn
as shapes, so the phone app can use it at any size without blur: the green
oval, "ABCDryBASIN", two water drops, the plant and the cracked orange soil.

Coordinates are in the original 59 x 50 pixel grid; `logo(width)` draws it
`width` pixels wide on a transparent background.

    py -3.11 scripts/draw_logo.py      # writes a preview next to the original
"""
import math
import pathlib

from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parents[1]
FONT = ROOT / 'mobile' / 'assets' / 'fonts' / 'HankenGrotesk-800.ttf'

W, H = 59, 50
RING = (92, 182, 112)
TEXT = (38, 104, 196)
DROP = (150, 216, 240)
DROP_EDGE = (78, 160, 214)
SOIL_TOP = (238, 132, 76)
SOIL_BOTTOM = (204, 90, 46)
SOIL_LINE = (246, 214, 176)
CRACK = (112, 38, 28)
STEM = (70, 136, 58)
LEAF_DARK = (58, 128, 48)
LEAF_LIGHT = (150, 200, 86)

OVAL = (1.0, 0.2, 58.0, 47.6)
SOIL_Y = 24.4


def _leaf(img, s, base, tip, width):
    """A leaf from `base` to `tip`, `width` across, dark along the midrib
    side and lighter on the other, like the logo's shaded leaves."""
    (bx, by), (tx, ty) = base, tip
    length = math.hypot(tx - bx, ty - by)
    ang = math.atan2(ty - by, tx - bx)
    pts_l, pts_r = [], []
    for i in range(41):
        u = i / 40
        half = width / 2 * math.sin(math.pi * u) ** 0.85
        x = bx + (tx - bx) * u
        y = by + (ty - by) * u
        nx, ny = -math.sin(ang), math.cos(ang)
        pts_l.append(((x + nx * half) * s, (y + ny * half) * s))
        pts_r.append(((x - nx * half * 0.9) * s, (y - ny * half * 0.9) * s))
    d = ImageDraw.Draw(img)
    mid = [(bx * s + (tx - bx) * s * i / 40, by * s + (ty - by) * s * i / 40) for i in range(41)]
    d.polygon(pts_l + mid[::-1], fill=LEAF_LIGHT)
    d.polygon(pts_r + mid[::-1], fill=LEAF_DARK)
    d.line(mid[2:-6], fill=(44, 104, 40), width=max(1, round(s * 0.18)))
    return length


def _drop(d, s, cx, cy):
    """The logo's light-blue drop: round on top, coming to a point below."""
    r = 3.0
    pts = []
    for i in range(61):
        a = math.pi * (1 + i / 60)  # upper half circle, left to right
        pts.append((cx + r * math.cos(a), cy - 0.6 + r * math.sin(a)))
    pts += [(cx + r, cy - 0.6), (cx + r * 0.45, cy + 2.2), (cx, cy + 3.6), (cx - r * 0.45, cy + 2.2), (cx - r, cy - 0.6)]
    d.polygon([(x * s, y * s) for x, y in pts], fill=DROP, outline=DROP_EDGE, width=max(1, round(s * 0.3)))
    d.ellipse([(cx - 1.9) * s, (cy - 2.9) * s, (cx - 0.5) * s, (cy - 1.5) * s], fill=(236, 249, 255))


def _quad(p0, p1, p2, n=40):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]) for t in (i / n for i in range(n + 1))]


def logo(width):
    """The logo `width` px wide (height keeps the 59:50 shape), transparent around the oval."""
    s = width * 4 / W  # draw 4x larger, then shrink: smooth edges
    big = (round(W * s), round(H * s))
    img = Image.new('RGBA', big, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    box = [c * s for c in OVAL]

    # Inside of the oval: white sky over orange soil.
    inside = Image.new('RGBA', big, (255, 255, 255, 255))
    soil = Image.new('RGBA', big)
    sd = ImageDraw.Draw(soil)
    for y in range(round(SOIL_Y * s), big[1]):
        t = (y / s - SOIL_Y) / (OVAL[3] - SOIL_Y)
        col = tuple(round(SOIL_TOP[i] + (SOIL_BOTTOM[i] - SOIL_TOP[i]) * t) for i in range(3))
        sd.line([(0, y), (big[0], y)], fill=col + (255,))
    inside.alpha_composite(soil)
    ImageDraw.Draw(inside).line([(0, SOIL_Y * s), (big[0], SOIL_Y * s)], fill=SOIL_LINE, width=round(s * 0.7))
    mask = Image.new('L', big, 0)
    ImageDraw.Draw(mask).ellipse(box, fill=255)
    img.paste(inside, (0, 0), mask)
    d = ImageDraw.Draw(img)

    # Cracks in the soil, from the foot of the plant.
    cw = max(1, round(s * 0.55))
    for path in [
        [(27.6, 33.2), (24.5, 32.2), (21.5, 32.0), (18.5, 31.0), (16.5, 30.2)],
        [(21.5, 32.0), (19.5, 33.6)],
        [(28.6, 33.2), (31.5, 32.4), (34.5, 32.2), (37.0, 31.0), (39.5, 30.4), (47.5, 30.2)],
        [(29.0, 33.6), (30.0, 35.4), (31.8, 36.8), (34.0, 38.2), (36.6, 38.4), (37.5, 40.0)],
        [(36.6, 38.4), (39.6, 38.0)],
        [(36.4, 40.4), (36.2, 42.6)],
    ]:
        d.line([(x * s, y * s) for x, y in path], fill=CRACK, width=cw, joint='curve')

    # Stem, a soft curve from the soil up to the bud.
    stem = _quad((28.5, 34.5), (28.0, 21.0), (25.5, 8.6))
    d.line([(x * s, y * s) for x, y in stem], fill=STEM, width=round(s * 1.5), joint='curve')

    # Leaves: two pairs and the bud on top.
    _leaf(img, s, (27.6, 26.0), (16.0, 19.0), 6.6)
    _leaf(img, s, (28.6, 25.0), (41.5, 17.6), 7.4)
    _leaf(img, s, (26.0, 17.0), (17.6, 11.6), 5.2)
    _leaf(img, s, (26.6, 16.0), (34.0, 10.4), 5.4)
    _leaf(img, s, (25.8, 12.6), (25.2, 7.4), 3.0)

    d = ImageDraw.Draw(img)
    _drop(d, s, 10.6, 12.6)
    _drop(d, s, 47.8, 12.4)

    # "ABCDryBASIN" across the top of the oval.
    font = ImageFont.truetype(str(FONT), round(3.3 * s))
    text = 'ABCDryBASIN'
    tw = d.textlength(text, font=font)
    d.text((29.6 * s - tw / 2, 6.6 * s), text, font=font, fill=TEXT, anchor='lm')

    # The green ring around everything.
    d.ellipse(box, outline=RING, width=round(s * 1.1))
    return img.resize((width, round(width * H / W)), Image.LANCZOS)


if __name__ == '__main__':
    out = ROOT / 'mobile' / 'build' / 'logo_preview.png'
    out.parent.mkdir(parents=True, exist_ok=True)
    preview = Image.new('RGBA', (1240, 520), (255, 255, 255, 255))
    old = Image.open(ROOT / 'static' / 'dashboard' / 'img' / 'apwrs-logo.png').convert('RGBA')
    preview.alpha_composite(old.resize((590, 500), Image.LANCZOS), (10, 10))
    preview.alpha_composite(logo(590), (640, 10))
    preview.save(out)
    print('preview:', out)
