"""Draw the phone app's launcher icons with the same artwork as the website's
installable app (scripts/make_pwa_icons.py), so both carry one icon.

    py -3.11 scripts/make_app_icons.py

Writes into mobile/:
  android  mipmap-*/ic_launcher.png            legacy icon (rounded tile)
           mipmap-*/ic_launcher_foreground.png  adaptive icon drawing (108 dp,
                                                inside the 66 dp safe zone)
           mipmap-anydpi-v26/ic_launcher.xml    adaptive icon on the brand green
           values/ic_launcher_background.xml
  ios      AppIcon.appiconset/Icon-App-*.png    opaque squares (iOS rounds them)
"""
import pathlib
import re
import sys

from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from make_pwa_icons import GREEN, artwork  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
RES = ROOT / 'mobile' / 'android' / 'app' / 'src' / 'main' / 'res'
IOS = ROOT / 'mobile' / 'ios' / 'Runner' / 'Assets.xcassets' / 'AppIcon.appiconset'

DENSITIES = {'mdpi': 1, 'hdpi': 1.5, 'xhdpi': 2, 'xxhdpi': 3, 'xxxhdpi': 4}

ADAPTIVE_XML = """<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@color/ic_launcher_background"/>
    <foreground android:drawable="@mipmap/ic_launcher_foreground"/>
</adaptive-icon>
"""

BACKGROUND_XML = """<?xml version="1.0" encoding="utf-8"?>
<resources>
    <color name="ic_launcher_background">#012D1D</color>
</resources>
"""


def android():
    for name, k in DENSITIES.items():
        folder = RES / f'mipmap-{name}'
        folder.mkdir(parents=True, exist_ok=True)
        artwork(round(48 * k)).save(folder / 'ic_launcher.png')
        # The launcher masks the 108 dp layer to a circle or squircle and only
        # guarantees the central 66 dp: keep the drawing inside it.
        artwork(round(108 * k), scale=0.6, background=False).save(folder / 'ic_launcher_foreground.png')
    anydpi = RES / 'mipmap-anydpi-v26'
    anydpi.mkdir(exist_ok=True)
    (anydpi / 'ic_launcher.xml').write_text(ADAPTIVE_XML, encoding='utf-8')
    (RES / 'values' / 'ic_launcher_background.xml').write_text(BACKGROUND_XML, encoding='utf-8')


def ios():
    for path in sorted(IOS.glob('Icon-App-*.png')):
        m = re.match(r'Icon-App-([\d.]+)x[\d.]+@(\d)x\.png', path.name)
        size = round(float(m.group(1)) * int(m.group(2)))
        icon = Image.new('RGBA', (size, size), GREEN)
        icon.alpha_composite(artwork(size, scale=0.9, rounded=False))
        icon.convert('RGB').save(path)  # App Store icons must be opaque


if __name__ == '__main__':
    android()
    ios()
    print('Wrote launcher icons to', RES, 'and', IOS)
