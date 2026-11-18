"""Build locale/ar/LC_MESSAGES/django.mo from locale/ar_pairs.py (no system gettext).

Run: python locale/build_ar_mo.py
"""
from __future__ import annotations

import pathlib
import sys

import polib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from agronomy_pairs import AGRO_PAIRS  # noqa: E402
from assistant_pairs import ASSISTANT_PAIRS  # noqa: E402
from ar_pairs import AR_PAIRS  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
PO_PATH = ROOT / "locale" / "ar" / "LC_MESSAGES" / "django.po"
MO_PATH = ROOT / "locale" / "ar" / "LC_MESSAGES" / "django.mo"


def main() -> None:
    PO_PATH.parent.mkdir(parents=True, exist_ok=True)
    po = polib.POFile()
    po.metadata = {
        "Project-Id-Version": "APWRS",
        "Language": "ar",
        "MIME-Version": "1.0",
        "Content-Type": "text/plain; charset=UTF-8",
        "Content-Transfer-Encoding": "8bit",
        "Plural-Forms": "nplurals=6; plural=n==0 ? 0 : n==1 ? 1 : n==2 ? 2 : "
                        "n%100>=3 && n%100<=10 ? 3 : n%100>=11 ? 4 : 5;",
    }
    seen = set()
    pairs = AR_PAIRS + [(en, ar) for en, _, ar in AGRO_PAIRS] + [(en, ar) for en, _, ar in ASSISTANT_PAIRS]
    # {% trans %} looks a text containing "%" up with the "%" doubled, while
    # gettext() in Python uses it as is: register both spellings.
    pairs += [(m.replace('%', '%%'), s.replace('%', '%%')) for m, s in pairs if '%' in m and '%%' not in m]
    for msgid, msgstr in pairs:
        if msgid in seen:
            continue
        seen.add(msgid)
        po.append(polib.POEntry(msgid=msgid, msgstr=msgstr))
    po.save(str(PO_PATH))
    po.save_as_mofile(str(MO_PATH))
    print("Wrote", PO_PATH, "and", MO_PATH, f"({len(seen)} strings)")


if __name__ == "__main__":
    main()
