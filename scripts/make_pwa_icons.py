"""Draw the farmer app icons (installable web app) in the brand colours.

    py -3.11 scripts/make_pwa_icons.py

Writes static/dashboard/pwa/: icon-192.png, icon-512.png (any purpose),
icon-maskable-512.png (Android adaptive icons crop to a circle or squircle:
the drawing stays inside the central safe zone), apple-touch-icon.png (iOS,
opaque) and favicon-32.png. Drawn at 4x and downsampled for smooth edges.
"""
import math
import pathlib

from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'static' / 'dashboard' / 'pwa'
GREEN = (1, 45, 29, 255)        # --primary
LEAF = (216, 243, 227, 255)     # --mint
STEM = (134, 239, 172, 255)
DROP = (105, 212, 244, 255)     # assistant accent
SOIL = (45, 106, 79, 255)       # --leaf


def leaf(draw, cx, cy, length, width, angle, fill):
    """A pointed leaf (two arcs) from (cx, cy) towards `angle` degrees."""
    a = math.radians(angle)
    pts = []
    for i in range(41):
        t = i / 40
        x = t * length
        y = math.sin(math.pi * t) * width / 2
        pts.append((x, y))
    pts += [(x, -y) for x, y in reversed(pts)]
    rot = [(cx + x * math.cos(a) - y * math.sin(a), cy + x * math.sin(a) + y * math.cos(a)) for x, y in pts]
    draw.polygon(rot, fill=fill)


def drop(draw, cx, cy, r, fill):
    """Water drop: circle with a pointed top."""
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)
    draw.polygon([(cx - r * 0.86, cy - r * 0.5), (cx, cy - r * 2.3), (cx + r * 0.86, cy - r * 0.5)], fill=fill)


def bar(draw, box, fill):
    """Rounded bar whose corner radius always fits the bar."""
    x0, y0, x1, y1 = box
    r = max(0, int(min(x1 - x0, y1 - y0) / 2) - 1)
    draw.rounded_rectangle(box, radius=r, fill=fill) if r else draw.rectangle(box, fill=fill)


def artwork(size, scale=1.0, background=True, rounded=True):
    s = size * 4
    img = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if background:
        if rounded:
            d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=GREEN)
        else:
            d.rectangle([0, 0, s, s], fill=GREEN)
    k = s * scale
    c = s / 2
    off = (s - k) / 2
    # soil line
    bar(d, [off + k * 0.20, off + k * 0.76, off + k * 0.80, off + k * 0.81], SOIL)
    # stem
    bar(d, [c - k * 0.022, off + k * 0.40, c + k * 0.022, off + k * 0.78], STEM)
    # leaves
    leaf(d, c, off + k * 0.56, k * 0.30, k * 0.16, -35, LEAF)
    leaf(d, c, off + k * 0.62, k * 0.26, k * 0.14, 215, LEAF)
    # water drop above the sprout
    drop(d, c + k * 0.21, off + k * 0.27, k * 0.068, DROP)
    return img.resize((size, size), Image.LANCZOS)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    artwork(192).save(OUT / 'icon-192.png')
    artwork(512).save(OUT / 'icon-512.png')
    # maskable: full-bleed background, drawing inside the 80% safe zone
    artwork(512, scale=0.78, rounded=False).save(OUT / 'icon-maskable-512.png')
    apple = Image.new('RGBA', (180, 180), GREEN)
    apple.alpha_composite(artwork(180, scale=0.9, rounded=False))
    apple.convert('RGB').save(OUT / 'apple-touch-icon.png')
    artwork(32).save(OUT / 'favicon-32.png')
    print('Wrote icons to', OUT)


if __name__ == '__main__':
    main()
