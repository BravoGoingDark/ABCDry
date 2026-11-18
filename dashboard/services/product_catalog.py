"""Precise products for the farmer: fertilisers and crop protection.

Fertilisers: nutrient content, bag size, the farm-sized quantity of each
application in crop_management.MANAGEMENT, and an equivalent alternative
(same nutrient dose from another common product).

Crop protection: for each threat in crop_management.MANAGEMENT, the options
in integrated pest management order (cultural, traps, biological / mineral,
then chemical). Chemical options name the ACTIVE INGREDIENT (sold under many
brand names) with its resistance group (FRAC fungicides, IRAC insecticides,
HRAC herbicides), so the farmer can rotate groups. Doses are given where a
standard rate exists (per hectare or per 100 L of spray); otherwise "label
dose". Every dose stays INDICATIVE: the product must be registered in Tunisia
for that crop and its label (dose, protective equipment, days before harvest)
always wins. Sources: FAO fertiliser guides, common extension practice for
the Mediterranean, product-class label ranges.
"""
import math
import re

from django.utils.translation import gettext as _

# Texts below are English msgids, translated when a response is built
# (French and Arabic in locale/agronomy_pairs.py).


def _t(text):
    return _(text) if text else text

# ------------------------------------------------------------------ #
# Fertilisers
# ------------------------------------------------------------------ #

FERTILIZERS = {
    'dap': {'name': 'DAP 18-46-0', 'N': 18, 'P2O5': 46, 'K2O': 0, 'bag_kg': 50,
            'tip': 'Bury it in the soil at sowing (it does not move down by itself); keep large '
                   'doses out of direct contact with the seed.'},
    'an': {'name': 'Ammonium nitrate 33.5%', 'N': 33.5, 'P2O5': 0, 'K2O': 0, 'bag_kg': 50,
           'tip': 'Spread on moist soil, just before a light rain or a watering; split large doses.'},
    'urea': {'name': 'Urea 46%', 'N': 46, 'P2O5': 0, 'K2O': 0, 'bag_kg': 50,
             'tip': 'Loses nitrogen to the air if left on the surface: water it in or bury it within 2 days.'},
    'tsp': {'name': 'Triple superphosphate 45%', 'N': 0, 'P2O5': 45, 'K2O': 0, 'bag_kg': 50,
            'tip': 'Bury it before sowing or planting, near the future root zone.'},
    'npk': {'name': 'NPK 10-20-20', 'N': 10, 'P2O5': 20, 'K2O': 20, 'bag_kg': 50,
            'tip': 'Base dressing: spread and work into the soil before planting.'},
    'sop': {'name': 'Potassium sulphate 50%', 'N': 0, 'P2O5': 0, 'K2O': 50, 'bag_kg': 50,
            'tip': 'Better than potassium chloride for vegetables, potato, citrus and olive '
                   '(no chloride, adds sulphur).'},
    'can': {'name': 'Calcium nitrate 15.5%', 'N': 15.5, 'P2O5': 0, 'K2O': 0, 'bag_kg': 25,
            'tip': 'Soluble: through the drip line. Calcium prevents blossom-end rot. '
                   'Never mix with sulphates or phosphates in the same tank.'},
    'kno3': {'name': 'Potassium nitrate 13-0-46', 'N': 13, 'P2O5': 0, 'K2O': 46, 'bag_kg': 25,
             'tip': 'Soluble: through the drip line during fruit growth.'},
    'manure': {'name': 'Well-rotted manure', 'N': None, 'P2O5': None, 'K2O': None, 'bag_kg': None,
               'tip': 'Only well-composted manure (fresh manure burns roots and spreads weeds); bury it.'},
}

# Product text used in crop_management.MANAGEMENT -> catalogue keys.
PRODUCT_KEYS = {
    'DAP 18-46-0': ['dap'],
    'Ammonium nitrate 33.5%': ['an'],
    'Triple superphosphate 45%': ['tsp'],
    'NPK 10-20-20': ['npk'],
    'NPK 10-20-20 or DAP + potassium sulphate': ['npk'],
    'Potassium sulphate 50%': ['sop'],
    'Potassium sulphate 50% + manure': ['sop', 'manure'],
    'Calcium nitrate + potassium nitrate': ['can', 'kno3'],
    'Potassium nitrate / sulphate': ['kno3', 'sop'],
    'Ammonium nitrate or fertigation': ['an'],
    'Ammonium nitrate + potassium sulphate': ['an', 'sop'],
    'Fertigation N + K': ['kno3'],
    'Manure': ['manure'],
}

# Same nutrient dose from another product: (alternative, nutrient it replaces).
ALTERNATIVES = {'an': ('urea', 'N'), 'urea': ('an', 'N')}

_RATE_RE = re.compile(r'(\d+(?:\.\d+)?)\s*(?:-|–)\s*(\d+(?:\.\d+)?)\s*kg/ha|(\d+(?:\.\d+)?)\s*kg/ha')


def _rng(lo, hi, dec=0):
    """'200–300', '1.5–2', or a single value when both ends round the same."""
    def f(v):
        s = f'{v:,.{dec}f}' if dec else f'{round(v):,}'
        return s.rstrip('0').rstrip('.') if '.' in s else s
    return f(lo) if f(lo) == f(hi) else f'{f(lo)}–{f(hi)}'


def parse_rate_kg_ha(rate):
    """(low, high) kg/ha from texts such as '100-150 kg/ha (skip ...)'."""
    m = _RATE_RE.search(rate or '')
    if not m:
        return None
    if m.group(3):
        v = float(m.group(3))
        return v, v
    return float(m.group(1)), float(m.group(2))


def _content(f):
    parts = [f'{k} {f[k]:g}%' for k in ('N', 'P2O5', 'K2O') if f.get(k)]
    return ', '.join(parts)


def fertilizer_details(product, rate, area_ha=None):
    """Precise products and farm quantities for one fertiliser application."""
    keys = PRODUCT_KEYS.get(product, [])
    products = [{'key': k, 'name': _t(FERTILIZERS[k]['name']), 'content': _content(FERTILIZERS[k]),
                 'bag_kg': FERTILIZERS[k]['bag_kg'], 'tip': _t(FERTILIZERS[k]['tip'])} for k in keys]
    out = {'products': products, 'per_week': 'per week' in (rate or '')}
    per_ha = parse_rate_kg_ha(rate)
    if len(keys) != 1 or not per_ha or FERTILIZERS[keys[0]]['bag_kg'] is None:
        return out
    f = FERTILIZERS[keys[0]]
    lo, hi = per_ha
    out['supplies'] = {k: _('{v} kg/ha').format(v=_rng(lo * f[k] / 100, hi * f[k] / 100))
                       for k in ('N', 'P2O5', 'K2O') if f.get(k)}
    if area_ha:
        out['farm'] = {'area_ha': round(area_ha, 2), 'kg': _rng(lo * area_ha, hi * area_ha),
                       'bags': _rng(math.ceil(lo * area_ha / f['bag_kg']), math.ceil(hi * area_ha / f['bag_kg'])),
                       'bag_kg': f['bag_kg']}
    alt = ALTERNATIVES.get(keys[0])
    if alt:
        a, nutrient = FERTILIZERS[alt[0]], alt[1]
        k = f[nutrient] / a[nutrient]
        out['alternative'] = {'name': _t(a['name']), 'rate': _('{v} kg/ha').format(v=_rng(lo * k, hi * k)),
                              'farm_kg': _rng(lo * k * area_ha, hi * k * area_ha) if area_ha else None,
                              'tip': _t(a['tip'])}
    return out


# ------------------------------------------------------------------ #
# Crop protection
# ------------------------------------------------------------------ #

# Typical spray volume (L of water per ha) for per-100 L concentrations.
SPRAY_VOLUME_L_HA = {
    'wheat': 250, 'barley': 250, 'oats': 250, 'faba_bean': 300, 'lentil': 300, 'alfalfa': 300,
    'garlic': 500, 'potato': 500, 'tomato': 600, 'pepper': 600,
    'olive': 1000, 'citrus': 1500, 'date_palm': 1000,
}

KIND_ORDER = {'cultural': 0, 'trap': 1, 'biological': 2, 'mineral': 3, 'chemical': 4}


def _o(kind, name, rate='Label dose', group='', notes='', ha=None, hl=None):
    """One option. ha=(lo, hi, unit) per hectare; hl=(lo, hi, unit) per 100 L."""
    return {'kind': kind, 'name': name, 'group': group, 'rate': rate, 'notes': notes,
            'rate_ha': ha, 'rate_hl': hl}


TEBUCONAZOLE = _o('chemical', 'Tebuconazole 250 g/L (EW)', '1 L/ha (250 g active ingredient/ha)', 'FRAC 3',
                  'At the first symptoms on the upper leaves. Do not use the same group more than '
                  'twice a season.', ha=(1, 1, 'L'))
PROPICONAZOLE = _o('chemical', 'Propiconazole 250 g/L (EC)', '0.5 L/ha (125 g active ingredient/ha)', 'FRAC 3',
                   'Same group as tebuconazole: alternate with azoxystrobin, not with tebuconazole.',
                   ha=(0.5, 0.5, 'L'))
AZOXYSTROBIN = _o('chemical', 'Azoxystrobin 250 g/L (SC)', '0.8–1 L/ha', 'FRAC 11',
                  'Preventive (best at flag leaf on cereals). Max 2 sprays of this group per season; '
                  'mix or alternate with a triazole (FRAC 3).', ha=(0.8, 1, 'L'))
MANCOZEB = _o('chemical', 'Mancozeb 80% (WP)', '2–2.5 kg/ha', 'FRAC M03',
              'Contact, preventive: before rain, renew every 7–10 days in wet weather and after '
              '25–30 mm of rain. Check it is still registered for your crop.', ha=(2, 2.5, 'kg'))
METALAXYL_MZ = _o('chemical', 'Metalaxyl-M + mancozeb (WG)', '2.5 kg/ha', 'FRAC 4 + M03',
                  'Penetrating: when blight starts. Max 2–3 sprays a season (resistance), then back to '
                  'a contact fungicide.', ha=(2.5, 2.5, 'kg'))
CYMOXANIL_MZ = _o('chemical', 'Cymoxanil + mancozeb (WP)', 'Label dose', 'FRAC 27 + M03',
                  'Stops infections of the last 2–3 days: use right after a wet spell.')
COPPER_HYDROXIDE = _o('mineral', 'Copper hydroxide', 'Label dose', 'FRAC M01',
                      'Allowed in organic farming. Preventive only; washed off by heavy rain.')
COPPER_OXY = _o('mineral', 'Copper oxychloride 50% (WP)', '300–500 g per 100 L of water', 'FRAC M01',
                'Allowed in organic farming. Wet the whole canopy.', hl=(300, 500, 'g'))
SULPHUR = _o('mineral', 'Wettable sulphur 80%', '200–300 g per 100 L of water', 'FRAC M02',
             'Allowed in organic farming. Not above 30 °C (leaf burn) and not within 2 weeks of an '
             'oil spray.', hl=(200, 300, 'g'))
PENCONAZOLE = _o('chemical', 'Penconazole', 'Label dose', 'FRAC 3', 'When sulphur is not enough or too hot to use.')
BT = _o('biological', 'Bacillus thuringiensis kurstaki (Bt)', '0.5–1 kg/ha', 'IRAC 11A',
        'Kills young caterpillars only, harmless to bees and people; spray in the evening '
        '(sunlight breaks it down) and renew after 7 days.', ha=(0.5, 1, 'kg'))
SPINOSAD = _o('biological', 'Spinosad', 'Label dose', 'IRAC 5',
              'Natural origin. Spray in the evening (toxic to bees while wet); max 2–3 sprays a season.')
SPINOSAD_BAIT = _o('biological', 'Spinosad fruit-fly bait (ready bait, 0.24 g/L)',
                   'About 1 L of bait per ha, mixed with 4 L of water', 'IRAC 5',
                   'Spot-spray a few big drops on one side of every tree (or every other tree): the flies '
                   'come to eat it. Repeat every 7–10 days while the traps catch flies.', ha=(1, 1, 'L'))
SOAP = _o('biological', 'Insecticidal (potassium) soap', '1–2 L per 100 L of water', '',
          'Contact only: wet the colonies, under the leaves too. Spares most beneficial insects.',
          hl=(1, 2, 'L'))
PIRIMICARB = _o('chemical', 'Pirimicarb 50% (WG)', 'Label dose', 'IRAC 1A',
                'Selective: spares ladybirds, hoverflies and bees. Treat only when colonies spread.')
FLONICAMID = _o('chemical', 'Flonicamid 50% (WG)', 'Label dose', 'IRAC 29', 'Stops aphid feeding within hours.')
KAOLIN = _o('mineral', 'Kaolin clay', '3–5 kg per 100 L of water', '',
            'The white film repels the insect. Spray before the attack period and again after heavy '
            'rain. Allowed in organic farming.', hl=(3, 5, 'kg'))
FOSETYL = _o('chemical', 'Fosetyl-aluminium 80% (WG)', 'Label dose', 'FRAC P07',
             'Systemic, moves down to the roots: foliar spray in spring and autumn.')

CEREAL_WEEDS = [
    _o('chemical', 'Tribenuron-methyl 75% (WG) — broadleaf weeds', '15–25 g/ha', 'HRAC 2',
       'From 3 leaves to the end of tillering, on young growing weeds; no rain for 4 h.', ha=(15, 25, 'g')),
    _o('chemical', '2,4-D amine — broadleaf weeds', 'Label dose', 'HRAC 4',
       'End of tillering, before stem elongation. Drift damages vegetables, vines and trees: '
       'never in wind.'),
    _o('chemical', 'Clodinafop-propargyl — wild oats, ryegrass, phalaris', 'Label dose', 'HRAC 1',
       'Grass weeds at 2 leaves to tillering. Ryegrass resistance is common: rotate groups.'),
    _o('chemical', 'Mesosulfuron + iodosulfuron — grasses and broadleaf', 'Label dose', 'HRAC 2',
       'Wide spectrum on durum and bread wheat (not barley).'),
]
APHIDS = [SOAP, PIRIMICARB, FLONICAMID]
LATE_BLIGHT = [MANCOZEB, METALAXYL_MZ, CYMOXANIL_MZ, COPPER_HYDROXIDE]
FRUIT_FLY_TRAPS = _o('trap', 'Fruit-fly traps (food lure or pheromone)',
                     'Monitoring: 2–4 traps/ha. Mass trapping: about 50 traps/ha', '',
                     'Hang on the sunny side at head height before the attack period; treat when '
                     'catches rise.')

PROTECTION = {
    'wheat': {
        'Weeds (grasses and broadleaf)': CEREAL_WEEDS,
        'Septoria leaf blotch': [TEBUCONAZOLE, AZOXYSTROBIN, PROPICONAZOLE],
        'Yellow and brown rust': [TEBUCONAZOLE, PROPICONAZOLE, AZOXYSTROBIN],
    },
    'barley': {
        'Net blotch and scald': [PROPICONAZOLE, TEBUCONAZOLE, AZOXYSTROBIN],
        'Weeds': CEREAL_WEEDS[:3],
    },
    'oats': {'Crown rust': [PROPICONAZOLE, TEBUCONAZOLE]},
    'faba_bean': {
        'Broomrape (Orobanche)': [
            _o('cultural', 'Tolerant varieties, later sowing, long rotation', '', '',
               'Broomrape seeds live 10+ years in the soil: no faba bean, lentil or pea on infested '
               'land for several years.'),
            _o('chemical', 'Glyphosate at very low dose', '60–80 g active ingredient/ha, 2–3 sprays '
               '10–15 days apart from the start of flowering', 'HRAC 9',
               'ONLY on faba bean, only at this very low dose and with your CRDA advice: a normal dose '
               'kills the crop.'),
        ],
        'Chocolate spot (Botrytis)': [MANCOZEB, _o('chemical', 'Tebuconazole', 'Label dose', 'FRAC 3',
                                                   'From early flowering if wet weather persists.')],
        'Black bean aphid': APHIDS,
    },
    'lentil': {
        'Ascochyta blight and rust': [MANCOZEB, _o('chemical', 'Tebuconazole', 'Label dose', 'FRAC 3',
                                                   'At the first spots; renew after 2 weeks in wet weather.')],
        'Weeds': [_o('chemical', 'Pendimethalin — before emergence', 'Label dose', 'HRAC 3',
                     'Spray right after sowing on moist, fine soil; lentil competes poorly with weeds.')],
    },
    'garlic': {
        'Rust': [_o('chemical', 'Tebuconazole', 'Label dose', 'FRAC 3', 'At the first orange pustules.'),
                 AZOXYSTROBIN],
        'Thrips': [_o('trap', 'Blue sticky traps', '2–4 per ha to watch numbers', '', ''), SPINOSAD],
    },
    'potato': {
        'Late blight (mildiou)': LATE_BLIGHT,
        'Potato tuber moth': [
            _o('trap', 'Pheromone traps (tuber moth lure)', '2–4 traps/ha for monitoring', '', ''),
            _o('cultural', 'Earth up well and keep the soil from cracking', '', '',
               'Moths lay on exposed tubers: hill up, water to close cracks, harvest promptly and '
               'never leave tubers in the field overnight.'),
            BT,
            _o('chemical', 'Deltamethrin', 'Label dose', 'IRAC 3A', 'Only when traps catch many moths.'),
        ],
    },
    'tomato': {
        'Tomato leaf miner (Tuta absoluta)': [
            _o('trap', 'Pheromone water traps (Tuta lure)',
               'Monitoring: 2–4 traps/ha. Mass trapping: 20–40 traps/ha', '',
               'Start at transplanting; also put insect-proof nets on greenhouse openings.'),
            BT, SPINOSAD,
            _o('chemical', 'Chlorantraniliprole', 'Label dose', 'IRAC 28', 'Alternate groups between sprays.'),
            _o('chemical', 'Emamectin benzoate', 'Label dose', 'IRAC 6', 'Alternate groups between sprays.'),
        ],
        'Late blight': LATE_BLIGHT,
        'Powdery mildew': [SULPHUR, PENCONAZOLE],
        'Whitefly (virus vector)': [
            _o('trap', 'Yellow sticky traps', 'About 1 trap per 20–50 m² in greenhouses', '', ''),
            _o('biological', 'Beauveria bassiana (fungus)', 'Label dose', '', 'Needs humid conditions; spray in the evening.'),
            SOAP,
            _o('chemical', 'Pyriproxyfen', 'Label dose', 'IRAC 7C', 'Stops young stages; acts slowly.'),
            _o('chemical', 'Acetamiprid', 'Label dose', 'IRAC 4A', 'Toxic to bees: never during flowering visits.'),
        ],
    },
    'pepper': {
        'Aphids': APHIDS,
        'Powdery mildew': [SULPHUR, PENCONAZOLE],
        'Phytophthora root rot': [
            _o('cultural', 'Raised beds and drip irrigation', '', '',
               'Never let water stand at the stem; remove wilted plants with their soil.'),
            FOSETYL,
            _o('chemical', 'Metalaxyl-M through the drip line', 'Label dose', 'FRAC 4',
               'At planting and once later; max 2 uses a season.'),
        ],
    },
    'alfalfa': {
        'Alfalfa weevil': [
            _o('cultural', 'Cut early', '', '', 'Cutting when larvae damage the tips is the most effective control.'),
            _o('chemical', 'Lambda-cyhalothrin', 'Label dose', 'IRAC 3A',
               'Respect the label interval before cutting or grazing; never during flowering (bees).'),
        ],
        'Dodder (Cuscuta)': [
            _o('cultural', 'Dodder-free seed; cut, cover and burn patches', '', '',
               'Act before the dodder flowers and seeds.'),
        ],
    },
    'olive': {
        'Olive fruit fly (Bactrocera oleae)': [FRUIT_FLY_TRAPS, KAOLIN, SPINOSAD_BAIT],
        'Peacock spot (oeil de paon)': [COPPER_OXY, COPPER_HYDROXIDE],
        'Olive moth (Prays oleae)': [BT],
    },
    'citrus': {
        'Mediterranean fruit fly (Ceratitis)': [FRUIT_FLY_TRAPS, SPINOSAD_BAIT, KAOLIN],
        'Scale insects': [
            _o('biological', 'Keep the natural parasites (Aphytis)', '', '',
               'Avoid broad-spectrum insecticides that kill them.'),
            _o('mineral', 'Paraffinic (summer) oil', '1–1.5 L per 100 L of water', '',
               'At the crawler stage (late spring); wet the whole tree; not above 32 °C and not with '
               'sulphur.', hl=(1, 1.5, 'L')),
            _o('chemical', 'Pyriproxyfen', 'Label dose', 'IRAC 7C', 'On crawlers.'),
        ],
        'Gummosis (Phytophthora)': [
            _o('cultural', 'Keep water off the trunk', '', '', 'Drippers 50 cm away from the trunk; good drainage.'),
            FOSETYL,
            _o('mineral', 'Copper (Bordeaux) paste on the trunk base', '', 'FRAC M01',
               'Scrape the diseased bark first, then paint the wound.'),
        ],
    },
    'date_palm': {
        'Date moth (Ectomyelois)': [
            _o('cultural', 'Bag the bunches in fine net after fruit set', '', '',
               'Remove fallen and left-over dates: the moth survives in them.'),
            BT,
        ],
        'Red palm weevil (alert)': [
            _o('cultural', 'Report any suspect palm to the CRDA at once', '', '',
               'Holes with brown ooze, chewed fibres, a crown that leans: quarantine pest.'),
            _o('trap', 'Pheromone + food bait traps', 'About 1 trap per ha for monitoring', '', ''),
        ],
    },
}


def protection_options(crop_key, threat_name, area_ha=None):
    """Product options for one threat, with farm quantities where a rate exists."""
    vol = SPRAY_VOLUME_L_HA.get(crop_key, 400)
    out = []
    for o in sorted(PROTECTION.get(crop_key, {}).get(threat_name, []), key=lambda o: KIND_ORDER[o['kind']]):
        item = {'kind': o['kind'], 'group': o['group'], 'name': _t(o['name']), 'rate': _t(o['rate']),
                'notes': _t(o['notes'])}
        if o['rate_hl']:
            lo, hi, unit = o['rate_hl']
            item['per_ha'] = _('{v} {unit}/ha').format(
                v=_rng(lo * vol / 100, hi * vol / 100, 1 if hi * vol / 100 < 10 else 0), unit=_(unit))
            item['spray_l_ha'] = vol
        if area_ha:
            if o['rate_ha']:
                lo, hi, unit = o['rate_ha']
                item['farm'] = f"{_rng(lo * area_ha, hi * area_ha, 1 if hi * area_ha < 10 else 0)} {_(unit)}"
            elif o['rate_hl']:
                lo, hi, unit = o['rate_hl']
                f_lo, f_hi = lo * vol / 100 * area_ha, hi * vol / 100 * area_ha
                item['farm'] = f"{_rng(f_lo, f_hi, 1 if f_hi < 10 else 0)} {_(unit)}"
                item['farm_water_l'] = round(vol * area_ha)
        out.append(item)
    return out


def best_spray_day(forecast_days, today_iso=None):
    """First forecast day fit for spraying: dry, little wind, not hot."""
    for d in forecast_days[:7]:
        if today_iso and d.get('date', '') < today_iso:
            continue
        if ((d.get('precip_prob') or 0) < 30 and (d.get('wind') or 0) < 15
                and (d.get('tmax') or 0) < 30 and (d.get('precip') or 0) < 1):
            return d.get('date')
    return None
