"""Draw the phone app's launcher icons and splash artwork from the website's
icon (scripts/make_pwa_icons.py): same sprout, leaves and water drop, drawn
larger for a phone and on a soft radial green, so web and app read as one.

    py -3.11 scripts/make_app_icons.py

Writes into mobile/:
  android  mipmap-*/ic_launcher.png             legacy icon (rounded tile)
           mipmap-*/ic_launcher_foreground.png   adaptive icon drawing (108 dp,
                                                 kept inside the 66 dp safe zone)
           mipmap-*/ic_launcher_background.png   radial green behind it
           mipmap-*/ic_launcher_monochrome.png   one-colour drawing (themed icons)
           mipmap-anydpi-v26/ic_launcher.xml
           drawable-*/splash_icon.png            sprout for the launch screen
  ios      AppIcon.appiconset/Icon-App-*.png     opaque squares (iOS rounds them)
           LaunchImage.imageset/LaunchImage*.png sprout for the launch screen
  flutter  assets/img/app_icon.png               the icon for in-app screens
"""
import math
import pathlib
import re
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from make_pwa_icons import DROP, GREEN, LEAF, SOIL, STEM, bar, drop, leaf  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
MOBILE = ROOT / 'mobile'
RES = MOBILE / 'android' / 'app' / 'src' / 'main' / 'res'
IOS = MOBILE / 'ios' / 'Runner' / 'Assets.xcassets'

DENSITIES = {'mdpi': 1, 'hdpi': 1.5, 'xhdpi': 2, 'xxhdpi': 3, 'xxxhdpi': 4}
CENTRE = (27, 67, 50)  # --primary-c, lighter green in the middle of the gradient
WHITE = (255, 255, 255, 255)

ADAPTIVE_XML = """<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@mipmap/ic_launcher_background"/>
    <foreground android:drawable="@mipmap/ic_launcher_foreground"/>
    <monochrome android:drawable="@mipmap/ic_launcher_monochrome"/>
</adaptive-icon>
"""


def sprout(size, scale=1.0, mono=None):
    """The website's sprout, leaves and drop on a transparent square, its
    drawing centred and `scale` times the size. `mono` paints it all one colour."""
    s = size * 4
    img = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    k = s * scale
    c = s / 2
    off = (s - k) / 2
    # The drawing spans y 0.11..0.81 of its box: shift it up so it sits centred.
    dy = -0.04 * k
    pick = (lambda col: mono) if mono else (lambda col: col)
    bar(d, [off + k * 0.30, off + k * 0.76 + dy, off + k * 0.70, off + k * 0.81 + dy], pick(SOIL))
    bar(d, [c - k * 0.024, off + k * 0.40 + dy, c + k * 0.024, off + k * 0.78 + dy], pick(STEM))
    leaf(d, c, off + k * 0.56 + dy, k * 0.30, k * 0.16, -35, pick(LEAF))
    leaf(d, c, off + k * 0.62 + dy, k * 0.26, k * 0.14, 215, pick(LEAF))
    drop(d, c + k * 0.21, off + k * 0.27 + dy, k * 0.068, pick(DROP))
    return img.resize((size, size), Image.LANCZOS)


def radial(size):
    """Brand green, lighter in the middle (like a lit leaf), dark at the edge."""
    img = Image.new('RGBA', (size, size))
    px = img.load()
    r_max = math.hypot(size / 2, size / 2)
    for y in range(size):
        for x in range(size):
            t = min(1.0, math.hypot(x - size / 2, y - size * 0.42) / r_max) ** 1.4
            px[x, y] = tuple(round(CENTRE[i] + (GREEN[i] - CENTRE[i]) * t) for i in range(3)) + (255,)
    return img


def tile(size, rounded=True, scale=0.82):
    """Gradient square (optionally rounded like the website's icon) with the sprout."""
    img = radial(size)
    img.alpha_composite(sprout(size, scale))
    if rounded:
        mask = Image.new('L', (size * 4, size * 4), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, size * 4 - 1, size * 4 - 1], radius=int(size * 4 * 0.22), fill=255)
        img.putalpha(mask.resize((size, size), Image.LANCZOS))
    return img


def android():
    for name, k in DENSITIES.items():
        folder = RES / f'mipmap-{name}'
        folder.mkdir(parents=True, exist_ok=True)
        tile(round(48 * k)).save(folder / 'ic_launcher.png')
        # 108 dp layers; launchers show the middle 72 dp and only promise the
        # central 66 dp circle, which the drawing at 0.66 stays inside.
        layer = round(108 * k)
        sprout(layer, 0.66).save(folder / 'ic_launcher_foreground.png')
        radial(layer).save(folder / 'ic_launcher_background.png')
        sprout(layer, 0.66, mono=WHITE).save(folder / 'ic_launcher_monochrome.png')
        splash = RES / f'drawable-{name}'
        splash.mkdir(exist_ok=True)
        sprout(round(160 * k), 0.9).save(splash / 'splash_icon.png')
    anydpi = RES / 'mipmap-anydpi-v26'
    anydpi.mkdir(exist_ok=True)
    (anydpi / 'ic_launcher.xml').write_text(ADAPTIVE_XML, encoding='utf-8')
    old = RES / 'values' / 'ic_launcher_background.xml'  # replaced by the gradient image
    if old.exists():
        old.unlink()


def ios():
    for path in sorted((IOS / 'AppIcon.appiconset').glob('Icon-App-*.png')):
        m = re.match(r'Icon-App-([\d.]+)x[\d.]+@(\d)x\.png', path.name)
        size = round(float(m.group(1)) * int(m.group(2)))
        tile(size, rounded=False).convert('RGB').save(path)  # App Store icons must be opaque
    launch = IOS / 'LaunchImage.imageset'
    for n, name in enumerate(['LaunchImage.png', 'LaunchImage@2x.png', 'LaunchImage@3x.png'], start=1):
        sprout(160 * n, 0.9).save(launch / name)


def flutter():
    (MOBILE / 'assets' / 'img').mkdir(parents=True, exist_ok=True)
    tile(512).save(MOBILE / 'assets' / 'img' / 'app_icon.png')


if __name__ == '__main__':
    android()
    ios()
    flutter()
    print('Wrote launcher icons and splash artwork under', MOBILE)
