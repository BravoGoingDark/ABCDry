"""Crop management guidance for farmers: calendar, fertilisation, protection.

Static, reviewable agronomy for the crops in crop_suitability.CROPS. All
rates are INDICATIVE totals for Mediterranean (northern Tunisia) conditions,
taken from common extension practice and FAO fertiliser guides; the real
dose must come from a soil test and the local CRDA / extension office.

Plant protection follows integrated pest management (IPM): monitoring and
cultural measures first, then product *types* only. No pesticide doses are
given here on purpose: the farmer must use a product registered in Tunisia
for that crop and follow its label (dose, protective equipment, pre-harvest
interval). weather_alerts() links each problem to the 16-day forecast.
"""
import datetime as dt

from .crop_suitability import CROPS

PROTECTION_NOTICE = (
    'Use only products registered in Tunisia for this crop, at the label dose, '
    'with protective equipment, and respect the pre-harvest interval. Prefer the '
    'prevention and biological options first and confirm with your CRDA '
    'extension office before treating.')

FERTILIZER_NOTICE = (
    'Indicative rates for an average soil. A soil analysis (every 3-4 years) '
    'and your CRDA extension office should set the final dose. Do not apply '
    'nitrogen just before heavy rain (it is washed out) or on dry soil without '
    'irrigation (it is not taken up).')

# offset_days: days after sowing/planting (annual crops)
# month: calendar month (perennial crops)
MANAGEMENT = {
    'wheat': {
        'fertilizer': {
            'totals': {'N': (80, 120), 'P2O5': (45, 70), 'K2O': (0, 50)},
            'note': 'K is rarely needed on the clay soils of the north.',
            'schedule': [
                {'offset_days': 0, 'stage': 'Sowing (incorporated)', 'product': 'DAP 18-46-0',
                 'rate': '100-150 kg/ha'},
                {'offset_days': 50, 'stage': 'Start of tillering', 'product': 'Ammonium nitrate 33.5%',
                 'rate': '100-150 kg/ha'},
                {'offset_days': 95, 'stage': 'Stem elongation', 'product': 'Ammonium nitrate 33.5%',
                 'rate': '100 kg/ha (skip in a very dry year)'},
            ],
        },
        'protection': [
            {'name': 'Weeds (grasses and broadleaf)', 'type': 'weeds', 'months': [12, 1, 2],
             'watch': 'Weed cover between the 3-leaf stage and tillering.',
             'prevent': 'Clean seed, rotation with legumes, stale seedbed before sowing.',
             'control': 'Selective post-emergence herbicide registered for durum wheat, '
                        'applied at 3 leaves - full tillering.'},
            {'name': 'Septoria leaf blotch', 'type': 'disease', 'months': [2, 3, 4],
             'trigger': 'wet_mild',
             'watch': 'Brown blotches with black dots on the lower leaves climbing upward after rain.',
             'prevent': 'Tolerant varieties, rotation, avoid very early sowing and excess nitrogen.',
             'control': 'Triazole or strobilurin fungicide when symptoms reach the upper '
                        'leaves, at flag-leaf stage.'},
            {'name': 'Yellow and brown rust', 'type': 'disease', 'months': [3, 4, 5],
             'trigger': 'warm_humid',
             'watch': 'Yellow stripes or orange pustules that rub off on the fingers.',
             'prevent': 'Resistant varieties.',
             'control': 'Triazole fungicide at the first pustules on the upper leaves.'},
        ],
    },
    'barley': {
        'fertilizer': {
            'totals': {'N': (50, 80), 'P2O5': (40, 60), 'K2O': (0, 40)},
            'note': 'Too much nitrogen causes lodging.',
            'schedule': [
                {'offset_days': 0, 'stage': 'Sowing', 'product': 'DAP 18-46-0', 'rate': '100 kg/ha'},
                {'offset_days': 50, 'stage': 'Tillering', 'product': 'Ammonium nitrate 33.5%',
                 'rate': '100 kg/ha'},
            ],
        },
        'protection': [
            {'name': 'Net blotch and scald', 'type': 'disease', 'months': [2, 3, 4],
             'trigger': 'wet_mild',
             'watch': 'Net-like brown stripes or pale oval blotches with a dark edge.',
             'prevent': 'Rotation, certified seed, bury stubble.',
             'control': 'Triazole fungicide if the top two leaves are attacked.'},
            {'name': 'Weeds', 'type': 'weeds', 'months': [12, 1],
             'watch': 'Weed cover at 3 leaves - tillering.',
             'prevent': 'Rotation, clean seed.',
             'control': 'Selective herbicide registered for barley.'},
        ],
    },
    'oats': {
        'fertilizer': {
            'totals': {'N': (60, 80), 'P2O5': (40, 50), 'K2O': (0, 40)},
            'note': 'Forage oats: a second N dose after the first cut if grazed or cut twice.',
            'schedule': [
                {'offset_days': 0, 'stage': 'Sowing', 'product': 'DAP 18-46-0', 'rate': '100 kg/ha'},
                {'offset_days': 45, 'stage': 'Tillering', 'product': 'Ammonium nitrate 33.5%',
                 'rate': '100 kg/ha'},
            ],
        },
        'protection': [
            {'name': 'Crown rust', 'type': 'disease', 'months': [3, 4], 'trigger': 'warm_humid',
             'watch': 'Orange pustules on the leaves.',
             'prevent': 'Tolerant varieties; cut forage early if heavily attacked.',
             'control': 'Rarely economic on forage oats; cut early instead.'},
        ],
    },
    'faba_bean': {
        'fertilizer': {
            'totals': {'N': (0, 20), 'P2O5': (40, 60), 'K2O': (0, 50)},
            'note': 'A legume: it fixes its own nitrogen. Inoculate seed with Rhizobium '
                    'if beans were not grown on the field recently.',
            'schedule': [
                {'offset_days': 0, 'stage': 'Sowing', 'product': 'Triple superphosphate 45%',
                 'rate': '100-130 kg/ha'},
            ],
        },
        'protection': [
            {'name': 'Broomrape (Orobanche)', 'type': 'weeds', 'months': [2, 3, 4],
             'watch': 'Pale flowering stems emerging at the foot of the plants.',
             'prevent': 'Long rotation (4+ years), tolerant varieties, slightly later sowing, '
                        'pull and burn the stems before they seed.',
             'control': 'No reliable curative option; prevention is essential.'},
            {'name': 'Chocolate spot (Botrytis)', 'type': 'disease', 'months': [1, 2, 3],
             'trigger': 'wet_mild',
             'watch': 'Small red-brown spots on leaves after humid days.',
             'prevent': 'Lower seed density, good drainage.',
             'control': 'Fungicide registered for faba bean at the first spreading spots.'},
            {'name': 'Black bean aphid', 'type': 'pest', 'months': [3, 4], 'trigger': 'warm',
             'watch': 'Black colonies on the shoot tips.',
             'prevent': 'Ladybirds usually control it; pinch infested tips.',
             'control': 'Only if colonies cover many plants; never spray during flowering '
                        '(bees) - spray in the evening if needed.'},
        ],
    },
    'lentil': {
        'fertilizer': {
            'totals': {'N': (0, 20), 'P2O5': (40, 50), 'K2O': (0, 40)},
            'note': 'A legume: no nitrogen top-dressing needed.',
            'schedule': [
                {'offset_days': 0, 'stage': 'Sowing', 'product': 'Triple superphosphate 45%',
                 'rate': '90-110 kg/ha'},
            ],
        },
        'protection': [
            {'name': 'Ascochyta blight and rust', 'type': 'disease', 'months': [2, 3, 4],
             'trigger': 'wet_mild',
             'watch': 'Brown lesions on leaves and pods; rust pustules on stems.',
             'prevent': 'Healthy treated seed, rotation, tolerant varieties.',
             'control': 'Registered fungicide at first symptoms in a wet spring.'},
            {'name': 'Weeds', 'type': 'weeds', 'months': [12, 1, 2],
             'watch': 'Lentil competes poorly in the first 6 weeks.',
             'prevent': 'Clean seedbed, row sowing to allow hoeing.',
             'control': 'Hoeing; herbicide registered for lentil.'},
        ],
    },
    'garlic': {
        'fertilizer': {
            'totals': {'N': (100, 150), 'P2O5': (60, 80), 'K2O': (100, 150)},
            'note': 'Well-rotted manure (20 t/ha) before planting improves bulb size.',
            'schedule': [
                {'offset_days': 0, 'stage': 'Planting', 'product': 'NPK 10-20-20 or DAP + potassium sulphate',
                 'rate': '300-400 kg/ha'},
                {'offset_days': 60, 'stage': 'Leaf growth', 'product': 'Ammonium nitrate 33.5%',
                 'rate': '100-150 kg/ha'},
                {'offset_days': 100, 'stage': 'Start of bulbing', 'product': 'Potassium sulphate 50%',
                 'rate': '100 kg/ha (stop N now)'},
            ],
        },
        'protection': [
            {'name': 'Rust', 'type': 'disease', 'months': [2, 3, 4], 'trigger': 'warm_humid',
             'watch': 'Orange pustules on leaves.',
             'prevent': 'Healthy cloves, avoid dense planting and excess N.',
             'control': 'Registered fungicide at first pustules.'},
            {'name': 'Thrips', 'type': 'pest', 'months': [3, 4, 5], 'trigger': 'hot_dry',
             'watch': 'Silvery streaks on the leaves.',
             'prevent': 'Blue sticky traps, irrigate to avoid stress.',
             'control': 'Registered insecticide only if heavily infested.'},
        ],
    },
    'potato': {
        'fertilizer': {
            'totals': {'N': (150, 200), 'P2O5': (100, 150), 'K2O': (200, 250)},
            'note': 'Manure 30 t/ha before planting is recommended. Potassium improves '
                    'tuber quality.',
            'schedule': [
                {'offset_days': 0, 'stage': 'Planting', 'product': 'NPK 10-20-20',
                 'rate': '500-600 kg/ha'},
                {'offset_days': 35, 'stage': 'Earthing up', 'product': 'Ammonium nitrate 33.5%',
                 'rate': '150-200 kg/ha'},
                {'offset_days': 55, 'stage': 'Tuber initiation', 'product': 'Potassium sulphate 50%',
                 'rate': '150 kg/ha'},
            ],
        },
        'protection': [
            {'name': 'Late blight (mildiou)', 'type': 'disease', 'months': [2, 3, 4, 5, 10, 11],
             'trigger': 'wet_mild',
             'watch': 'Dark wet patches with white mould under the leaf after humid nights.',
             'prevent': 'Healthy seed, earthing up, destroy volunteer plants and culls.',
             'control': 'Preventive contact fungicide (e.g. copper or mancozeb-type) '
                        'before humid spells; repeat according to the label.'},
            {'name': 'Potato tuber moth', 'type': 'pest', 'months': [4, 5, 6, 9, 10], 'trigger': 'hot_dry',
             'watch': 'Galleries in leaves and tubers; pheromone trap catches.',
             'prevent': 'Good earthing up, irrigate to avoid soil cracks, harvest promptly, '
                        'never leave tubers exposed in the field.',
             'control': 'Bacillus thuringiensis or registered insecticide if catches rise.'},
        ],
    },
    'tomato': {
        'fertilizer': {
            'totals': {'N': (150, 200), 'P2O5': (80, 120), 'K2O': (200, 300)},
            'note': 'Best applied by fertigation with drip irrigation, weekly. Manure '
                    '30 t/ha before transplanting.',
            'schedule': [
                {'offset_days': 0, 'stage': 'Before transplanting', 'product': 'NPK 10-20-20',
                 'rate': '300 kg/ha'},
                {'offset_days': 30, 'stage': 'Flowering start (weekly fertigation)',
                 'product': 'Calcium nitrate + potassium nitrate', 'rate': '10-15 kg/ha per week'},
                {'offset_days': 70, 'stage': 'Fruit enlargement', 'product': 'Potassium nitrate / sulphate',
                 'rate': '15-20 kg/ha per week'},
            ],
        },
        'protection': [
            {'name': 'Tomato leaf miner (Tuta absoluta)', 'type': 'pest',
             'months': [3, 4, 5, 6, 7, 8, 9, 10], 'trigger': 'warm',
             'watch': 'Pheromone traps (weekly counts); mines in leaves and holes in fruit.',
             'prevent': 'Insect-proof nets, mass trapping, remove infested leaves and crop residues.',
             'control': 'Bacillus thuringiensis or spinosad-type products, alternating modes '
                        'of action.'},
            {'name': 'Late blight', 'type': 'disease', 'months': [3, 4, 5, 10, 11],
             'trigger': 'wet_mild',
             'watch': 'Brown greasy patches on leaves and fruit after humid nights.',
             'prevent': 'Drip rather than sprinkler irrigation, airy spacing.',
             'control': 'Preventive copper-type fungicide before humid spells.'},
            {'name': 'Powdery mildew', 'type': 'disease', 'months': [5, 6, 7, 8, 9], 'trigger': 'hot_dry',
             'watch': 'Yellow patches on top of leaves with white powder underneath.',
             'prevent': 'Avoid water stress.',
             'control': 'Sulphur (not above 30 C) or registered fungicide.'},
            {'name': 'Whitefly (virus vector)', 'type': 'pest', 'months': [6, 7, 8, 9, 10], 'trigger': 'warm',
             'watch': 'Yellow sticky traps; small white insects under the leaves.',
             'prevent': 'Nets, virus-tolerant varieties, remove weeds around the field.',
             'control': 'Registered insecticide only when traps rise sharply.'},
        ],
    },
    'pepper': {
        'fertilizer': {
            'totals': {'N': (120, 180), 'P2O5': (60, 100), 'K2O': (150, 250)},
            'note': 'Fertigation with drip is best. Manure 25 t/ha before planting.',
            'schedule': [
                {'offset_days': 0, 'stage': 'Before transplanting', 'product': 'NPK 10-20-20',
                 'rate': '300 kg/ha'},
                {'offset_days': 30, 'stage': 'Flowering (weekly fertigation)',
                 'product': 'Calcium nitrate + potassium nitrate', 'rate': '10 kg/ha per week'},
            ],
        },
        'protection': [
            {'name': 'Aphids', 'type': 'pest', 'months': [4, 5, 6], 'trigger': 'warm',
             'watch': 'Colonies under young leaves.',
             'prevent': 'Encourage natural enemies; avoid excess nitrogen.',
             'control': 'Insecticidal soap or registered product if colonies spread.'},
            {'name': 'Powdery mildew', 'type': 'disease', 'months': [6, 7, 8, 9], 'trigger': 'hot_dry',
             'watch': 'Pale patches on top, white felt under the leaves.',
             'prevent': 'Regular irrigation.',
             'control': 'Sulphur (not above 30 C) or registered fungicide.'},
            {'name': 'Phytophthora root rot', 'type': 'disease', 'months': [5, 6, 7, 8],
             'watch': 'Sudden wilting of plants in wet spots.',
             'prevent': 'Raised beds, drip irrigation, never waterlog.',
             'control': 'Remove dying plants; rotation away from solanaceous crops.'},
        ],
    },
    'alfalfa': {
        'fertilizer': {
            'totals': {'N': (0, 20), 'P2O5': (60, 100), 'K2O': (100, 150)},
            'note': 'A legume: nitrogen only as a small starter at establishment. P and K '
                    'every year keep the stand productive.',
            'schedule': [
                {'month': 10, 'stage': 'Autumn (each year)', 'product': 'Triple superphosphate 45%',
                 'rate': '150-200 kg/ha'},
                {'month': 2, 'stage': 'End of winter (each year)', 'product': 'Potassium sulphate 50%',
                 'rate': '200 kg/ha'},
            ],
        },
        'protection': [
            {'name': 'Alfalfa weevil', 'type': 'pest', 'months': [3, 4], 'trigger': 'warm',
             'watch': 'Leaves eaten into lace at the shoot tips in spring.',
             'prevent': 'An early first cut usually controls it.',
             'control': 'Registered insecticide only if damage is heavy and cutting is not possible.'},
            {'name': 'Dodder (Cuscuta)', 'type': 'weeds', 'months': [4, 5, 6],
             'watch': 'Orange thread-like stems wrapping the plants.',
             'prevent': 'Certified dodder-free seed.',
             'control': 'Cut and burn patches early, before it seeds.'},
        ],
    },
    'olive': {
        'fertilizer': {
            'totals': {'N': (40, 100), 'P2O5': (20, 40), 'K2O': (60, 120)},
            'note': 'Rainfed groves: about 0.5-1 kg N per tree per year; irrigated groves '
                    'the higher values. Manure every 2-3 years.',
            'schedule': [
                {'month': 2, 'stage': 'End of winter (before bud burst)', 'product': 'Ammonium nitrate 33.5%',
                 'rate': '1.5-3 kg per tree (half the N)'},
                {'month': 4, 'stage': 'Before flowering', 'product': 'Ammonium nitrate 33.5%',
                 'rate': '1.5 kg per tree (rest of the N; skip in a dry spring without irrigation)'},
                {'month': 11, 'stage': 'After harvest', 'product': 'Potassium sulphate 50% + manure',
                 'rate': '1-2 kg per tree + 20-30 kg manure'},
            ],
        },
        'protection': [
            {'name': 'Olive fruit fly (Bactrocera oleae)', 'type': 'pest',
             'months': [7, 8, 9, 10], 'trigger': 'warm',
             'watch': 'Yellow sticky or McPhail traps from July; stings on the fruit.',
             'prevent': 'Mass trapping, early harvest, collect fallen fruit.',
             'control': 'Bait (attract-and-kill) sprays on part of the canopy when catches '
                        'and stings rise; kaolin clay as a barrier.'},
            {'name': 'Peacock spot (oeil de paon)', 'type': 'disease', 'months': [10, 11, 12, 1, 2, 3],
             'trigger': 'wet_mild',
             'watch': 'Dark round spots with a yellow halo on leaves; leaf drop.',
             'prevent': 'Pruning to open the canopy.',
             'control': 'Copper fungicide after harvest and again in late winter before the rains.'},
            {'name': 'Olive moth (Prays oleae)', 'type': 'pest', 'months': [4, 5], 'trigger': 'warm',
             'watch': 'Larvae in the flower clusters; pheromone traps.',
             'prevent': 'Natural enemies; traps for monitoring.',
             'control': 'Bacillus thuringiensis at the start of flowering if traps are high.'},
        ],
    },
    'citrus': {
        'fertilizer': {
            'totals': {'N': (150, 200), 'P2O5': (40, 60), 'K2O': (100, 150)},
            'note': 'Split nitrogen over the season; on calcareous soils watch for iron '
                    'chlorosis (yellow leaves with green veins).',
            'schedule': [
                {'month': 2, 'stage': 'Before flowering', 'product': 'Ammonium nitrate 33.5%',
                 'rate': '40% of the N'},
                {'month': 5, 'stage': 'Fruit set', 'product': 'Ammonium nitrate or fertigation',
                 'rate': '35% of the N + potassium'},
                {'month': 7, 'stage': 'Fruit growth', 'product': 'Fertigation N + K',
                 'rate': '25% of the N'},
            ],
        },
        'protection': [
            {'name': 'Mediterranean fruit fly (Ceratitis)', 'type': 'pest',
             'months': [6, 7, 8, 9, 10, 11], 'trigger': 'warm',
             'watch': 'Traps; stings and soft spots on ripening fruit.',
             'prevent': 'Mass trapping, collect and destroy fallen fruit.',
             'control': 'Bait sprays on part of the canopy when catches rise.'},
            {'name': 'Scale insects', 'type': 'pest', 'months': [5, 6, 7],
             'watch': 'Scales on twigs and leaves, sooty mould.',
             'prevent': 'Pruning for air flow, protect natural enemies.',
             'control': 'Mineral (summer) oil at crawler stage, not above 32 C.'},
            {'name': 'Gummosis (Phytophthora)', 'type': 'disease', 'months': [10, 11, 12, 1, 2, 3],
             'trigger': 'wet_mild',
             'watch': 'Gum oozing from cracks at the base of the trunk.',
             'prevent': 'Keep water away from the trunk, good drainage, tolerant rootstock.',
             'control': 'Scrape the lesion and paint with a copper paste.'},
        ],
    },
    'date_palm': {
        'fertilizer': {
            'totals': {'N': (100, 200), 'P2O5': (50, 100), 'K2O': (100, 200)},
            'note': 'About 1-1.5 kg N per palm per year plus 50 kg manure per palm in winter.',
            'schedule': [
                {'month': 1, 'stage': 'Winter', 'product': 'Manure', 'rate': '50 kg per palm'},
                {'month': 3, 'stage': 'Before pollination', 'product': 'Ammonium nitrate 33.5%',
                 'rate': '1.5-2 kg per palm'},
                {'month': 6, 'stage': 'Fruit growth', 'product': 'Ammonium nitrate + potassium sulphate',
                 'rate': '1.5 kg + 1 kg per palm'},
            ],
        },
        'protection': [
            {'name': 'Date moth (Ectomyelois)', 'type': 'pest', 'months': [8, 9, 10], 'trigger': 'warm',
             'watch': 'Larvae in ripening dates.',
             'prevent': 'Bag the bunches with nets, collect fallen dates, clean stores.',
             'control': 'Bacillus thuringiensis on bunches if needed.'},
            {'name': 'Red palm weevil (alert)', 'type': 'pest', 'months': list(range(1, 13)),
             'watch': 'Holes with brown ooze in the trunk, wilting central leaves.',
             'prevent': 'Use certified offshoots only.',
             'control': 'Report any suspicion to the CRDA immediately (quarantine pest).'},
        ],
    },
}


# ------------------------------------------------------------------ #
# Calendar
# ------------------------------------------------------------------ #

def default_sowing_date(crop_key, today=None):
    """Next sowing date (15th of the next planting month, today included)."""
    today = today or dt.date.today()
    months = CROPS[crop_key]['planting_months']
    for k in range(13):
        y, m = divmod(today.month - 1 + k, 12)
        candidate = dt.date(today.year + y, m + 1, 15)
        if m + 1 in months and candidate >= today - dt.timedelta(days=14):
            return candidate
    return dt.date(today.year, months[0], 15)


def crop_calendar(crop_key, sowing_date=None, today=None):
    """Dated timeline: growth stages + fertiliser applications + protection
    watch windows for the next 12 months."""
    crop = CROPS[crop_key]
    mgmt = MANAGEMENT.get(crop_key, {})
    today = today or dt.date.today()
    events = []

    if crop['perennial']:
        sowing_date = None
        for item in mgmt.get('fertilizer', {}).get('schedule', []):
            events.append({'date': _next_month_date(item['month'], today), 'kind': 'fertilizer',
                           'title': item['stage'], 'detail': f"{item['product']}: {item['rate']}"})
    else:
        sowing_date = sowing_date or default_sowing_date(crop_key, today)
        l_ini, l_dev, l_mid, l_late = crop['stages']
        marks = [(0, 'Sowing / planting'), (l_ini, 'Establishment complete'),
                 (l_ini + l_dev, 'Full canopy - peak water need'),
                 (l_ini + l_dev + l_mid, 'Maturation (reduce irrigation)'),
                 (l_ini + l_dev + l_mid + l_late, 'Expected harvest')]
        for offset, title in marks:
            events.append({'date': sowing_date + dt.timedelta(days=offset), 'kind': 'stage',
                           'title': title, 'detail': ''})
        for item in mgmt.get('fertilizer', {}).get('schedule', []):
            events.append({'date': sowing_date + dt.timedelta(days=item['offset_days']),
                           'kind': 'fertilizer', 'title': item['stage'],
                           'detail': f"{item['product']}: {item['rate']}"})

    for threat in mgmt.get('protection', []):
        if len(threat['months']) == 12:
            continue
        events.append({'date': _next_month_date(threat['months'][0], today, day=1),
                       'kind': 'protection', 'title': f"Start watching: {threat['name']}",
                       'detail': threat['watch']})

    events.sort(key=lambda e: e['date'])
    return {'sowing_date': sowing_date, 'events': [
        {**e, 'date': e['date'].isoformat()} for e in events]}


def _next_month_date(month, today, day=15):
    candidate = dt.date(today.year, month, day)
    if candidate < today.replace(day=1):
        candidate = dt.date(today.year + 1, month, day)
    return candidate


# ------------------------------------------------------------------ #
# Weather-linked alerts
# ------------------------------------------------------------------ #

def _weather_flags(days):
    """Which disease/pest weather patterns occur in the forecast days."""
    def ok(d, k):
        return d.get(k) is not None

    wet_mild = sum(1 for d in days if ok(d, 'precip') and ok(d, 'tmean')
                   and d['precip'] >= 1 and 10 <= d['tmean'] <= 25)
    warm_humid = sum(1 for d in days if ok(d, 'tmean') and ok(d, 'humidity')
                     and 15 <= d['tmean'] <= 30 and d['humidity'] >= 75)
    hot_dry = sum(1 for d in days if ok(d, 'tmax') and d['tmax'] >= 30
                  and (d.get('precip') or 0) < 1)
    warm = sum(1 for d in days if ok(d, 'tmean') and d['tmean'] >= 18)
    return {'wet_mild': wet_mild >= 2, 'warm_humid': warm_humid >= 3,
            'hot_dry': hot_dry >= 3, 'warm': warm >= 4}


def weather_alerts(days, crop_key=None, today=None):
    """Field alerts from the forecast days (Open-Meteo rows from
    services.weather_forecast): frost, heat, heavy rain, spray windows,
    and crop-specific pest/disease risk."""
    today = today or dt.date.today()
    alerts = []
    week = days[:7]

    frost = [d for d in week if d.get('tmin') is not None and d['tmin'] <= 2]
    if frost:
        alerts.append({'level': 'danger', 'icon': 'ac_unit', 'title': 'Frost risk',
                       'text': f"Minimum down to {min(d['tmin'] for d in frost)} C on "
                               f"{', '.join(d['label'] for d in frost)}. Protect seedlings and "
                               'young trees; irrigate the day before to store heat in the soil.'})
    heat = [d for d in week if d.get('tmax') is not None and d['tmax'] >= 35]
    if heat:
        alerts.append({'level': 'warning', 'icon': 'device_thermostat', 'title': 'Heat stress',
                       'text': f"Up to {max(d['tmax'] for d in heat)} C on "
                               f"{', '.join(d['label'] for d in heat)}. Irrigate early morning or "
                               'evening; avoid spraying and fertilising during the heat.'})
    heavy = [d for d in week if (d.get('precip') or 0) >= 20]
    if heavy:
        alerts.append({'level': 'warning', 'icon': 'thunderstorm', 'title': 'Heavy rain',
                       'text': f"{', '.join(d['label'] for d in heavy)}: 20 mm or more. "
                               'Postpone nitrogen and spraying; check drainage.'})

    spray = [d['label'] for d in week
             if (d.get('precip_prob') or 0) < 30 and (d.get('wind') or 0) < 15
             and (d.get('tmax') or 0) < 30 and (d.get('precip') or 0) < 1]
    alerts.append({'level': 'info', 'icon': 'sprinkler', 'title': 'Spraying windows',
                   'text': ('Good days to spray (little wind, dry, not too hot): ' + ', '.join(spray)
                            + '. Spray early morning or evening.') if spray
                   else 'No good spraying day this week (rain, wind or heat).'})

    rain_7 = sum(d.get('precip') or 0 for d in week)
    et0_7 = sum(d.get('et0') or 0 for d in week)
    if crop_key in CROPS and et0_7:
        alerts.append({'level': 'info', 'icon': 'water_drop', 'title': 'Water balance (7 days)',
                       'text': f'Expected rain {rain_7:.0f} mm against about {et0_7:.0f} mm of '
                               'reference evaporation. ' + (
                                   'Rain should cover the crop this week.' if rain_7 >= et0_7
                                   else 'Plan irrigation for the difference if the crop is growing.')})

    if crop_key in MANAGEMENT:
        flags = _weather_flags(days)
        for threat in MANAGEMENT[crop_key]['protection']:
            trig = threat.get('trigger')
            if trig and flags.get(trig) and today.month in threat['months']:
                alerts.append({'level': 'warning', 'icon': 'coronavirus',
                               'title': f"{threat['name']}: favourable weather",
                               'text': f"{threat['watch']} Prevention: {threat['prevent']}"})
    return alerts


def crop_plan(crop_key, sowing_date=None, today=None):
    """Everything the farmer page shows for one crop."""
    if crop_key not in CROPS:
        return None
    mgmt = MANAGEMENT.get(crop_key, {})
    return {
        'crop': crop_key,
        'names': CROPS[crop_key]['names'],
        'calendar': crop_calendar(crop_key, sowing_date, today),
        'fertilizer': mgmt.get('fertilizer'),
        'fertilizer_notice': FERTILIZER_NOTICE,
        'protection': mgmt.get('protection', []),
        'protection_notice': PROTECTION_NOTICE,
    }
