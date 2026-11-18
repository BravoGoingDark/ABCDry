"""The farmer's to-do list: what to do on the parcel, when, how much and why,
from live data (soil-water balance, 16-day forecast, crop stage), plus the
questions about what he did.

Every reminder says WHY (the measurement behind it), WHEN (a date) and HOW
(amount, product, timing tips). A reminder whose date has passed and that
the farmer did not answer becomes a question ("Did you water since ...?").
Answers are FarmActivity rows: they change the soil-water balance (and
therefore the next waterings, stress days and harvest risk), close the
question, or move the season on (sowing date, harvest).

States, in the order the page shows them:
  ask    a past reminder nobody answered: the plan is uncertain until he does
  today  due today (or late)
  soon   due in the next days
Texts are codes + parameters; the farmer page words them in his language.
Product names, rates and pest descriptions come from crop_management (as on
the Plan tab).
"""
import datetime as dt
import logging
import re

from . import crop_management as cm
from . import crop_suitability as cs
from . import irrigation_schedule as irr

logger = logging.getLogger(__name__)

SOON_DAYS = 3            # waterings shown ahead
FERT_AHEAD_DAYS = 7      # fertiliser reminder this long before its date
FERT_ASK_DAYS = 21       # ask about a past application for this long
HARVEST_AHEAD_DAYS = 14
HARVEST_ASK_DAYS = 45
HEAVY_RAIN_MM = 20.0
LIGHT_RAIN_MM = (3.0, 15.0)

STATE_ORDER = {'ask': 0, 'today': 1, 'soon': 2}


def _slug(text):
    return re.sub(r'[^a-z0-9]+', '-', (text or '').lower()).strip('-')[:30]


def _p(code, **params):
    return {'code': code, 'params': params}


# ------------------------------------------------------------------ #
# Water
# ------------------------------------------------------------------ #

def irrigation_tasks(ir, today):
    """Questions about missed waterings and the waterings of the next days."""
    if not ir or not ir.get('available') or not ir.get('irrigated'):
        return []
    st = ir['now']
    if st['code'] == 'no_crop':
        return []
    tasks = []
    nxt = ir.get('next')
    dose = nxt['gross_mm'] if nxt and nxt['date'] == today.isoformat() else None
    missed = ir.get('missed')

    if missed and missed.get('ask'):
        why = [_p('why_irr_missed', due=missed['due_date'],
                  pct=st['available_pct'], thr=st['threshold_pct'])]
        if missed.get('stress_since'):
            why.append(_p('why_irr_stress_since', date=missed['stress_since']))
        tasks.append({
            'key': f"irr-missed:{missed['ask_from']}", 'kind': 'irrigation', 'state': 'ask',
            'date': missed['due_date'], 'title': _p('irr_missed', since=missed['ask_from']),
            'why': why,
            'how': [_p('how_irr_answer', dose=dose)] if dose else [],
            'answer': {'type': 'irrigation', 'min_date': missed['ask_from'], 'dose_mm': dose},
        })
    elif ir['basis'] in ('assumed_schedule', 'sowing'):
        tasks.append({
            'key': 'irr-last', 'kind': 'irrigation', 'state': 'ask', 'date': today.isoformat(),
            'title': _p('irr_last'), 'why': [_p('why_irr_last')], 'how': [],
            'answer': {'type': 'irrigation', 'min_date': None, 'dose_mm': None, 'no_skip': True},
        })

    if nxt and (dt.date.fromisoformat(nxt['date']) - today).days <= SOON_DAYS:
        days_to = (dt.date.fromisoformat(nxt['date']) - today).days
        day_use = next((d['etc'] for d in ir['days'] if d['today']), None)
        soil = ('why_irr_soil_low' if st['available_pct'] is not None and st['threshold_pct'] is not None
                and st['available_pct'] <= st['threshold_pct'] else 'why_irr_soil')
        why = [_p(soil, pct=st['available_pct'], thr=st['threshold_pct'], date=nxt['date']),
               _p('why_irr_use', stage=st['stage'], mm=day_use)]
        if missed and missed.get('reported_skipped'):
            why.append(_p('why_irr_skipped', due=missed['due_date']))
        rain = [d for d in ir['days'] if not d['past'] and d['postponed']]
        if rain:
            why.append(_p('why_irr_rain', date=rain[0]['date']))
        how = [_p('how_irr_amount', mm=nxt['gross_mm'], m3=nxt['m3_farm'], m3ha=nxt['m3_per_ha']),
               _p('how_irr_method_' + ir['method'])]
        if nxt.get('hours') is not None:
            how.append(_p('how_irr_pump', h=nxt['hours']))
        how += [_p('tip_' + t) for t in nxt['tips']]
        skip = ir['scenarios']['skip']
        if skip.get('first_stress_date'):
            why.append(_p('why_irr_if_skip', date=skip['first_stress_date'],
                          days=skip['stress_days'], risk=skip['yield_risk_pct']))
        tasks.append({
            'key': f"irr:{nxt['date']}", 'kind': 'irrigation',
            'state': 'today' if days_to <= 0 else 'soon', 'date': nxt['date'],
            'title': _p('irr_due', mm=nxt['gross_mm'], m3=nxt['m3_farm']),
            'why': why, 'how': how,
            'answer': {'type': 'irrigation', 'min_date': today.isoformat(),
                       'dose_mm': nxt['gross_mm'], 'only_today': True} if days_to <= 0 else None,
        })
    return tasks


# ------------------------------------------------------------------ #
# Fertiliser
# ------------------------------------------------------------------ #

def _fertilizer_dates(crop_key, sowing, today):
    """(date, schedule item) of the fertiliser applications near today."""
    sched = cm.MANAGEMENT.get(crop_key, {}).get('fertilizer', {}).get('schedule', [])
    out = []
    for item in sched:
        if 'offset_days' in item:
            if sowing is None:
                continue
            out.append((sowing + dt.timedelta(days=item['offset_days']), item))
        elif 'month' in item:
            for year in (today.year - 1, today.year, today.year + 1):
                out.append((dt.date(year, item['month'], 15), item))
    lo = today - dt.timedelta(days=FERT_ASK_DAYS)
    hi = today + dt.timedelta(days=FERT_AHEAD_DAYS)
    return [(d, item) for d, item in out if lo <= d <= hi]


def _fertilizer_timing(day, weather, ir, irrigated, today):
    """Weather-linked HOW for a fertiliser application around `day`."""
    future = {w['date']: w for w in weather or [] if w['date'] >= today}
    near = [future[d] for d in (day + dt.timedelta(days=k) for k in range(-1, 3)) if d in future]
    heavy = next((w for w in near if (w.get('precip') or 0) >= HEAVY_RAIN_MM), None)
    if heavy:
        return [_p('how_fert_heavy_rain', date=heavy['date'].isoformat())]
    light = next((w for w in near if LIGHT_RAIN_MM[0] <= (w.get('precip') or 0) <= LIGHT_RAIN_MM[1]), None)
    if light:
        return [_p('how_fert_light_rain', date=light['date'].isoformat())]
    if irrigated and ir and ir.get('available'):
        ev = next((e for e in ir['events'] if e['date'] >= max(day, today).isoformat()), None)
        if ev and (dt.date.fromisoformat(ev['date']) - max(day, today)).days <= 3:
            return [_p('how_fert_with_water', date=ev['date'])]
    week = [future[d] for d in sorted(future)[:7]]
    if not irrigated and week and sum(w.get('precip') or 0 for w in week) < LIGHT_RAIN_MM[0]:
        return [_p('how_fert_dry')]
    return []


def _fertilizer_how(details):
    """Farm quantity and equivalent product, as HOW lines."""
    how = []
    farm = details.get('farm')
    if farm:
        how.append(_p('how_fert_farm', area=farm['area_ha'], kg=farm['kg'], bags=farm['bags'], bag=farm['bag_kg']))
    alt = details.get('alternative')
    if alt:
        how.append(_p('how_fert_alt', name=alt['name'], rate=alt['rate'], kg=alt['farm_kg'] or '—'))
    return how


def fertilizer_tasks(farm, sowing, answered, weather, ir, today):
    from .product_catalog import fertilizer_details

    tasks = []
    for day, item in _fertilizer_dates(farm.crop, sowing, today):
        key = f"fert:{day.isoformat()}:{_slug(item['product'])}"
        if key in answered:
            continue
        info = {'product': cm.tr(item['product']), 'rate': cm.tr(item['rate']), 'stage': cm.tr(item['stage'])}
        details = fertilizer_details(item['product'], item['rate'], float(farm.area_ha))
        if day < today:
            tasks.append({
                'key': key, 'kind': 'fertilizer', 'state': 'ask', 'date': day.isoformat(),
                'title': _p('fert_ask', **info), 'why': [_p('why_fert_stage', **info)],
                'how': [_p('how_fert_late')] + _fertilizer_how(details),
                'fertilizer': details,
                'answer': {'type': 'yesno', 'kind': 'fertilizer', 'date': day.isoformat()},
            })
        else:
            tasks.append({
                'key': key, 'kind': 'fertilizer', 'state': 'today' if day == today else 'soon',
                'date': day.isoformat(), 'title': _p('fert_due', **info),
                'why': [_p('why_fert_stage', **info)],
                'how': ([_p('how_fert_rate', **info)] + _fertilizer_how(details)
                        + _fertilizer_timing(day, weather, ir, farm.irrigated, today)),
                'fertilizer': details,
                'answer': {'type': 'done', 'kind': 'fertilizer'},
            })
    return tasks


# ------------------------------------------------------------------ #
# Field checks (pests and diseases favoured by the coming weather)
# ------------------------------------------------------------------ #

def scouting_tasks(farm, answered, today, forecast_days):
    threats = cm.MANAGEMENT.get(farm.crop, {}).get('protection', [])
    if not threats or not forecast_days:
        return []
    from .product_catalog import best_spray_day, protection_options

    flags = cm._weather_flags(forecast_days)
    year, week, _ = today.isocalendar()
    spray_day = best_spray_day(forecast_days, today.isoformat())
    spray = _p('how_spray_day', date=spray_day) if spray_day else _p('how_spray_none')
    tasks = []
    for t in threats:
        trig = t.get('trigger')
        if not trig or not flags.get(trig) or today.month not in t['months']:
            continue
        key = f"scout:{_slug(t['name'])}:{year}-{week}"
        if key in answered:
            continue
        tasks.append({
            'key': key, 'kind': 'scouting', 'state': 'soon', 'date': today.isoformat(),
            'title': _p('scout', name=cm.tr(t['name'])),
            'why': [_p('why_scout_' + trig, name=cm.tr(t['name']))],
            'how': [_p('how_scout_watch', text=cm.tr(t['watch'])), _p('how_scout_prevent', text=cm.tr(t['prevent'])),
                    _p('how_scout_control', text=cm.tr(t['control'])), spray],
            'products': protection_options(farm.crop, t['name'], float(farm.area_ha)),
            'answer': {'type': 'checked', 'kind': 'scouting'},
        })
    return tasks


# ------------------------------------------------------------------ #
# Season: sowing date and harvest
# ------------------------------------------------------------------ #

def season_tasks(farm, sowing, sowing_assumed, answered, harvested, ir, today):
    crop = cs.CROPS[farm.crop]
    if crop['perennial']:
        return []
    tasks = []
    if sowing_assumed and sowing <= today + dt.timedelta(days=FERT_AHEAD_DAYS):
        key = f'sow:{sowing.isoformat()}'   # "not yet" waits for the next assumed date
        if key not in answered:
            tasks.append({
                'key': key, 'kind': 'sowing', 'state': 'ask', 'date': sowing.isoformat(),
                'title': _p('sow_ask'), 'why': [_p('why_sow_ask', date=sowing.isoformat())], 'how': [],
                'answer': {'type': 'date', 'kind': 'sowing', 'date': min(sowing, today).isoformat()},
            })
        return tasks
    if harvested or sowing_assumed:
        return tasks
    harvest = sowing + dt.timedelta(days=sum(crop['stages']))
    left = (harvest - today).days
    key = f'harvest:{sowing.isoformat()}'
    if 0 <= left <= HARVEST_AHEAD_DAYS:
        how = [_p('how_harvest_dry')] if farm.crop in irr.DRY_DOWN_CROPS else [_p('how_harvest_pick')]
        tasks.append({
            'key': key, 'kind': 'harvest', 'state': 'today' if left == 0 else 'soon',
            'date': harvest.isoformat(), 'title': _p('harvest_soon', date=harvest.isoformat()),
            'why': [_p('why_harvest_stage')], 'how': how,
            'answer': {'type': 'date', 'kind': 'harvest', 'date': today.isoformat()},
        })
    elif -HARVEST_ASK_DAYS <= left < 0 and key not in answered:
        tasks.append({
            'key': key, 'kind': 'harvest', 'state': 'ask', 'date': harvest.isoformat(),
            'title': _p('harvest_ask'), 'why': [_p('why_harvest_ask', date=harvest.isoformat())],
            'how': [],
            'answer': {'type': 'date', 'kind': 'harvest', 'date': harvest.isoformat()},
        })
    return tasks


# ------------------------------------------------------------------ #
# Entry point
# ------------------------------------------------------------------ #

def render_text(p):
    """One reminder line written out in the request's language, exactly as the
    web page writes it (same msgids, same translations): for the mobile app."""
    from django.utils.formats import date_format
    from django.utils.translation import gettext as _
    from .farm_qa import STAGE_MSG, n
    from .task_text_msgids import TEXTS
    tpl = _(TEXTS.get('tk_' + p['code']) or TEXTS.get(p['code']) or p['code'])
    params = p.get('params') or {}

    def value(match):
        k = match.group(1)
        v = params.get(k)
        if v is None:
            return '—'
        if k in ('pct', 'thr', 'risk'):
            return f'{n(v, 0)}%'
        if k in ('date', 'due', 'since'):
            try:
                return date_format(dt.date.fromisoformat(str(v)), 'j M Y')
            except ValueError:
                return str(v)
        if k == 'stage':
            return _(STAGE_MSG[v]) if v in STAGE_MSG else str(v)
        return n(v) if isinstance(v, (int, float)) else str(v)
    return re.sub(r'\{(\w+)\}', value, tpl)


def with_text(task):
    task['text'] = {'title': render_text(task['title']),
                    'why': [render_text(x) for x in task['why']],
                    'how': [render_text(x) for x in task['how']]}
    return task


def serialize_activity(a):
    return {'id': a.pk, 'kind': a.kind, 'status': a.status, 'date': a.date.isoformat(),
            'amount_mm': float(a.amount_mm) if a.amount_mm is not None else None,
            'task_key': a.task_key, 'note': a.note}


def farm_tasks(farm, today=None):
    """Reminders and questions for one farm, plus the recent activity log."""
    today = today or dt.date.today()
    activities = irr.recent_activities(farm, today)
    log = [serialize_activity(a) for a in activities[:20]]
    if not farm.crop or farm.crop not in cs.CROPS:
        return {'tasks': [], 'activities': log, 'reason': 'no_crop'}

    crop = cs.CROPS[farm.crop]
    sowing, sowing_assumed = None, False
    if not crop['perennial']:
        sowing = farm.sowing_date
        if sowing is None:
            sowing, sowing_assumed = cm.default_sowing_date(farm.crop, today), True
    answered = {a.task_key for a in activities if a.task_key}
    harvested = irr.activity_history(activities, today, sowing)['harvested_on']

    ir = irr.farm_irrigation(farm, today, activities=activities)
    weather = irr.fetch_daily_water(float(farm.centroid_lat), float(farm.centroid_lon))
    forecast_days = []
    try:
        from .farmer_service import farm_weather
        payload = farm_weather(farm).get('forecast') or {}
        forecast_days = payload.get('days') or [] if not payload.get('error') else []
    except Exception:  # forecast is optional for the field-check reminders
        logger.exception('Forecast for farm tasks failed (farm %s)', farm.pk)

    tasks = []
    tasks += irrigation_tasks(ir, today)
    tasks += season_tasks(farm, sowing, sowing_assumed, answered, harvested, ir, today)
    if not sowing_assumed and not harvested:
        tasks += fertilizer_tasks(farm, sowing, answered, weather, ir, today)
        tasks += scouting_tasks(farm, answered, today, forecast_days)
    tasks.sort(key=lambda t: (STATE_ORDER[t['state']], t['date']))
    return {
        'tasks': [with_text(t) for t in tasks],
        'activities': log,
        'irrigation': {k: ir.get(k) for k in ('available', 'now', 'next', 'missed', 'recent',
                                               'scenarios', 'basis')} if ir.get('available') else None,
    }
