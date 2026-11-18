"""Farm questions answered from the farm's own data, never invented.

When the farmer asks the assistant about his farm, the answer is written by
code from the very functions the farmer pages use (irrigation_schedule,
farm_tasks, crop_management, product_catalog, farmer_service), so the chat and
the screens always agree and no number can be made up. No language model is
involved here.

  1. topics()    which farm topics the question asks about (English, French,
                 Arabic; typo tolerant, via assistant_nlu). A short follow-up
                 ("and the pump?", "why?") keeps the previous topics.
  2. ANSWERS     one function per topic, writing only what that topic needs:
                 "when should I water?" gets the date, the amount and the
                 reason, not the drought score.
  3. answer()    the payload of the assistant API, or None when the question
                 is not about the farm (the regional assistant then answers).

Missing data is said plainly ("add your water flow to get the pump time"),
never guessed. Texts are English msgids translated with gettext (French and
Arabic in locale/assistant_pairs.py; task, stage and product texts reuse the
page's own translations).
"""
import datetime as dt
import logging
from functools import cached_property

from django.utils import translation
from django.utils.formats import date_format
from django.utils.translation import gettext as _

from . import assistant_nlu as nlu
from . import crop_suitability as cs

logger = logging.getLogger(__name__)

MAX_TOPICS = 3
FOLLOWUP_MAX_TOKENS = 5

# ------------------------------------------------------------------ #
# Understanding: topics and their keywords
# ------------------------------------------------------------------ #
# A leading "~" marks a generic word: it counts, but less than a precise phrase.
TOPIC_KEYWORDS = {
    'next_watering': (
        '~water', 'watering', 'irrigat', 'how much water', 'when to water', 'when should i water',
        'when do i water', 'next watering', 'how many mm', 'dose of water',
        '~arros', 'arroser', 'arrosage', 'irriguer', "combien d eau", 'quand arroser', 'prochain arrosage',
        '~سقي', 'اسقي', 'نسقي', 'سقية', 'السقي', 'الري', 'كم ماء', 'كمية الماء', 'متى اسقي'),
    'pump_time': (
        'pump', 'how long', 'how many hours', 'hours of pumping',
        'pompe', 'combien de temps', 'combien d heures',
        'مضخة', 'المضخة', 'كم ساعة', 'ساعات'),
    'soil_water': (
        'soil water', 'soil moisture', 'water in the soil', 'water in soil', 'soil is dry', 'soil dry', 'dry soil',
        'humidite du sol', 'eau dans le sol', 'sol sec', 'sol est sec',
        'رطوبة التربة', 'الماء في التربة', 'ماء التربة', 'التربة جافة'),
    'skip_scenario': (
        'don t water', 'dont water', 'do not water', 'if i skip', 'skip the watering', 'skip watering',
        'without watering', 'without water', 'what happens if', 'what if i',
        'n arrose pas', 'sans arroser', 'sans arrosage', 'si je saute', 'que se passe', 'et si je',
        'لم اسق', 'لا اسقي', 'بدون سقي', 'ماذا يحدث', 'ما سقيتش'),
    'water_16d': (
        'total water', 'water need', 'water needs', 'next 16 days', '16 days', 'water this week',
        'water next week', 'besoin en eau', 'besoins en eau', '16 jours', 'eau cette semaine',
        'حاجة الماء', 'احتياج الماء', '16 يوم', 'ماء هذا الاسبوع'),
    'season_water': (
        'season', 'rest of the season', 'coming months', 'next months', 'per month', 'monthly', 'this year',
        'saison', 'prochains mois', 'mois prochains', 'par mois', 'cette annee',
        'الموسم', 'الاشهر القادمة', 'شهريا', 'هذا العام'),
    'recent_stress': (
        'stress', 'suffer', 'suffered', 'thirst', 'thirsty', 'yield loss', 'lost', 'damage',
        'souffr', 'stress hydrique', 'perte', 'pertes', 'soif',
        'عطش', 'اجهاد', 'خسارة', 'تضرر', 'يعاني'),
    'todo': (
        'what should i do', 'what to do', 'what do i do', 'to do', 'todo', 'tasks', 'reminder', 'reminders',
        'que dois je faire', 'que faire', 'a faire', 'taches', 'rappel', 'rappels',
        'ماذا افعل', 'ما العمل', 'المهام', 'مهام', 'تذكير', 'شنوة نعمل'),
    'fertilizer': (
        'fertiliz', 'fertilis', 'nitrogen', 'npk', 'urea', 'dap', 'ammonium', 'potassium', 'phosph',
        'engrais', 'azote', 'uree', 'ammonitrate', 'potasse',
        'تسميد', 'سماد', 'اسمدة', 'الازوت', 'امونيتر', 'يوريا', 'بوتاسيوم'),
    'pests': (
        'pest', 'disease', 'insect', 'bug', 'fungus', 'weed', 'pesticide', 'insecticide', 'fungicide',
        'herbicide', 'treat', 'treatment', '~spray', 'symptom', 'sick', 'product',
        'ravageur', 'maladie', 'insecte', 'champignon', 'mauvaise herbe', 'mauvaises herbes',
        'traitement', 'traiter', 'produit', 'symptome',
        'مرض', 'امراض', 'حشرة', 'حشرات', 'افة', 'افات', 'مبيد', 'دواء', 'علاج', 'اعشاب', 'اعراض'),
    'spray_day': (
        'when to spray', 'when should i spray', 'when can i spray', 'day to spray', 'spray day',
        'spraying day', 'good day', 'quand traiter', 'quand pulveriser', 'jour pour traiter', 'meilleur jour',
        'متى ارش', 'يوم الرش', 'وقت الرش', 'يوم للرش', 'للرش'),
    'weather': (
        'weather', 'forecast', 'tomorrow', 'temperature', 'hot', 'cold', 'wind', 'windy', 'rain',
        'meteo', 'quel temps', 'demain', 'chaud', 'froid', 'vent', 'pluie', 'pleuvoir', 'pleut',
        'الطقس', 'الجو', 'غدا', 'حرارة', 'برد', 'رياح', 'ريح', 'مطر', 'امطار', 'تمطر'),
    'alerts': (
        'alert', 'warning', 'frost', 'heat wave', 'heatwave', 'storm',
        'alerte', 'gel', 'gelee', 'canicule', 'orage',
        'تنبيه', 'تحذير', 'صقيع', 'موجة حر', 'عاصفة'),
    'what_to_plant': (
        'what to plant', 'what should i plant', 'what can i plant', 'which crop', 'best crop',
        'plant now', 'can i plant', 'can i sow', '~grow', '~plant', 'worst crop', 'riskiest', '~dangerous',
        '~risky', '~avoid', 'low success', 'success rate', '~fail', 'least suitable', 'most suitable',
        'quoi planter', 'que planter', 'quelle culture', 'semer', 'cultiver', '~planter', 'pire culture',
        '~dangereu', '~risque', '~eviter', 'taux de reussite', '~echec',
        'ماذا ازرع', 'شنوة نزرع', 'افضل محصول', 'اي محصول', 'ازرع', 'نزرع', 'اسوا محصول', '~خطير', '~اخطر',
        '~تجنب', 'نسبة النجاح', '~فشل'),
    'crop_status': (
        'harvest', 'stage', 'growth stage', 'sowing date', 'when did i sow', 'ripe', 'mature',
        'recolte', 'recolter', 'stade', 'date de semis', 'maturite',
        'الحصاد', 'احصد', 'جني', 'المرحلة', 'مرحلة', 'تاريخ الزرع', 'نضج'),
    'farm_info': (
        'my farm', 'farm size', 'area', 'how big', 'soil type', 'type of soil', 'my soil', 'texture',
        'irrigation method', 'flow rate', 'ma parcelle', 'superficie', 'surface', 'type de sol', 'mon sol',
        'debit', 'ضيعتي', 'مساحة', 'المساحة', 'نوع التربة', 'تربتي', 'طريقة السقي', 'الدفق'),
    'last_watering': (
        'last watering', 'last irrigation', 'when did i water', 'when did i last', 'did i water',
        'my log', 'farm log', 'history', 'recorded',
        'dernier arrosage', 'quand ai je arrose', 'journal', 'historique',
        'اخر سقية', 'اخر سقي', 'متى سقيت', 'السجل', 'سجل'),
    'how_calculated': (
        'how do you calculate', 'how is it calculated', 'how is this calculated', 'how do you know',
        'calculation', 'data source', 'where does the data', 'source', 'trust', 'accurate', 'accuracy',
        'comment calcul', 'comment savez', 'calcul', 'source des donnees', 'fiable', 'precision',
        'كيف تحسب', 'كيف يتم الحساب', 'مصدر', 'مصدر البيانات', 'دقة', 'دقيق'),
    'capabilities': (
        'what can you do', 'what can i ask', 'help me', 'who are you',
        'que peux tu', 'que sais tu', 'aide moi', 'qui es tu',
        'ماذا يمكنك', 'من انت', 'ساعدني'),
}
# A more precise topic replaces the generic ones it overlaps with.
SUPPRESS = {
    'skip_scenario': {'next_watering', 'soil_water', 'recent_stress', 'water_16d'},
    'last_watering': {'next_watering', 'farm_info'},
    'water_16d': {'next_watering'},
    'season_water': {'next_watering', 'water_16d'},
    'how_calculated': {'next_watering', 'soil_water', 'farm_info'},
    'spray_day': {'pests', 'weather'},
    'alerts': {'weather'},
    'soil_water': {'farm_info'},
    'recent_stress': {'next_watering'},
    'pump_time': {'farm_info'},
    'crop_status': {'what_to_plant'},
    'pests': {'what_to_plant'},       # "most dangerous pest" is about pests
}
# These only make sense about water ("next month" alone is a drought question).
NEEDS_WATER_WORD = {'water_16d', 'season_water'}
WATER_WORDS = ('water', 'irrigat', 'watering', 'arros', 'irrig', 'eau', 'سقي', 'الري', 'ماء', 'مياه')
# A past-tense weather question is about measurements: the regional assistant has them.
PAST_MARKERS = ('last week', 'last month', 'past', 'did it rain', 'yesterday', 'dernier', 'derniere',
                'passe', 'a plu', 'hier', 'الماضي', 'الماضية', 'امس', 'سابق')
TOMORROW = ('tomorrow', 'demain', 'غدا', 'غدوة')
RAIN_WORDS = ('rain', 'pluie', 'pleuv', 'pleut', 'مطر', 'امطار', 'تمطر')
FOLLOWUP_MARKERS = ('and', 'also', 'what about', 'why', 'how much', 'et', 'aussi', 'pourquoi', 'combien',
                    'و', 'لماذا', 'علاش', 'كم', 'وماذا')

# Pest sub-questions
SUB_WATCH = ('recognise', 'recognize', 'identify', 'symptom', 'signs', 'look like', 'how do i know',
             'reconnaitre', 'symptome', 'signes', 'اعراض', 'علامات', 'كيف اعرف')
SUB_PREVENT = ('prevent', 'avoid', 'prevention', 'protect', 'eviter', 'prevenir', 'proteger',
               'وقاية', 'تجنب', 'منع', 'حماية')
SUB_PRODUCT = ('product', 'which product', 'what to spray', 'pesticide', 'insecticide', 'fungicide',
               'herbicide', 'dose', 'produit', 'quel produit', 'منتج', 'دواء', 'مبيد', 'جرعة')
SUB_TREAT = ('treat', 'control', 'kill', 'get rid', 'cure', 'traiter', 'lutter', 'eliminer',
             'علاج', 'مكافحة', 'القضاء')
THREAT_STOPWORDS = {'and', 'the', 'of', 'et', 'de', 'la', 'le', 'des', 'du', 'alert', 'alerte'}

_TABLE = {}


def _table():
    if 'kw' not in _TABLE:
        table = {}
        for topic, words in TOPIC_KEYWORDS.items():
            table[topic] = [(nlu.normalize_text(w.lstrip('~')), 0.75 if w.startswith('~') else 1.0)
                            for w in words]
        _TABLE['kw'] = table
    return _TABLE['kw']


def _has_any(norm, tokens, words):
    return any(nlu.keyword_score(norm, tokens, nlu.normalize_text(w)) for w in words)


def _score(norm, tokens, keyword, weight):
    s = nlu.keyword_score(norm, tokens, keyword)
    if s == 2 and ' ' in keyword:
        s = 3            # an exact phrase is the strongest signal
    return s * weight


def topics(question, previous=None):
    """The farm topics a question asks about, most relevant first."""
    norm = nlu.normalize_text(question)
    tokens = norm.split()
    if not norm:
        return []
    scores, best_kw = {}, {}
    for topic, words in _table().items():
        hits = sorted(((_score(norm, tokens, w, weight), w) for w, weight in words), reverse=True)
        hits = [h for h in hits if h[0]]
        if hits:
            scores[topic] = hits[0][0] + 0.25 * (len(hits) - 1)
            best_kw[topic] = hits[0][1]
    if not _has_any(norm, tokens, WATER_WORDS):
        for t in NEEDS_WATER_WORD:
            scores.pop(t, None)
    if 'weather' in scores and _has_any(norm, tokens, PAST_MARKERS):
        scores.pop('weather')
    if not scores:
        # "and the pump?", "why?": keep the topic of the previous answer
        if previous and len(tokens) <= FOLLOWUP_MAX_TOKENS and (
                _has_any(norm, tokens, FOLLOWUP_MARKERS) or len(tokens) <= 2):
            return [t for t in previous if t in TOPIC_KEYWORDS][:MAX_TOPICS]
        return []
    top = max(scores.values())
    if top >= 1.5:
        # a precise keyword always counts, so "when to water and will it rain?" gets both
        keep = [t for t, s in sorted(scores.items(), key=lambda kv: -kv[1]) if s >= max(1.5, min(top * 0.6, 2))]
    else:   # only typo-level matches: trust the best one, in a short message, on a long keyword
        best = max(scores, key=scores.get)
        keep = [best] if len(tokens) <= 6 and len(best_kw[best]) >= 5 else []
    for t in list(keep):
        for weaker in SUPPRESS.get(t, ()):
            if weaker in keep:
                keep.remove(weaker)
    if 'todo' in keep and len(keep) > 1:
        keep.remove('todo')             # "what should I do against X": X is the topic
    if 'capabilities' in keep and len(keep) > 1:
        keep.remove('capabilities')
    return keep[:MAX_TOPICS]


# ------------------------------------------------------------------ #
# Formatting
# ------------------------------------------------------------------ #

def n(value, digits=1):
    """12, 12.5 - no trailing zero, no thousands separator (read aloud easily)."""
    if value is None:
        return '—'
    v = round(float(value), digits)
    return str(int(v)) if v == int(v) else f'{v:.{digits}f}'.rstrip('0').rstrip('.')


def d(iso_or_date):
    day = iso_or_date if isinstance(iso_or_date, dt.date) else dt.date.fromisoformat(str(iso_or_date))
    return date_format(day, 'j F')


def when(iso_or_date, today):
    day = iso_or_date if isinstance(iso_or_date, dt.date) else dt.date.fromisoformat(str(iso_or_date))
    k = (day - today).days
    if k == 0:
        return _('today')
    if k == 1:
        return _('tomorrow')
    if k == -1:
        return _('yesterday')
    if k > 1:
        return _('in {n} days').format(n=k)
    return _('{n} days ago').format(n=-k)


def sep(lang, strong=False):
    """List separators: Arabic has its own comma and semicolon."""
    if lang == 'ar':
        return '؛ ' if strong else '، '
    return '; ' if strong else ', '


def crop_name(key, lang):
    crop = cs.CROPS.get(key) or {}
    name = (crop.get('names') or {}).get(lang) or (crop.get('names') or {}).get('en') or key or ''
    return name[:1].upper() + name[1:]


STAGE_MSG = {'initial': 'Establishment', 'development': 'Growing', 'mid': 'Full canopy (peak need)',
             'late': 'Maturation', 'perennial': 'Tree / perennial'}
METHOD_MSG = {'drip': 'Drip', 'sprinkler': 'Sprinkler', 'surface': 'Surface / furrow'}
TEXTURE_MSG = {'light': 'light (sandy)', 'medium': 'medium (loam)', 'heavy': 'heavy (clay)'}
LIMIT_MSG = {'water': 'needs more water', 'temperature': 'climate not ideal', 'ph': 'soil pH not ideal',
             'texture': 'soil type not ideal', 'salinity': 'salty soil'}
CLASS_MSG = {'S1': 'highly suitable', 'S2': 'suitable', 'S3': 'marginal', 'N': 'not suitable'}
KIND_MSG = {'irrigation': 'Watering', 'fertilizer': 'Fertiliser', 'treatment': 'Treatment',
            'scouting': 'Field check', 'sowing': 'Sowing', 'harvest': 'Harvest', 'other': 'Other'}
# Reminder titles: the very texts of the farmer page (same msgids, same translations).
TASK_TITLE = {
    'irr_missed': 'Did you water since {since}?', 'irr_last': 'When did you last water this farm?',
    'irr_due': 'Water {mm} mm ({m3} m³)', 'fert_ask': 'Did you apply {product}?',
    'fert_due': 'Apply {product}', 'scout': 'Check the field for {name}',
    'sow_ask': 'Have you sown? Tell us the date', 'harvest_soon': 'Harvest around {date}',
    'harvest_ask': 'Have you harvested?',
}


def task_title(title):
    params = {}
    for k, v in (title.get('params') or {}).items():
        params[k] = d(v) if k in ('since', 'date', 'due') and v else n(v) if isinstance(v, (int, float)) else v
    return _(TASK_TITLE.get(title['code'], title['code'])).format(**params)


# ------------------------------------------------------------------ #
# The farm's data, computed only when a topic needs it
# ------------------------------------------------------------------ #

class FarmData:
    def __init__(self, farm, today, lang):
        self.farm, self.today, self.lang = farm, today, lang

    @cached_property
    def activities(self):
        from .irrigation_schedule import recent_activities
        return recent_activities(self.farm, self.today)

    @cached_property
    def irrigation(self):
        from .irrigation_schedule import farm_irrigation
        return farm_irrigation(self.farm, self.today, activities=self.activities)

    @cached_property
    def tasks(self):
        from .farm_tasks import farm_tasks
        return farm_tasks(self.farm, self.today)

    @cached_property
    def weather(self):
        from .farmer_service import farm_weather
        try:
            return farm_weather(self.farm)
        except Exception:      # the forecast service is optional for an answer
            logger.exception('farm_qa: forecast failed (farm %s)', self.farm.pk)
            return {'forecast': {'error': 'unavailable'}, 'alerts': []}

    @cached_property
    def forecast_days(self):
        fc = self.weather.get('forecast') or {}
        if fc.get('error'):
            return []
        return [x for x in fc.get('days') or [] if x.get('date', '') >= self.today.isoformat()]

    @cached_property
    def advice(self):
        from .farmer_service import farm_advice
        try:
            return farm_advice(self.farm, self.today.month)
        except Exception:
            logger.exception('farm_qa: advice failed (farm %s)', self.farm.pk)
            return {'error': _('Not found.')}

    @cached_property
    def crop(self):
        return self.farm.crop if self.farm.crop in cs.CROPS else None

    @cached_property
    def area(self):
        return float(self.farm.area_ha)


def _need_crop(data):
    if not data.crop:
        return [_('Tell me what grows on this farm first (edit the farm and choose the crop): '
                  'this answer depends on the crop.')]
    return None


def _irrigation_or_reason(data):
    """(irrigation result, None) or (None, sentences explaining why there is no plan)."""
    missing = _need_crop(data)
    if missing:
        return None, missing
    ir = data.irrigation
    if not ir.get('available'):
        return None, [_('The watering plan needs the weather forecast, which is unavailable right now. '
                        'Please try again later.')]
    season = ir.get('season') or {}
    if season.get('state') == 'not_sown':
        return None, [_('The crop is not sown yet (sowing planned on {date}): no watering is planned '
                        'before that.').format(date=d(season['sowing_date']))]
    if season.get('state') == 'harvested':
        return None, [_('The season is over (harvest on {date}): no watering is planned.').format(
            date=d(season.get('harvested_on') or season['harvest_date']))]
    if ir['now']['code'] == 'no_crop':
        return None, [_('There is no crop in the field right now, so no watering is planned.')]
    return ir, None


# ------------------------------------------------------------------ #
# One answer per topic
# ------------------------------------------------------------------ #

def a_next_watering(data, q):
    ir, why_not = _irrigation_or_reason(data)
    if why_not:
        return why_not
    st, nxt = ir['now'], ir.get('next')
    out = []
    if not nxt:
        out.append(_('No watering is needed in the next 16 days: the water in the soil ({pct}% of what '
                     'the roots can use) and the expected rain cover the crop.').format(pct=n(st['available_pct'], 0)))
        return out
    lead = (_('Next watering: {when} ({date}).') if ir.get('irrigated') else
            _('Your farm is marked as rain only. If you can irrigate, a supplementary watering is due '
              '{when} ({date}).'))
    out.append(lead.format(when=when(nxt['date'], data.today), date=d(nxt['date'])))
    out.append(_('Give {mm} mm (= {mm} litres per m²), that is {m3} m³ for your {area} ha.').format(
        mm=n(nxt['gross_mm']), m3=n(nxt['m3_farm'], 0), area=n(data.area, 2)))
    if nxt.get('hours') is not None:
        out.append(_('Run the pump about {h} h.').format(h=n(nxt['hours'])))
        out += _pump_reality(nxt['hours'], ir.get('flow_m3h'))
    out.append(_('Why: the soil holds {pct}% of the water the roots can use, and watering is due at '
                 '{thr}%.').format(pct=n(st['available_pct'], 0), thr=n(st['threshold_pct'], 0)))
    missed = ir.get('missed')
    if missed and missed.get('ask'):
        out.append(_('A watering was due on {date} and none is recorded since: if you watered, record it '
                     'in the farm log so the plan is right.').format(date=d(missed['due_date'])))
    if 'split_dose' in (nxt.get('tips') or []):
        out.append(_('It is a large catch-up dose: split it over 2 or 3 days so the soil can absorb it.'))
    return out


def _pump_reality(hours, flow):
    """A pump time longer than a day cannot be done in one go: say so."""
    if hours is None or hours <= 24:
        return []
    return [_('At {flow} m³ per hour this takes about {days} days of pumping: check the flow you entered, '
              'or water the farm in sectors.').format(flow=n(flow), days=n(hours / 24, 0))]


def a_pump_time(data, q):
    ir, why_not = _irrigation_or_reason(data)
    if why_not:
        return why_not
    nxt = ir.get('next')
    if not nxt:
        return [_('No watering is planned in the next 16 days, so no pumping is needed.')]
    if nxt.get('hours') is None:
        return [_('I cannot compute the pump time: add your water flow (m³ per hour) in "Method & flow" '
                  'on the Water tab. The next watering is {mm} mm, that is {m3} m³ for the farm.').format(
                      mm=n(nxt['gross_mm']), m3=n(nxt['m3_farm'], 0))]
    return [_('For the next watering ({mm} mm, {when}) run the pump about {h} h at {flow} m³ per hour '
              '({m3} m³ in total).').format(mm=n(nxt['gross_mm']), when=when(nxt['date'], data.today),
                                            h=n(nxt['hours']), flow=n(ir['flow_m3h']), m3=n(nxt['m3_farm'], 0))] + \
        _pump_reality(nxt['hours'], ir['flow_m3h'])


def a_soil_water(data, q):
    ir, why_not = _irrigation_or_reason(data)
    if why_not:
        return why_not
    st = ir['now']
    out = [_('Water in the soil now: {pct}% of what the roots can use ({used} mm used out of {taw} mm). '
             'Watering is due at {thr}% and the crop starts to suffer below {stress}%.').format(
                 pct=n(st['available_pct'], 0), used=n(st['depletion_mm'], 0), taw=n(st['taw_mm'], 0),
                 thr=n(st['threshold_pct'], 0), stress=n(st['stress_pct'], 0))]
    if ir.get('first_stress_date'):
        out.append(_('Without watering, the crop would start to suffer {when} ({date}).').format(
            when=when(ir['first_stress_date'], data.today), date=d(ir['first_stress_date'])))
    else:
        out.append(_('Even without watering, the crop stays comfortable for the next 16 days.'))
    return out


def a_skip_scenario(data, q):
    ir, why_not = _irrigation_or_reason(data)
    if why_not:
        return why_not
    fo, sk = ir['scenarios']['follow'], ir['scenarios']['skip']
    out = [_('If you follow the plan: {n} waterings, {mm} mm in total, and {s} days of water stress in the '
             'next 16 days.').format(n=fo['waterings'], mm=n(fo['gross_mm'], 0), s=fo['stress_days'])]
    if sk.get('first_stress_date'):
        out.append(_('If you do not water: the crop suffers from {date}, with {s} days of water stress, and '
                     'about {risk}% of the harvest is at risk.').format(
                         date=d(sk['first_stress_date']), s=sk['stress_days'], risk=n(sk['yield_risk_pct'] or 0, 0)))
    else:
        out.append(_('If you do not water: the crop stays without water stress for the next 16 days.'))
    return out


def a_water_16d(data, q):
    ir, why_not = _irrigation_or_reason(data)
    if why_not:
        return why_not
    t = ir['totals']
    return [_('Next 16 days: {n} waterings, {mm} mm in total, that is {m3} m³ for the farm. The crop will use '
              'about {etc} mm and useful rain brings {rain} mm.').format(
                  n=len(ir['events']), mm=n(t['gross_mm'], 0), m3=n(t['m3_farm'], 0),
                  etc=n(t['etc_mm'], 0), rain=n(t['peff_mm'], 0))]


def a_season_water(data, q):
    missing = _need_crop(data)
    if missing:
        return missing
    o = data.irrigation.get('outlook')
    if not o or not o.get('months'):
        return [_('The monthly outlook needs the climate history of your region, which is not available '
                  'for this farm.')]
    parts = []
    for r in o['months']:
        month = date_format(dt.date(r['year'], r['month'], 1), 'F')
        parts.append(_('{month}: no crop').format(month=month) if not r.get('growing_days')
                     else _('{month}: {mm} mm').format(month=month, mm=n(r.get('gross_mm') or 0, 0)))
    out = [_('Average watering need in the coming months (average year): {months}.').format(months=sep(data.lang, True).join(parts))]
    if o.get('rest_of_season_gross_mm'):
        out.append(_('Rest of the season: about {mm} mm, that is {m3} m³ for the farm.').format(
            mm=n(o['rest_of_season_gross_mm'], 0), m3=n(o['rest_of_season_m3_farm'], 0)))
        supply = data.irrigation.get('water_supply_mm')
        if supply is not None:
            out.append((_('You declared {supply} mm of water: that covers the need.') if supply >= o['rest_of_season_gross_mm']
                        else _('You declared {supply} mm of water: that is less than the need, keep it for the '
                               'most sensitive stages (flowering and fruit set).')).format(supply=n(supply, 0)))
    return out


def a_recent_stress(data, q):
    ir, why_not = _irrigation_or_reason(data)
    if why_not:
        return why_not
    rc = ir.get('recent')
    if not rc or rc.get('days', 0) < 3:
        return [_('I can only judge past water stress from the waterings you record. Record them in the farm '
                  'log and I will tell you.')]
    if rc['stress_days']:
        return [_('Over the last {n} days the crop was short of water on {d} days ({s}% less water than it '
                  'needed): about {r}% of the harvest has been lost.').format(
                      n=rc['days'], d=rc['stress_days'], s=n(rc['shortfall_pct'], 0), r=n(rc['yield_risk_pct'] or 0, 0))]
    return [_('Over the last {n} days the crop had all the water it needed.').format(n=rc['days'])]


def a_todo(data, q):
    missing = _need_crop(data)
    if missing:
        return missing
    tasks = data.tasks.get('tasks') or []
    if not tasks:
        return [_('Nothing to do on this farm today.')]
    asks = [t for t in tasks if t['state'] == 'ask']
    doing = [t for t in tasks if t['state'] != 'ask']
    out = []
    if doing:
        out.append(_('To do:') + ''.join('\n• ' + _('{task} ({when})').format(
            task=task_title(t['title']), when=when(t['date'], data.today)) for t in doing))
    if asks:
        out.append(_('Questions waiting for your answer (Today tab):') + ''.join(
            '\n• ' + task_title(t['title']) for t in asks))
    return out


def _fert_schedule(data):
    """[(date, schedule item)] of this crop's applications around today."""
    from .crop_management import MANAGEMENT, _next_month_date, default_sowing_date
    sched = MANAGEMENT.get(data.crop, {}).get('fertilizer', {}).get('schedule', [])
    sowing = data.farm.sowing_date
    assumed = False
    if not cs.CROPS[data.crop]['perennial'] and sowing is None:
        sowing, assumed = default_sowing_date(data.crop, data.today), True
    out = []
    for item in sched:
        if 'offset_days' in item:
            out.append((sowing + dt.timedelta(days=item['offset_days']), item))
        elif 'month' in item:
            out.append((_next_month_date(item['month'], data.today), item))
    return sorted(out, key=lambda x: x[0]), (sowing if assumed else None)


def a_fertilizer(data, q):
    missing = _need_crop(data)
    if missing:
        return missing
    from .crop_management import tr
    from .product_catalog import fertilizer_details
    sched, assumed = _fert_schedule(data)
    if not sched:
        return [_('There is no fertiliser schedule for this crop in the application.')]
    done = {a.task_key for a in data.activities if a.task_key}
    out = []
    for day, item in sched:
        if dt.timedelta(0) < data.today - day <= dt.timedelta(days=21):
            from .farm_tasks import _slug
            if f"fert:{day.isoformat()}:{_slug(item['product'])}" not in done:
                out.append(_('The application of {product} planned on {date} is not recorded: if you did it, '
                             'add it in the farm log.').format(product=tr(item['product']), date=d(day)))
    upcoming = [(day, item) for day, item in sched if day >= data.today]
    if not upcoming:
        out.append(_('No other fertiliser application is planned this season.'))
        return out
    day, item = upcoming[0]
    out.append(_('Next fertiliser: {product}, {when} ({date}), at the "{stage}" stage. Dose: {rate}.').format(
        product=tr(item['product']), when=when(day, data.today), date=d(day), stage=tr(item['stage']),
        rate=tr(item['rate'])))
    det = fertilizer_details(item['product'], item['rate'], data.area)
    if det.get('farm'):
        f = det['farm']
        out.append(_('For your {area} ha: {kg} kg, that is {bags} bags of {bag} kg.').format(
            area=n(f['area_ha'], 2), kg=f['kg'], bags=f['bags'], bag=f['bag_kg']))
    if det.get('alternative'):
        a = det['alternative']
        out.append(_('Or {name}: {rate} ({kg} kg for the farm).').format(name=a['name'], rate=a['rate'], kg=a['farm_kg'] or '—'))
    if assumed:
        out.append(_('These dates assume sowing on {date}: give your real sowing date (edit the farm) to make '
                     'them exact.').format(date=d(assumed)))
    return out


# ---- pests: a named threat, or this month's threats ----

def _threat_aliases():
    """[(crop, threat, set of normalised token lists)] in the three languages."""
    if 'threats' in _TABLE:
        return _TABLE['threats']
    from .crop_management import MANAGEMENT
    out = []
    for crop, m in MANAGEMENT.items():
        for t in m.get('protection', []):
            names = {t['name']}
            for lang in ('fr', 'ar'):
                with translation.override(lang):
                    names.add(_(t['name']))
            aliases = []
            for name in names:
                base, _sep, inner = name.partition('(')
                for part in (base, inner.rstrip(')')):
                    toks = [w for w in nlu.normalize_text(part).split() if w not in THREAT_STOPWORDS and len(w) >= 3]
                    if toks:
                        aliases.append(toks)
            out.append((crop, t, aliases))
    _TABLE['threats'] = out
    return out


# Words that appear in many threat names: they count, but never name a threat alone.
THREAT_GENERIC = {'leaf', 'leaves', 'spot', 'spots', 'yellow', 'brown', 'black', 'white', 'red', 'late',
                  'green', 'small', 'insect', 'insects', 'fruit', 'plant', 'plants', 'root', 'feuille', 'tache'}


def _crop_tokens():
    if 'crop_tokens' not in _TABLE:
        words = set()
        for key, crop in cs.CROPS.items():
            for name in [key] + list((crop.get('names') or {}).values()):
                for w in nlu.normalize_text(str(name).replace('_', ' ')).split():
                    words |= {w, nlu._strip_article(w)}
        _TABLE['crop_tokens'] = words
    return _TABLE['crop_tokens']


def match_threat(question, farm_crop=None):
    """The pest/disease/weed named in the question, or None.

    A crop name or a generic word ("olive", "leaf", "yellow") never names a
    threat on its own. Threats of the farm's crop are looked up first and
    accept one distinctive word ("rust", "blight", "tuta"); other crops need
    most of the name ("crown rust", "olive fruit fly").
    """
    tokens = nlu.normalize_text(question).split()
    if not tokens:
        return None
    weak = _crop_tokens() | THREAT_GENERIC

    def hits(alias):
        return [w for w in alias if any(nlu._token_matches(t, w) >= 0.9 or
                                        nlu._token_matches(nlu._strip_article(t), w) >= 0.9 for t in tokens)]

    for own in (True, False):
        best, best_score = None, 0.0
        for crop, threat, aliases in _threat_aliases():
            if (crop == farm_crop) != own:
                continue
            for alias in aliases:
                found = hits(alias)
                strong = [w for w in found if w not in weak and nlu._strip_article(w) not in weak]
                if not strong:
                    continue
                share = len(found) / len(alias)
                ok = (share >= 0.66 or (len(alias) <= 2 and any(len(w) >= 4 for w in strong))
                      or (own and any(len(w) >= 4 for w in strong)))
                if ok and share + 0.1 * len(found) > best_score:
                    best, best_score = (crop, threat), share + 0.1 * len(found)
        if best:
            return best
    return None


def _product_lines(products, limit):
    lines = []
    for p in products[:limit]:
        head = _('{name} ({group})').format(name=p['name'], group=p['group']) if p['group'] else p['name']
        line = head + (': ' + p['rate'] if p.get('rate') else '')
        if p.get('farm'):
            line += ' — ' + _('for your farm: {qty}').format(qty=p['farm'])
            if p.get('farm_water_l'):
                line += ' ' + _('in {l} L of water').format(l=n(p['farm_water_l'], 0))
        lines.append('\n• ' + line)
    return ''.join(lines)


def a_pests(data, q):
    from .crop_management import MANAGEMENT, tr
    from .product_catalog import protection_options
    norm = nlu.normalize_text(q)
    tokens = norm.split()
    hit = match_threat(q, data.crop)
    if hit is None:
        missing = _need_crop(data)
        if missing:
            return missing
        month = data.today.month
        now = [t for t in MANAGEMENT.get(data.crop, {}).get('protection', []) if month in t['months']]
        cname = crop_name(data.crop, data.lang)
        if not now:
            return [_('No major pest, disease or weed of {crop} is expected this month.').format(crop=cname)]
        out = [_('To watch on your {crop} this month: {names}.').format(
            crop=cname, names=sep(data.lang).join(tr(t['name']) for t in now))]
        favour = [a['title'] for a in (data.weather.get('alerts') or []) if a.get('icon') == 'coronavirus']
        if favour:
            out.append(_('The coming weather favours: {names}.').format(names='; '.join(favour)))
        out.append(_('Ask me about one of them by name to get its symptoms, prevention and products.'))
        return out
    crop, threat = hit
    want_watch, want_prevent = _has_any(norm, tokens, SUB_WATCH), _has_any(norm, tokens, SUB_PREVENT)
    want_products, want_treat = _has_any(norm, tokens, SUB_PRODUCT), _has_any(norm, tokens, SUB_TREAT)
    everything = not (want_watch or want_prevent or want_products or want_treat)
    name = tr(threat['name'])
    out = []
    if crop != data.crop:
        out.append(_('{threat} is a problem of {crop}.').format(threat=name, crop=crop_name(crop, data.lang)))
    if want_watch or everything:
        out.append(_('{threat} — how to recognise it: {text}').format(threat=name, text=tr(threat['watch'])))
    if want_prevent or everything:
        out.append(_('Prevention: {text}').format(text=tr(threat['prevent'])))
    if want_treat or everything:
        out.append(_('Treatment: {text}').format(text=tr(threat['control'])))
    if want_products or want_treat or everything:
        products = protection_options(crop, threat['name'], data.area if crop == data.crop else None)
        if products:
            out.append(_('Products that help:') + _product_lines(products, 5 if want_products else 3))
            out.append(_('Names are active ingredients: buy any registered brand that contains it, and always '
                         'follow its label (dose, protective equipment, days before harvest).'))
    return out


def a_spray_day(data, q):
    from .product_catalog import best_spray_day
    if not data.forecast_days:
        return [_('The weather forecast is unavailable right now.')]
    day = best_spray_day(data.forecast_days, data.today.isoformat())
    if day:
        return [_('Best day to spray this week: {date} (dry, little wind, not hot). Spray early in the '
                  'morning or in the evening.').format(date=f'{when(day, data.today)} ({d(day)})')]
    return [_('No good spraying day this week (rain, wind or heat): wait before treating.')]


def _day_line(label, x):
    return _('{label}: {cond}, {tmin} to {tmax} °C, rain {rain} mm ({prob}% chance), wind {wind} km/h.').format(
        label=label, cond=(x.get('condition') or {}).get('label', '—'), tmin=n(x.get('tmin'), 0),
        tmax=n(x.get('tmax'), 0), rain=n(x.get('precip') or 0), prob=n(x.get('precip_prob') or 0, 0),
        wind=n(x.get('wind'), 0))


def a_weather(data, q):
    days = data.forecast_days
    if not days:
        return [_('The weather forecast is unavailable right now.')]
    norm = nlu.normalize_text(q)
    tokens = norm.split()
    out = []
    if _has_any(norm, tokens, TOMORROW) and len(days) > 1:
        out.append(_day_line(_('Tomorrow'), days[1]))
    week = days[:7]
    rain_total = sum(x.get('precip') or 0 for x in week)
    rainy = [x for x in week if (x.get('precip') or 0) >= 1]
    if _has_any(norm, tokens, RAIN_WORDS):
        if rainy:
            out.append(_('Rain expected in the next 7 days: {mm} mm in total. Next rainy day: {date}, {day_mm} mm.').format(
                mm=n(rain_total), date=f"{when(rainy[0]['date'], data.today)} ({d(rainy[0]['date'])})",
                day_mm=n(rainy[0]['precip'])))
        else:
            out.append(_('No rain is expected in the next 7 days.'))
    if not out:
        out.append(_day_line(_('Today'), days[0]))
        out.append(_('Next 7 days: {mm} mm of rain on {n} days, temperatures from {tmin} to {tmax} °C.').format(
            mm=n(rain_total), n=len(rainy), tmin=n(min(x.get('tmin') or 0 for x in week), 0),
            tmax=n(max(x.get('tmax') or 0 for x in week), 0)))
    return out


def a_alerts(data, q):
    if not (data.weather.get('forecast') or {}).get('days'):
        return [_('The weather forecast is unavailable right now.')]
    alerts = [a for a in data.weather.get('alerts') or [] if a.get('level') in ('danger', 'warning')]
    if not alerts:
        return [_('No frost, heat, heavy-rain or disease alert for your farm in the next 7 days.')]
    return [f"{a['title']}: {a['text']}" for a in alerts]


# "Which crops should I avoid / are the riskiest / have a low success rate?"
WORST_WORDS = ('worst', 'riskiest', 'dangerous', 'risky', 'avoid', 'low success', 'least', 'fail', 'bad',
               'unsuitable', 'not suitable', 'pire', 'dangereu', 'risque', 'eviter', 'echec', 'mauvais',
               'moins adapt', 'اسوا', 'خطير', 'اخطر', 'تجنب', 'فشل', 'اقل', 'غير ملائم')
BEST_WORDS = ('best', 'most suitable', 'highest', 'good', 'meilleur', 'plus adapt', 'افضل', 'احسن')


def _score_now(r):
    """Score if sown this month (the model's out-of-window estimate when needed)."""
    if r.get('plantable_now') is False and r.get('if_sown_now'):
        return r['if_sown_now']
    return r


def a_what_to_plant(data, q):
    adv = data.advice
    if adv.get('error'):
        return [adv['error']]
    norm = nlu.normalize_text(q)
    tokens = norm.split()
    asked = nlu.match_crop(q)
    ranking = adv.get('ranking') or []
    if asked and asked in cs.CROPS:
        r = next((x for x in ranking if x['crop'] == asked), None)
        if r is None:
            return [_('I have no suitability score for this crop here.')]
        cname = crop_name(asked, data.lang)
        if r.get('plantable_now') is False and r.get('if_sown_now'):
            now = r['if_sown_now']
            out = [_('{crop} sown this month: {cls} (score {score}/100).').format(
                crop=cname, cls=_(CLASS_MSG[now['class']]), score=n(now['score'], 0))]
            month = date_format(dt.date(2001, r['next_planting_month'], 1), 'F')
            out.append(_('Its usual sowing time starts in {month}: {cls} (score {score}/100) then.').format(
                month=month, cls=_(CLASS_MSG[r['next_window']['class']]), score=n(r['next_window']['score'], 0)))
            return out
        return [_('{crop} on this farm: {cls} (score {score}/100).').format(
            crop=cname, cls=_(CLASS_MSG[r['class']]), score=n(r['score'], 0))]
    worst = _has_any(norm, tokens, WORST_WORDS)
    best = _has_any(norm, tokens, BEST_WORDS) or not worst
    out = []
    if best:
        top = (adv.get('plant_now') or [])[:3]
        if top:
            items = sep(data.lang).join(_('{crop} ({score}/100)').format(crop=crop_name(r['crop'], data.lang),
                                                               score=n(r['score'], 0)) for r in top)
            out.append(_('Best crops to plant now on this farm (climate and soil of your parcel): {items}.').format(
                items=items))
        else:
            out.append(_('No crop is well suited to plant this month on this farm.'))
    if worst:
        scored = sorted(((r, _score_now(r)) for r in ranking), key=lambda rs: rs[1]['score'])[:3]
        items = []
        for r, now in scored:
            lim = now.get('limiting_factor')
            problem = _(LIMIT_MSG[lim]) if lim in LIMIT_MSG and (now.get('factors') or {}).get(lim, 1) < 0.95 else ''
            label = _('{crop} ({score}/100)').format(crop=crop_name(r['crop'], data.lang), score=n(now['score'], 0))
            items.append(label + (': ' + problem if problem else ''))
        out.append(_('Riskiest crops to plant now on this farm (lowest chance of success): {items}.').format(
            items=sep(data.lang, True).join(items)))
    return out


def a_crop_status(data, q):
    missing = _need_crop(data)
    if missing:
        return missing
    crop = cs.CROPS[data.crop]
    cname = crop_name(data.crop, data.lang)
    if crop['perennial']:
        return [_('{crop} is a tree crop: it has no sowing or harvest date to compute here; its care follows '
                  'the calendar months (see the Plan tab).').format(crop=cname)]
    from .crop_management import default_sowing_date
    from .irrigation_schedule import crop_state, season_bounds
    sowing = data.farm.sowing_date
    assumed = sowing is None
    if assumed:
        sowing = default_sowing_date(data.crop, data.today)
    _s, harvest = season_bounds(data.crop, sowing)
    if data.today < sowing:
        return [_('{crop}: sowing planned {when} ({date}).').format(crop=cname, when=when(sowing, data.today), date=d(sowing))]
    if data.today >= harvest:
        return [_('{crop}: the season ended; harvest was expected on {date}.').format(crop=cname, date=d(harvest))]
    st = crop_state(data.crop, sowing, data.today)
    out = [_('{crop}: sown on {sow}, now at the "{stage}" stage. Expected harvest {when} ({date}).').format(
        crop=cname, sow=d(sowing), stage=_(STAGE_MSG.get(st['stage'], st['stage'] or '')),
        when=when(harvest, data.today), date=d(harvest))]
    if assumed:
        out.append(_('This assumes sowing on {date}: give your real sowing date (edit the farm) to make it exact.').format(date=d(sowing)))
    return out


def a_farm_info(data, q):
    farm = data.farm
    from .irrigation_schedule import soil_awc
    norm = nlu.normalize_text(q)
    tokens = norm.split()
    soil_only = _has_any(norm, tokens, ('soil', 'texture', 'sol', 'تربة', 'التربة', 'تربتي'))
    awc, tex, src = soil_awc(farm.soil, farm.region)
    soil_line = _('Soil: {texture}; it holds about {awc} mm of water per metre of depth ({source}).').format(
        texture=_(TEXTURE_MSG.get(tex, 'medium (loam)')) if tex else _('unknown texture'),
        awc=n(awc, 0), source=_('measured for your parcel (SoilGrids)') if src == 'parcel'
        else _('average of your region') if src.startswith('region') else _('typical value'))
    if soil_only:
        return [soil_line]
    if farm.irrigated:
        method = _(METHOD_MSG.get(farm.irrigation_method, 'Sprinkler'))
        water = (_('irrigated ({method}, {flow} m³ per hour)').format(method=method, flow=n(farm.irrigation_flow_m3h))
                 if farm.irrigation_flow_m3h else _('irrigated ({method})').format(method=method))
    else:
        water = _('rain only')
    crop = crop_name(farm.crop, data.lang) if farm.crop else _('no crop chosen')
    out = [_('Your farm "{name}": {area} ha, {crop}, {water}.').format(name=farm.name, area=n(data.area, 2),
                                                                       crop=crop, water=water), soil_line]
    if farm.region is not None:
        out.append(_('Climate data come from the region of {region}.').format(region=farm.region.name))
    return out


def a_last_watering(data, q):
    acts = data.activities
    norm = nlu.normalize_text(q)
    tokens = norm.split()
    if _has_any(norm, tokens, ('log', 'journal', 'history', 'historique', 'السجل', 'سجل')):
        if not acts:
            return [_('Your farm log is empty: record your waterings and other work in the farm log.')]
        lines = []
        for a in acts[:6]:
            line = f'{d(a.date)}: ' + _(KIND_MSG.get(a.kind, a.kind))
            if a.amount_mm is not None:
                line += f' {n(a.amount_mm)} mm'
            if a.status == 'skipped':
                line += ' (' + _('not done') + ')'
            lines.append('\n• ' + line)
        return [_('Last entries in your farm log:') + ''.join(lines)]
    done = [a for a in acts if a.kind == 'irrigation' and a.status == 'done']
    last = data.farm.last_irrigation_date
    if not done and not last:
        return [_('No watering is recorded for this farm yet. Record them in the farm log: the plan then '
                  'follows what you really did.')]
    out = []
    if done:
        a = done[0]
        out.append((_('Your last recorded watering: {date} ({when}), {mm} mm.') if a.amount_mm is not None
                    else _('Your last recorded watering: {date} ({when}).')).format(
                        date=d(a.date), when=when(a.date, data.today), mm=n(a.amount_mm)))
        month = [x for x in done if (data.today - x.date).days < 30]
        total = sum(float(x.amount_mm) for x in month if x.amount_mm is not None)
        out.append(_('{n} waterings recorded in the last 30 days ({mm} mm with a recorded amount).').format(
            n=len(month), mm=n(total, 0)))
    else:
        out.append(_('Your last recorded watering: {date} ({when}).').format(date=d(last), when=when(last, data.today)))
    return out


def a_how_calculated(data, q):
    out = []
    ir = data.irrigation if data.crop else {}
    if ir.get('available') and ir['now']['code'] != 'no_crop':
        st = ir['now']
        out.append(_('Watering follows the FAO-56 method: every day the crop uses water (crop coefficient {kc} × '
                     'the reference evaporation of the weather), rain refills the soil, and watering is due when '
                     'the roots ({root} m deep, {taw} mm of usable water in your soil) have used {trig} mm.').format(
                         kc=n(st['kc'], 2), root=n(st['root_depth_m'], 2), taw=n(st['taw_mm'], 0),
                         trig=n(st['trigger_mm'], 0)))
        out.append(_('Your {method} system brings {eff}% of the water to the roots, so the dose you apply is '
                     'larger than what the roots receive.').format(
                         method=_(METHOD_MSG[ir['method']]).lower(), eff=n(ir['efficiency'] * 100, 0)))
    out.append(_('Data used: Open-Meteo weather at your parcel (last 60 days and 16-day forecast), FAO-56 crop '
                 'tables, ISRIC SoilGrids soil, the climate history of your region, and your own farm log. '
                 'Fertiliser and product doses are indicative extension values: the label and your CRDA '
                 'office have the final word.'))
    return out


def a_capabilities(data, q):
    return [_('I answer from your farm\'s data: when and how much to water, pump time, water in the soil, '
              'what happens if you skip a watering, your to-do list, fertiliser and products, pests and the '
              'best day to spray, the weather and alerts, growth stage and harvest, what to plant, and your '
              'farm log. For your region I also know the drought outlook, rainfall and temperatures.')]


ANSWERS = {
    'next_watering': a_next_watering, 'pump_time': a_pump_time, 'soil_water': a_soil_water,
    'skip_scenario': a_skip_scenario, 'water_16d': a_water_16d, 'season_water': a_season_water,
    'recent_stress': a_recent_stress, 'todo': a_todo, 'fertilizer': a_fertilizer, 'pests': a_pests,
    'spray_day': a_spray_day, 'weather': a_weather, 'alerts': a_alerts, 'what_to_plant': a_what_to_plant,
    'crop_status': a_crop_status, 'farm_info': a_farm_info, 'last_watering': a_last_watering,
    'how_calculated': a_how_calculated, 'capabilities': a_capabilities,
}
assert set(ANSWERS) == set(TOPIC_KEYWORDS)

SOURCES = {
    'water': 'Farm water balance (FAO-56) with Open-Meteo weather',
    'weather': 'Open-Meteo forecast at your parcel',
    'plan': 'Crop calendar and product catalogue of the application',
    'advice': 'Crop suitability model (climate and soil of your parcel)',
    'log': 'Your farm log',
}
TOPIC_SOURCE = {
    'next_watering': 'water', 'pump_time': 'water', 'soil_water': 'water', 'skip_scenario': 'water',
    'water_16d': 'water', 'season_water': 'water', 'recent_stress': 'water', 'todo': 'plan',
    'fertilizer': 'plan', 'pests': 'plan', 'spray_day': 'weather', 'weather': 'weather', 'alerts': 'weather',
    'what_to_plant': 'advice', 'crop_status': 'plan', 'farm_info': 'plan', 'last_watering': 'log',
    'how_calculated': 'water', 'capabilities': None,
}
SUGGESTIONS = ('When should I water and how much?', 'What should I do today?', 'What happens if I skip the watering?',
               'Which fertiliser now, and how much?', 'Will it rain this week?', 'When is the best day to spray?')


def suggestions(lang):
    with translation.override(lang):
        return [_(s) for s in SUGGESTIONS]


def answer(question, farm, lang='en', previous_topics=None, today=None):
    """Assistant payload for a farm question, or None when it is not one."""
    found = topics(question, previous_topics)
    if 'pests' not in found and match_threat(question, farm.crop if farm else None):
        found = (found + ['pests'])[:MAX_TOPICS] if found != ['capabilities'] else ['pests']
    if not found:
        return None
    today = today or dt.date.today()
    with translation.override(lang):
        data = FarmData(farm, today, lang)
        blocks = []
        for topic in found:
            try:
                lines = ANSWERS[topic](data, question)
            except Exception:       # one broken topic must not hide the others
                logger.exception('farm_qa: topic %s failed (farm %s)', topic, farm.pk)
                lines = [_('I could not read this information right now. Please try again later.')]
            if lines:
                blocks.append(' '.join(lines) if not any('\n' in x for x in lines) else '\n'.join(lines))
        sources = []
        for topic in found:
            key = TOPIC_SOURCE.get(topic)
            if key and not any(s['key'] == key for s in sources):
                sources.append({'key': key, 'title': _(SOURCES[key]), 'kind': 'data', 'source': key})
        text = '\n\n'.join(blocks)
        return {
            'answer': text,
            'intent': 'farm:' + ','.join(found),
            'crop': farm.crop or None,
            'region': farm.region.name if farm.region else None,
            'lang': lang,
            'from_cache': False,
            'engine': 'farm_data',
            'engine_reason': 'answered from the farm data by code (no language model)',
            'model': None,
            'rag': {'enabled': False, 'dense': False, 'documents': 0, 'data': len(sources)},
            'sources': sources,
            'understood': {'crop': farm.crop or None, 'intent': 'farm', 'farm_topics': found,
                           'followup': False, 'inherited': {}},
            'facts': {},
            'details': {'farm_id': farm.pk, 'topics': found},
            'suggestions': suggestions(lang),
        }
