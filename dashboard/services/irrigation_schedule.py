"""Irrigation timing for a farmer's parcel: when to water and how much.

FAO-56 (Allen et al. 1998, chapter 8) daily root-zone soil-water balance:

    Dr(i) = Dr(i-1) - Peff(i) - In(i) + ETc(i)        0 <= Dr <= TAW
    ETc   = Kc * ET0
    TAW   = AWC * Zr          RAW = p * TAW,  p = p_tab + 0.04 (5 - ETc)

Water is due when the depletion Dr reaches the method's trigger (a share of
RAW); the net dose refills the root zone to field capacity, and the gross dose
adds the losses of the irrigation method (net / efficiency).

Inputs for one farm:
  soil     AWC (mm of water per m of soil) from the parcel's SoilGrids texture
           (field capacity - wilting point), else the region's soil, else the
           texture-class default used by crop_suitability
  crop     Kc curve, stage lengths, rooting depth and p from
           crop_suitability.CROPS (FAO-56 tables 11, 12 and 22); roots of
           annual crops grow from ROOT_MIN_M at sowing to full depth at the
           end of the development stage (FAO-56 eq. 8-1, linearised)
  weather  Open-Meteo daily rain and FAO-56 ET0 at the parcel: the last
           PAST_DAYS days estimate how much water is in the soil today, the
           next FORECAST_DAYS days plan the waterings
  method   drip / sprinkler / surface: application efficiency (typical
           values from FAO Irrigation Water Management manual 4, Brouwer et
           al. 1989) and how far the soil may dry before watering
  history  the farmer's watering log (FarmActivity: date and amount), else
           the last irrigation date, when known. Once the farmer reports, past
           days follow only what he reported: a watering that fell due and was
           not reported is a missed watering. The farmer is asked about it, and
           the plan, stress days and harvest risk change with his answers.
  climate  the region's monthly climatology for the months after the forecast

1 mm of water on 1 ha = 10 m3.

The API returns numbers and codes only; the farmer page words them in the
farmer's language.
"""
import calendar
import datetime as dt
import logging

from django.core.cache import cache

from . import crop_suitability as cs

logger = logging.getLogger(__name__)

PAST_DAYS = 60          # spin-up: enough to forget the assumed starting state
FORECAST_DAYS = 16      # Open-Meteo maximum
SHOWN_PAST_DAYS = 7     # history shown on the page
WEATHER_CACHE_TTL = 60 * 60
ROOT_MIN_M = 0.15       # seed / transplant rooting depth
OUTLOOK_MONTHS = 3

# trigger: water when depletion reaches this share of RAW. Drip keeps the
# soil moist with small frequent doses; surface irrigation applies large
# doses, so it waits for the whole readily available water to be used.
METHODS = {
    'drip': {'efficiency': 0.90, 'trigger': 0.35},
    'sprinkler': {'efficiency': 0.75, 'trigger': 0.85},
    'surface': {'efficiency': 0.60, 'trigger': 1.00},
}
DEFAULT_METHOD = 'sprinkler'

# Annual crops that are left to dry before harvest (ripening grain, pods,
# bulbs, tuber skin set). Tomato and pepper are picked over weeks: no stop.
DRY_DOWN_CROPS = {'wheat', 'barley', 'oats', 'faba_bean', 'lentil', 'garlic', 'potato'}
DRY_DOWN_DAYS = 14

# Rain-aware postponing: skip a due watering when the next RAIN_LOOKAHEAD
# days should bring at least RAIN_COVER_SHARE of the deficit, unless the
# crop is already short of water.
RAIN_LOOKAHEAD = 2
RAIN_COVER_SHARE = 0.6
RAIN_MIN_PROB = 50

WINDY_KMH = 20.0        # sprinklers drift and lose water above this
HOT_C = 35.0

RECENT_DAYS = 30        # window for "what the crop went through lately"
# Bases where past days follow what the farmer told us (not an assumed plan).
REPORTED_BASES = ('last_irrigation', 'reported_dry', 'rain_only')


# ------------------------------------------------------------------ #
# Weather
# ------------------------------------------------------------------ #

def fetch_daily_water(lat, lon, past_days=PAST_DAYS, forecast_days=FORECAST_DAYS):
    """Daily rain / ET0 / Tmax / wind / rain probability at a point, past and
    forecast, from Open-Meteo (or the backup sources in weather_fallback when
    Open-Meteo refuses). Returns a list of dicts or None on failure."""
    from .weather_forecast import open_meteo_get

    key = f'irrigation:wx:{lat:.3f}:{lon:.3f}:{past_days}:{forecast_days}'
    hit = cache.get(key)
    if hit is not None:
        return hit
    params = {
        'latitude': round(lat, 4), 'longitude': round(lon, 4),
        'daily': 'precipitation_sum,et0_fao_evapotranspiration,temperature_2m_max,'
                 'wind_speed_10m_max,precipitation_probability_max',
        'timezone': 'auto', 'past_days': past_days, 'forecast_days': forecast_days,
    }
    try:
        daily = open_meteo_get(params).get('daily') or {}
    except Exception as exc:  # network, HTTP, JSON (already retried once)
        logger.warning('Open-Meteo irrigation weather failed at (%s, %s): %r', lat, lon, exc)
        # Backup: NASA POWER for the past, MET Norway for the forecast.
        from .weather_fallback import daily_water
        try:
            rows = daily_water(lat, lon, past_days, forecast_days)
        except Exception as exc2:
            logger.warning('Backup irrigation weather failed at (%s, %s): %r', lat, lon, exc2)
            return None
        cache.set(key, rows, WEATHER_CACHE_TTL)
        return rows

    def col(name, i):
        values = daily.get(name) or []
        return values[i] if i < len(values) else None

    rows = []
    for i, iso in enumerate(daily.get('time') or []):
        try:
            day = dt.date.fromisoformat(iso)
        except ValueError:
            continue
        rows.append({'date': day, 'precip': col('precipitation_sum', i),
                     'et0': col('et0_fao_evapotranspiration', i),
                     'tmax': col('temperature_2m_max', i),
                     'wind': col('wind_speed_10m_max', i),
                     'precip_prob': col('precipitation_probability_max', i)})
    if not rows:
        return None
    cache.set(key, rows, WEATHER_CACHE_TTL)
    return rows


# ------------------------------------------------------------------ #
# Crop and soil
# ------------------------------------------------------------------ #

def season_bounds(crop_key, sowing_date):
    """(sowing, harvest) for an annual crop, (None, None) for a perennial."""
    crop = cs.CROPS[crop_key]
    if crop['perennial'] or sowing_date is None:
        return None, None
    return sowing_date, sowing_date + dt.timedelta(days=sum(crop['stages']))


def crop_state(crop_key, sowing_date, day):
    """Kc, rooting depth (m), p and stage code of the crop on a date.

    Outside an annual crop's season the field is bare: Kc_ini stands for soil
    evaporation over a shallow layer and the stage is None.
    """
    crop = cs.CROPS[crop_key]
    if crop['perennial']:
        return {'kc': crop['kc'][day.month - 1], 'zr': crop['root_m'], 'p': crop['p'],
                'stage': 'perennial', 'days_to_harvest': None}
    l_ini, l_dev, l_mid, l_late = crop['stages']
    total = l_ini + l_dev + l_mid + l_late
    t = (day - sowing_date).days if sowing_date else -1
    if t < 0 or t >= total:
        return {'kc': crop['kc'][0], 'zr': ROOT_MIN_M, 'p': crop['p'], 'stage': None,
                'days_to_harvest': None}
    zr = ROOT_MIN_M + (crop['root_m'] - ROOT_MIN_M) * min(t / float(l_ini + l_dev), 1.0)
    stage = ('initial' if t < l_ini else 'development' if t < l_ini + l_dev
             else 'mid' if t < l_ini + l_dev + l_mid else 'late')
    return {'kc': cs.annual_kc(t, crop['stages'], crop['kc']), 'zr': zr, 'p': crop['p'],
            'stage': stage, 'days_to_harvest': total - t}


def soil_awc(farm_soil, region=None):
    """(AWC mm/m, texture class, source) for the parcel."""
    from .farmer_service import suitability_soil

    soil, source = suitability_soil(farm_soil), 'parcel'
    if not soil and region is not None:
        try:
            soil, source = cs.region_soil(region), 'region'
        except Exception:  # region soil is optional
            logger.exception('Region soil failed for %s', region)
            soil = None
    soil = soil or {}
    tex = soil.get('texture_class') or cs.texture_class(soil.get('sand_pct'), soil.get('clay_pct'))
    awc = soil.get('awc_mm_per_m')
    if awc:
        return float(awc), tex, source
    return cs.AWC_MM_PER_M.get(tex, 150.0), tex, (source + '_texture' if tex else 'default')


def _peff_daily(precip, et0):
    """FAO-56: light rain (< 0.2 ET0) evaporates from the surface before it
    reaches the roots. Heavier rain counts in full; whatever overfills the
    root zone drains away in the balance itself."""
    p = float(precip or 0.0)
    return p if p >= 0.2 * float(et0 or 0.0) and p > 0 else 0.0


def _raw(taw, p_tab, etc):
    p = min(max(p_tab + 0.04 * (5.0 - etc), 0.1), 0.8)
    return p * taw


# ------------------------------------------------------------------ #
# Daily balance and schedule
# ------------------------------------------------------------------ #

def build_schedule(crop_key, weather, today, *, sowing_date=None, awc_mm_per_m=150.0,
                   method=DEFAULT_METHOD, irrigated=True, last_irrigation=None,
                   area_ha=1.0, flow_m3h=None, waterings=None, answered_through=None,
                   reported_from=None, harvested_on=None, clim=None):
    """Simulate the root zone over `weather` (past and forecast rows sorted
    by date) and return the plan. Pure: no I/O, so it is easy to test.

    waterings         {date: gross mm or None} the farmer reported (None =
                      "enough to refill the soil")
    answered_through  last day the farmer told us about watering, done or
                      not: missed waterings up to it are not asked again
    reported_from     first day of his reports; before it (and before his
                      first logged watering) the plan is assumed followed
    harvested_on      annual crop harvested early: no crop after that day
    """
    crop = cs.CROPS[crop_key]
    m = METHODS.get(method) or METHODS[DEFAULT_METHOD]
    eff, trigger = m['efficiency'], m['trigger']
    sowing, harvest = season_bounds(crop_key, sowing_date)
    if crop['perennial'] or not harvested_on or (sowing and harvested_on < sowing):
        harvested_on = None
    elif harvest is None or harvested_on < harvest:
        harvest = harvested_on
    rows = [w for w in weather if w.get('et0') is not None]
    if not rows:
        return None

    start = rows[0]['date']
    logs = {d: a for d, a in (waterings or {}).items() if start <= d <= today}
    if last_irrigation and start <= last_irrigation <= today:
        logs.setdefault(last_irrigation, None)
    if logs:
        basis = 'last_irrigation'
    elif not irrigated:
        basis = 'rain_only'
    elif answered_through and start <= answered_through <= today:
        basis = 'reported_dry'      # the farmer told us he did not water
    elif sowing and start <= sowing <= today:
        basis = 'sowing'
    else:
        basis = 'assumed_schedule'

    # The farmer's own history starts with his first report; nothing is
    # known before it, so those days keep the assumed plan.
    firsts = [d for d in (*logs, reported_from, answered_through) if d and start <= d <= today]
    known_from = min(firsts) if firsts and basis in ('last_irrigation', 'reported_dry') else start

    sim = dict(crop_key=crop_key, rows=rows, today=today, sowing=sowing, awc=awc_mm_per_m,
               method=method, eff=eff, trigger=trigger, irrigated=irrigated, basis=basis,
               logs=logs, known_from=known_from, harvested_on=harvested_on,
               area_ha=area_ha, flow_m3h=flow_m3h)
    days, events, current, missed = _simulate(plan_future=True, **sim)
    if current is None:
        return None
    # When would the crop run short if nobody waters from today on?
    dry_days, _, _, _ = _simulate(plan_future=False, **sim)
    first_stress = next((d['date'] for d in dry_days if not d['past'] and d['stressed']), None)

    if missed and irrigated:
        due = dt.date.fromisoformat(missed['due_date'])
        ask_from = max(due, answered_through + dt.timedelta(days=1)) if answered_through else due
        missed.update({
            'days_late': (today - due).days,
            'ask': ask_from < today,          # a past day nobody answered for
            'ask_from': ask_from.isoformat(),
            'reported_skipped': bool(answered_through and answered_through >= due),
        })
    else:
        missed = None

    future = [d for d in days if not d['past']]
    shown = [d for d in days if d['past']][-SHOWN_PAST_DAYS:] + future
    in_season_future = [d for d in future if d['stage']]
    totals = {
        'days': len(future),
        'etc_mm': round(sum(d['etc'] for d in in_season_future), 0),
        'peff_mm': round(sum(d['peff'] for d in in_season_future), 0),
        'net_mm': round(sum(e['net_mm'] for e in events), 0),
    }
    totals['gross_mm'] = round(totals['net_mm'] / eff, 0)
    totals['m3_per_ha'] = round(totals['gross_mm'] * 10)
    totals['m3_farm'] = round(totals['gross_mm'] * 10 * area_ha)

    season_etc = _season_etc(crop_key, sowing, rows, clim=clim)
    ky = crop.get('ky') or 1.0
    dry_future = [d for d in dry_days if not d['past']]
    scenarios = {
        'follow': {**_water_use(future, ky, season_etc), 'waterings': len(events),
                   'gross_mm': totals['gross_mm'], 'm3_farm': totals['m3_farm']},
        'skip': {**_water_use(dry_future, ky, season_etc), 'waterings': 0,
                 'first_stress_date': first_stress},
    }
    recent = None
    if basis in REPORTED_BASES:
        since = max(today - dt.timedelta(days=RECENT_DAYS), known_from).isoformat()
        window = [d for d in days if d['past'] and d['date'] >= since]
        recent = _water_use(window, ky, season_etc)
        recent['days'] = len(window)

    return {
        'basis': basis,
        'method': method if method in METHODS else DEFAULT_METHOD,
        'efficiency': eff,
        'trigger_share_of_raw': trigger,
        'season': {
            'perennial': crop['perennial'],
            'sowing_date': sowing.isoformat() if sowing else None,
            'harvest_date': harvest.isoformat() if harvest else None,
            'harvested_on': harvested_on.isoformat() if harvested_on else None,
            'state': _season_state(crop, sowing, harvest, today),
        },
        'now': _status(current, events, today, awc_mm_per_m),
        'next': events[0] if events else None,
        'events': events,
        'days': shown,
        'totals': totals,
        'first_stress_date': first_stress,
        'typical_interval_days': _interval(current, future),
        'logged': [{'date': d.isoformat(), 'gross_mm': a} for d, a in sorted(logs.items())],
        'missed': missed,
        'recent': recent,
        'scenarios': scenarios,
    }


def _water_use(days, ky, season_etc):
    """Stress days and water shortfall over in-season days, and the share of
    the harvest it costs (FAO-33: 1 - Ya/Ym = Ky (1 - ETa/ETm), with the
    deficit spread over the whole season's ETm)."""
    grow = [d for d in days if d['stage']]
    etc = sum(d['etc'] for d in grow)
    eta = sum(d['eta'] for d in grow)
    deficit = max(etc - eta, 0.0)
    return {
        'stress_days': sum(1 for d in grow if d['stressed']),
        'shortfall_pct': round(100 * deficit / etc) if etc else 0,
        'deficit_mm': round(deficit),
        'yield_risk_pct': (min(100, round(100 * ky * deficit / season_etc))
                           if season_etc else None),
    }


def _season_etc(crop_key, sowing, rows, clim=None):
    """Crop water use over a whole season (annual) or year (perennial), mm.
    Uses the monthly climatology ET0 when given, else the mean ET0 of the
    weather rows (a rough scale for the harvest-risk share only)."""
    crop = cs.CROPS[crop_key]
    et0_rows = [float(w['et0']) for w in rows if w.get('et0') is not None]
    mean_et0 = sum(et0_rows) / len(et0_rows) if et0_rows else 0.0

    def et0_on(day):
        c = clim.get(day.month) if clim else None
        return c['et0'] if c else mean_et0

    if crop['perennial']:
        start = dt.date(rows[0]['date'].year, 1, 1) if rows else dt.date.today()
        return sum(crop['kc'][(start + dt.timedelta(days=k)).month - 1] *
                   et0_on(start + dt.timedelta(days=k)) for k in range(365))
    if sowing is None:
        return 0.0
    return sum(crop_state(crop_key, sowing, sowing + dt.timedelta(days=t))['kc'] *
               et0_on(sowing + dt.timedelta(days=t)) for t in range(sum(crop['stages'])))


def _simulate(*, crop_key, rows, today, sowing, awc, method, eff, trigger, irrigated, basis,
              logs, known_from, harvested_on, area_ha, flow_m3h, plan_future):
    """One pass of the daily balance. Past days follow what is known (or
    assumed) about the farm; future days follow the plan when plan_future.

    Also returns the watering that fell due in the past and was never
    reported (only when past days follow the farmer's own reports): the
    first day of the current spell where the soil sat at or below the
    watering level."""
    depl, days, events = 0.0, [], []
    current = pending = None
    awc_mm_per_m = awc
    for i, w in enumerate(rows):
        day = w['date']
        past = day < today
        st = crop_state(crop_key, sowing, day)
        if harvested_on and day >= harvested_on:
            st = {**st, 'stage': None, 'days_to_harvest': None}
        in_season = st['stage'] is not None
        et0 = float(w['et0'])
        etc = st['kc'] * et0
        taw = cs_awc_taw(awc_mm_per_m, st['zr'])
        raw = _raw(taw, st['p'], etc)
        peff = _peff_daily(w.get('precip'), et0)
        depl = min(max(depl - peff, 0.0), taw)  # root growth: new soil starts at FC

        logged_mm = 0.0
        if day in logs:
            gross = logs[day]
            logged_mm = depl if gross is None else min(float(gross) * eff, depl)
            depl -= logged_mm
        if day == today:
            current = {'depletion_mm': depl, 'taw_mm': taw, 'raw_mm': raw,
                       'trigger_mm': trigger * raw, 'stage': st['stage'],
                       'root_depth_m': st['zr'], 'kc': st['kc']}

        # Who decides on waterings on this day?
        if past:
            plan = (irrigated and basis == 'assumed_schedule') or (
                irrigated and basis == 'sowing' and day >= sowing) or (
                irrigated and day < known_from)
        else:
            plan = plan_future
        dry_down = (crop_key in DRY_DOWN_CROPS and st['days_to_harvest'] is not None
                    and st['days_to_harvest'] <= DRY_DOWN_DAYS)
        due = in_season and not dry_down and depl >= trigger * raw and depl > 0.5

        # A past day the farmer reports for, at the watering level, and he
        # did not report a watering: remember when this dry spell became due.
        if past and not plan and irrigated and basis in REPORTED_BASES:
            if due:
                pending = pending or {'due_date': day.isoformat(), 'dose_net_mm': round(depl, 1),
                                      'stress_since': None}
                if depl > raw and not pending['stress_since']:
                    pending['stress_since'] = day.isoformat()
            else:
                pending = None

        irr = 0.0
        postponed = False
        if plan and due:
            ahead = rows[i + 1:i + 1 + RAIN_LOOKAHEAD]
            rain_ahead = sum(_peff_daily(a.get('precip'), a.get('et0')) for a in ahead
                             if (a.get('precip_prob') is None or a['precip_prob'] >= RAIN_MIN_PROB))
            if depl < raw and rain_ahead >= RAIN_COVER_SHARE * depl:
                postponed = True
            else:
                irr = depl
                depl = 0.0
                if not past:
                    events.append(_event(day, irr, eff, area_ha, flow_m3h, st, w, method,
                                         stressed=(irr > raw + etc),
                                         split=(method != 'surface' and irr > 1.5 * raw)))

        ks = 1.0 if depl <= raw else max((taw - depl) / (taw - raw), 0.0) if taw > raw else 0.0
        depl = min(depl + ks * etc, taw)
        days.append({
            'date': day.isoformat(), 'past': past, 'today': day == today,
            'stage': st['stage'], 'kc': round(st['kc'], 2),
            'et0': round(et0, 1), 'etc': round(etc, 1), 'eta': round(ks * etc, 2),
            'rain': round(float(w.get('precip') or 0.0), 1), 'peff': round(peff, 1),
            'irrigation_mm': round(irr + logged_mm, 1), 'logged': day in logs,
            'postponed': postponed, 'dry_down': dry_down,
            'stressed': ks < 1.0 and in_season,
            'available_pct': round(100 * (1 - depl / taw), 0) if taw else None,
            'threshold_pct': round(100 * (1 - trigger * raw / taw), 0) if taw else None,
        })
    return days, events, current, pending


def cs_awc_taw(awc_mm_per_m, zr):
    return float(awc_mm_per_m) * float(zr)


def _season_state(crop, sowing, harvest, today):
    if crop['perennial']:
        return 'perennial'
    if sowing is None:
        return 'no_sowing_date'
    if today < sowing:
        return 'not_sown'
    if today >= harvest:
        return 'harvested'
    return 'growing'


def _status(cur, events, today, awc):
    taw, raw, depl = cur['taw_mm'], cur['raw_mm'], cur['depletion_mm']
    nxt = events[0] if events else None
    days_to_next = (dt.date.fromisoformat(nxt['date']) - today).days if nxt else None
    if cur['stage'] is None:
        code = 'no_crop'
    elif days_to_next == 0:
        code = 'now'
    elif depl > raw:
        code = 'stress'
    elif days_to_next is not None and days_to_next <= 2:
        code = 'soon'
    else:
        code = 'ok'
    return {
        'code': code,
        'stage': cur['stage'],
        'kc': round(cur['kc'], 2),
        'root_depth_m': round(cur['root_depth_m'], 2),
        'awc_mm_per_m': round(awc, 0),
        'taw_mm': round(taw, 0),
        'raw_mm': round(raw, 0),
        'trigger_mm': round(cur['trigger_mm'], 0),
        'depletion_mm': round(depl, 0),
        'available_pct': round(100 * (1 - depl / taw), 0) if taw else None,
        'threshold_pct': round(100 * (1 - cur['trigger_mm'] / taw), 0) if taw else None,
        'stress_pct': round(100 * (1 - raw / taw), 0) if taw else None,
        'days_to_next': days_to_next,
    }


def _interval(cur, future):
    """Typical days between waterings at the coming two weeks' demand."""
    net_use = [max(d['etc'] - d['peff'], 0.0) for d in future if d['stage']]
    if not net_use or not sum(net_use):
        return None
    per_day = sum(net_use) / len(net_use)
    return max(1, round(cur['trigger_mm'] / per_day)) if cur['trigger_mm'] else None


def _event(day, net, eff, area_ha, flow_m3h, st, w, method, stressed, split=False):
    gross = net / eff
    m3_farm = gross * 10 * area_ha
    tips = ['early_morning']
    if method == 'sprinkler' and (w.get('wind') or 0) >= WINDY_KMH:
        tips.append('windy')
    if (w.get('tmax') or 0) >= HOT_C:
        tips.append('hot')
    if stressed:
        tips.append('overdue')
    if split:   # catch-up after a missed watering: the soil cannot take it at once
        tips.append('split_dose')
    if method == 'surface' and net < 25:
        tips.append('light_surface_dose')
    return {
        'date': day.isoformat(),
        'stage': st['stage'],
        'net_mm': round(net, 1),
        'gross_mm': round(gross, 1),
        'litres_per_m2': round(gross, 1),
        'm3_per_ha': round(gross * 10),
        'm3_farm': round(m3_farm),
        'hours': round(m3_farm / flow_m3h, 1) if flow_m3h else None,
        'tmax': w.get('tmax'),
        'wind': w.get('wind'),
        'tips': tips,
    }


# ------------------------------------------------------------------ #
# Months after the forecast (climatology)
# ------------------------------------------------------------------ #

def monthly_outlook(crop_key, clim, today, *, sowing_date=None, awc_mm_per_m=150.0,
                    method=DEFAULT_METHOD, area_ha=1.0, months=OUTLOOK_MONTHS):
    """Average water need for the next months and for the rest of the
    season, from the region's monthly climatology (ET0 mm/day, rain mm)."""
    if not clim:
        return None
    m = METHODS.get(method) or METHODS[DEFAULT_METHOD]
    eff, trigger = m['efficiency'], m['trigger']
    sowing, harvest = season_bounds(crop_key, sowing_date)
    crop = cs.CROPS[crop_key]

    def month_need(year, month):
        c = clim.get(month)
        if not c:
            return None
        ndays = calendar.monthrange(year, month)[1]
        peff_day = cs.effective_rain(c['rain_mean']) / ndays
        etc = net = 0.0
        doses, growing = [], 0
        for d in range(1, ndays + 1):
            day = dt.date(year, month, d)
            st = crop_state(crop_key, sowing, day)
            if st['stage'] is None:
                continue
            growing += 1
            e = st['kc'] * c['et0']
            etc += e
            net += max(e - peff_day, 0.0)
            doses.append(trigger * _raw(cs_awc_taw(awc_mm_per_m, st['zr']), st['p'], e))
        if not growing:
            return {'month': month, 'year': year, 'growing_days': 0}
        dose = sum(doses) / len(doses)
        gross = net / eff
        return {
            'month': month, 'year': year, 'growing_days': growing,
            'et0_mm_day': round(c['et0'], 1),
            'etc_mm': round(etc), 'rain_mm': round(c['rain_mean']),
            'peff_mm': round(peff_day * growing),
            'net_mm': round(net), 'gross_mm': round(gross),
            'm3_per_ha': round(gross * 10), 'm3_farm': round(gross * 10 * area_ha),
            'waterings': round(net / dose) if dose and net else 0,
            'interval_days': (max(1, round(dose / (net / growing))) if net else None),
            'dose_gross_mm': round(dose / eff, 1) if net else None,
        }

    def add_month(y, mo, k):
        mo2 = mo + k
        return y + (mo2 - 1) // 12, (mo2 - 1) % 12 + 1

    rows = [r for r in (month_need(*add_month(today.year, today.month, k))
                        for k in range(1, months + 1)) if r]

    # Rest of the season: current month's remainder is covered by the
    # forecast, so count from next month up to harvest (12 months at most).
    season_gross = 0.0
    if crop['perennial'] or harvest:
        for k in range(1, 13):
            y, mo = add_month(today.year, today.month, k)
            if harvest and dt.date(y, mo, 1) > harvest:
                break
            r = month_need(y, mo)
            if r and r.get('gross_mm'):
                season_gross += r['gross_mm']
    return {'months': rows, 'rest_of_season_gross_mm': round(season_gross),
            'rest_of_season_m3_farm': round(season_gross * 10 * area_ha),
            'climate_period': clim.get('_meta', {}).get('years')}


# ------------------------------------------------------------------ #
# Farm entry point
# ------------------------------------------------------------------ #

def recent_activities(farm, today, days=PAST_DAYS + 120):
    """The farm's reported activities over the simulated window and the
    current season (sowing / harvest answers can be months old)."""
    if getattr(farm, 'pk', None) is None:
        return []
    return list(farm.activities.filter(date__gte=today - dt.timedelta(days=days)))


def activity_history(activities, today, sowing=None):
    """What the farmer reported, as build_schedule keyword arguments:
    waterings {date: gross mm or None}, answered_through, reported_from,
    harvested_on."""
    waterings, answered, first, harvested = {}, None, None, None
    for a in activities:
        if a.date > today:
            continue
        if a.kind == 'irrigation':
            answered = max(answered, a.date) if answered else a.date
            first = min(first, a.date) if first else a.date
            if a.status == 'done':
                prev = waterings.get(a.date, 0.0)
                amount = float(a.amount_mm) if a.amount_mm is not None else None
                waterings[a.date] = None if prev is None or amount is None else prev + amount
        elif a.kind == 'harvest' and a.status == 'done' and (sowing is None or a.date >= sowing):
            harvested = max(harvested, a.date) if harvested else a.date
    return {'waterings': waterings, 'answered_through': answered, 'reported_from': first,
            'harvested_on': harvested}


def farm_irrigation(farm, today=None, activities=None):
    """Everything the farmer page's Irrigation tab shows for one farm.
    `activities`: the farm's FarmActivity rows (queried when omitted)."""
    today = today or dt.date.today()
    if not farm.crop or farm.crop not in cs.CROPS:
        return {'available': False, 'reason': 'no_crop'}
    if activities is None:
        activities = recent_activities(farm, today)

    from .crop_management import default_sowing_date
    crop = cs.CROPS[farm.crop]
    sowing = None
    sowing_assumed = False
    if not crop['perennial']:
        sowing = farm.sowing_date
        if sowing is None:
            sowing, sowing_assumed = default_sowing_date(farm.crop, today), True

    method = farm.irrigation_method if farm.irrigation_method in METHODS else DEFAULT_METHOD
    awc, texture, soil_source = soil_awc(farm.soil, farm.region)
    area = float(farm.area_ha)
    flow = float(farm.irrigation_flow_m3h) if farm.irrigation_flow_m3h else None
    common = {
        'crop': farm.crop,
        'method': method,
        'method_set': farm.irrigation_method in METHODS,
        'efficiency': METHODS[method]['efficiency'],
        'irrigated': farm.irrigated,
        'area_ha': area,
        'flow_m3h': flow,
        'last_irrigation': farm.last_irrigation_date.isoformat() if farm.last_irrigation_date else None,
        'sowing_assumed': sowing_assumed,
        'soil': {'awc_mm_per_m': round(awc), 'texture_class': texture, 'source': soil_source},
        'water_supply_mm': float(farm.water_supply_mm) if farm.water_supply_mm is not None else None,
    }

    clim = None
    if farm.region is not None:
        try:
            clim = cs.region_climatology(farm.region)
        except Exception:
            logger.exception('Climatology failed for %s', farm.region)
    outlook = monthly_outlook(farm.crop, clim, today, sowing_date=sowing, awc_mm_per_m=awc,
                              method=method, area_ha=area)

    history = activity_history(activities, today, sowing)
    weather = fetch_daily_water(float(farm.centroid_lat), float(farm.centroid_lon))
    plan = build_schedule(
        farm.crop, weather or [], today, sowing_date=sowing, awc_mm_per_m=awc, method=method,
        irrigated=farm.irrigated, last_irrigation=farm.last_irrigation_date,
        area_ha=area, flow_m3h=flow, clim=clim, **history) if weather else None
    if plan is None:
        return {'available': False, 'reason': 'weather', 'outlook': outlook, **common}
    return {'available': True, **common, **plan, 'outlook': outlook,
            'sources': {'weather': 'Open-Meteo (observed + forecast, FAO-56 ET0)',
                        'crop': 'FAO-56 Kc, rooting depth and depletion fraction',
                        'soil': 'ISRIC SoilGrids 2.0' if soil_source == 'parcel' else soil_source}}
