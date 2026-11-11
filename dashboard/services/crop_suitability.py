"""Crop suitability ranking for a region (rainfed or irrigated).

Each crop is scored on independent, explainable factors and the overall
score follows the EcoCrop / FAO land-evaluation "limiting factor" rule:
the worst climate/soil factor caps the result, then water multiplies it.

  temperature  monthly mean temperature vs the crop's optimal / absolute
               range (trapezoid; season mean for annuals, worst month for
               perennials)
  soil pH      trapezoid on the 0-30 cm pH
  texture      1.0 inside the preferred texture classes, 0.75 outside
  salinity     Maas-Hoffman relative yield, only when ECe is known
  water        FAO-56 single-Kc daily soil-water balance -> ETa/ETc ->
               FAO-33 relative yield 1 - Ky(1 - ETa/ETc)  (rainfed), or
               the share of the net irrigation need that the declared
               supply covers (irrigated)

Sources for the crop table (all values are defaults to be reviewed by a
local agronomist, not calibrated on Tunisian trials):
  Kc, stage lengths, root depth, depletion p: FAO-56 Tables 11, 12, 22
  Ky: FAO-33 (Doorenbos & Kassam 1979); entries marked approx. are not
      in FAO-33 and were set by analogy
  temperature / pH ranges: FAO EcoCrop (via GAEZ), widened for winter
      cereals whose Mediterranean season runs through 10-12 C months
  salinity threshold / slope: Maas & Hoffman (1977), FAO-29 Table 4
  planting months: Tunisian / northern Moroccan calendar (crop_kb.py)
"""
import calendar
import datetime as dt
import logging

import numpy as np

logger = logging.getLogger(__name__)

# kc: (ini, mid, end) for annuals; 12 monthly values for perennials
# stages: FAO-56 (L_ini, L_dev, L_mid, L_late) days
# temp / ph: (abs_min, opt_min, opt_max, abs_max)
# ece: (threshold dS/m, % yield loss per dS/m) or None if not tabulated
CROPS = {
    'wheat': {
        'names': {'en': 'durum wheat', 'fr': 'blé dur', 'ar': 'القمح الصلب'},
        'perennial': False, 'planting_months': [11, 12],
        'kc': (0.3, 1.15, 0.3), 'stages': (30, 60, 60, 40),
        'root_m': 1.2, 'p': 0.55, 'ky': 1.05,
        'temp': (3, 10, 24, 32), 'ph': (5.0, 6.0, 7.8, 8.5),
        'texture': {'medium', 'heavy'}, 'ece': (5.9, 3.8),
    },
    'barley': {
        'names': {'en': 'barley', 'fr': 'orge', 'ar': 'الشعير'},
        'perennial': False, 'planting_months': [11, 12],
        'kc': (0.3, 1.15, 0.25), 'stages': (25, 50, 50, 30),
        'root_m': 1.2, 'p': 0.55, 'ky': 1.0,  # Ky approx.
        'temp': (2, 10, 24, 32), 'ph': (5.0, 6.0, 8.3, 9.0),
        'texture': {'light', 'medium', 'heavy'}, 'ece': (8.0, 5.0),
    },
    'oats': {
        'names': {'en': 'oats', 'fr': 'avoine', 'ar': 'الخرطال'},
        'perennial': False, 'planting_months': [10, 11, 12],
        'kc': (0.3, 1.15, 0.25), 'stages': (25, 50, 50, 30),
        'root_m': 1.0, 'p': 0.55, 'ky': 1.0,  # Ky approx.
        'temp': (3, 10, 22, 28), 'ph': (4.5, 5.5, 7.5, 8.3),
        'texture': {'medium', 'heavy'}, 'ece': None,
    },
    'faba_bean': {
        'names': {'en': 'faba bean', 'fr': 'fève', 'ar': 'الفول'},
        'perennial': False, 'planting_months': [10, 11, 12],
        'kc': (0.5, 1.15, 0.3), 'stages': (30, 45, 60, 35),
        'root_m': 0.6, 'p': 0.45, 'ky': 1.15,  # Ky approx. (bean)
        'temp': (4, 10, 22, 28), 'ph': (4.5, 6.2, 8.0, 8.5),
        'texture': {'medium', 'heavy'}, 'ece': (1.6, 9.6),
    },
    'lentil': {
        'names': {'en': 'lentil', 'fr': 'lentille', 'ar': 'العدس'},
        'perennial': False, 'planting_months': [11, 12],
        'kc': (0.4, 1.1, 0.3), 'stages': (25, 35, 70, 40),
        'root_m': 0.7, 'p': 0.5, 'ky': 1.15,  # Ky approx. (bean)
        'temp': (4, 12, 24, 30), 'ph': (4.5, 6.0, 8.0, 8.5),
        'texture': {'medium'}, 'ece': None,
    },
    'garlic': {
        'names': {'en': 'garlic', 'fr': 'ail', 'ar': 'الثوم'},
        'perennial': False, 'planting_months': [10, 11],
        'kc': (0.7, 1.0, 0.7), 'stages': (20, 40, 70, 30),
        'root_m': 0.4, 'p': 0.3, 'ky': 1.1,  # Ky approx. (onion)
        'temp': (4, 12, 24, 30), 'ph': (4.5, 6.0, 7.5, 8.3),
        'texture': {'light', 'medium'}, 'ece': (3.9, 14.3),
    },
    'potato': {
        'names': {'en': 'potato', 'fr': 'pomme de terre', 'ar': 'البطاطا'},
        'perennial': False, 'planting_months': [1, 2, 8, 9],
        'kc': (0.5, 1.15, 0.75), 'stages': (25, 30, 45, 30),
        'root_m': 0.5, 'p': 0.35, 'ky': 1.1,
        # pH widened to 7.5 opt: grown widely on Tunisian calcareous soils
        # (common scab risk rises above ~7.5)
        'temp': (6, 14, 22, 28), 'ph': (4.5, 5.0, 7.5, 8.5),
        'texture': {'light', 'medium'}, 'ece': (1.7, 12.0),
    },
    'tomato': {
        'names': {'en': 'tomato', 'fr': 'tomate', 'ar': 'الطماطم'},
        'perennial': False, 'planting_months': [2, 3, 8, 9],
        'kc': (0.6, 1.15, 0.8), 'stages': (30, 40, 45, 30),
        'root_m': 1.0, 'p': 0.4, 'ky': 1.05,
        'temp': (10, 18, 28, 34), 'ph': (4.5, 5.5, 7.5, 8.3),
        'texture': {'light', 'medium'}, 'ece': (2.5, 9.9),
    },
    'pepper': {
        'names': {'en': 'pepper', 'fr': 'piment', 'ar': 'الفلفل'},
        'perennial': False, 'planting_months': [3, 4],
        'kc': (0.6, 1.05, 0.9), 'stages': (25, 35, 40, 20),
        'root_m': 0.7, 'p': 0.3, 'ky': 1.1,
        'temp': (12, 18, 30, 35), 'ph': (4.5, 5.5, 7.0, 8.3),
        'texture': {'light', 'medium'}, 'ece': (1.5, 14.0),
    },
    'alfalfa': {
        'names': {'en': 'alfalfa', 'fr': 'luzerne', 'ar': 'البرسيم'},
        'perennial': True, 'planting_months': [10, 11, 2, 3],
        'kc': (0.5, 0.6, 0.8, 0.95, 0.95, 0.95, 0.95, 0.95, 0.95, 0.9, 0.7, 0.5),
        'root_m': 1.5, 'p': 0.55, 'ky': 1.1,
        'temp': (0, 10, 30, 38), 'ph': (5.5, 6.5, 8.0, 8.5),
        'texture': {'medium'}, 'ece': (2.0, 7.3),
    },
    'olive': {
        'names': {'en': 'olive', 'fr': 'olivier', 'ar': 'الزيتون'},
        'perennial': True, 'planting_months': [11, 12, 1, 2, 3],
        'kc': (0.65, 0.65, 0.65, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.65, 0.65),
        'root_m': 1.5, 'p': 0.65, 'ky': 0.7,  # Ky approx.
        # monthly-mean limits: winter chill is wanted; -7 C frosts kill,
        # which corresponds to a coldest-month mean near 0 C
        'temp': (-1, 5, 30, 38), 'ph': (5.0, 6.5, 8.5, 9.0),
        'texture': {'light', 'medium'}, 'ece': None,  # moderately tolerant
    },
    'citrus': {
        'names': {'en': 'citrus', 'fr': 'agrumes', 'ar': 'الحمضيات'},
        'perennial': True, 'planting_months': [2, 3, 4, 10, 11],
        'kc': (0.7, 0.7, 0.7, 0.65, 0.65, 0.65, 0.65, 0.65, 0.65, 0.7, 0.7, 0.7),
        'root_m': 1.2, 'p': 0.5, 'ky': 1.1,
        'temp': (6, 11, 32, 38), 'ph': (4.5, 5.5, 7.5, 8.5),
        'texture': {'light', 'medium'}, 'ece': (1.7, 16.0),
    },
    'date_palm': {
        'names': {'en': 'date palm', 'fr': 'palmier dattier', 'ar': 'النخيل'},
        'perennial': True, 'planting_months': [3, 4, 9, 10],
        'kc': (0.9, 0.9, 0.9, 0.95, 0.95, 0.95, 0.95, 0.95, 0.95, 0.95, 0.9, 0.9),
        'root_m': 2.0, 'p': 0.5, 'ky': 0.8,  # Ky approx.
        'temp': (10, 20, 38, 45), 'ph': (5.0, 6.5, 8.5, 10.0),
        'texture': {'light', 'medium'}, 'ece': (4.0, 3.6),
    },
}

# Available water (field capacity - wilting point), mm per m of soil
# (FAO-56 Table 19 mid-range values)
AWC_MM_PER_M = {'light': 90.0, 'medium': 150.0, 'heavy': 140.0}

OFF_TEXTURE_FACTOR = 0.75

SUITABILITY_CLASSES = ((80, 'S1', 'Highly suitable'), (60, 'S2', 'Suitable'),
                       (40, 'S3', 'Marginal'), (0, 'N', 'Not suitable'))


# ------------------------------------------------------------------ #
# Scoring primitives
# ------------------------------------------------------------------ #

def trapezoid(value, abs_min, opt_min, opt_max, abs_max):
    """1 inside [opt_min, opt_max], linear to 0 at the absolute limits."""
    if value is None or value != value:
        return None
    if value <= abs_min or value >= abs_max:
        return 0.0
    if value < opt_min:
        return (value - abs_min) / (opt_min - abs_min)
    if value > opt_max:
        return (abs_max - value) / (abs_max - opt_max)
    return 1.0


def effective_rain(p_month_mm):
    """USDA-SCS monthly effective rainfall (the CROPWAT default)."""
    p = max(float(p_month_mm), 0.0)
    return p * (125 - 0.2 * p) / 125 if p <= 250 else 125 + 0.1 * p


def texture_class(sand_pct, clay_pct):
    if sand_pct is None or clay_pct is None:
        return None
    if clay_pct >= 40:
        return 'heavy'
    if sand_pct >= 70 and clay_pct < 15:
        return 'light'
    return 'medium'


def salinity_factor(ece, crop):
    if ece is None or crop.get('ece') is None:
        return None
    threshold, slope = crop['ece']
    return float(np.clip(1 - slope * max(ece - threshold, 0) / 100.0, 0, 1))


def annual_kc(day, stages, kc):
    """FAO-56 piecewise-linear Kc curve for day index of the season."""
    l_ini, l_dev, l_mid, _ = stages
    k_ini, k_mid, k_end = kc
    if day < l_ini:
        return k_ini
    if day < l_ini + l_dev:
        return k_ini + (k_mid - k_ini) * (day - l_ini) / l_dev
    if day < l_ini + l_dev + l_mid:
        return k_mid
    l_late = stages[3]
    return k_mid + (k_end - k_mid) * min((day - l_ini - l_dev - l_mid) / l_late, 1.0)


def simulate_season(crop, clim, sow_month, rain_key='rain_mean', taw_per_m=150.0):
    """FAO-56 single-coefficient daily root-zone water balance.

    clim: {month: {'et0': mm/day, rain_key: mm/month, 'tmean': C}}
    Returns ETc, ETa (rainfed), net irrigation need (irrigated, refilling
    whenever depletion exceeds RAW), effective rain and season months.
    """
    taw = taw_per_m * crop['root_m']
    raw = crop['p'] * taw
    if crop['perennial']:
        start, length, spin_up = dt.date(2001, 1, 1), 365, 365
    else:
        start, length, spin_up = dt.date(2001, sow_month, 15), sum(crop['stages']), 0
        if sow_month < 7:
            start = dt.date(2002, sow_month, 15)

    # Winter-sown crops start on a profile refilled by autumn rain; spring
    # and summer sowings start half empty.
    depl_rf = 0.0 if crop['perennial'] or sow_month in (10, 11, 12, 1, 2) else 0.5 * taw
    depl_ir = depl_rf
    etc_sum = eta_sum = irr_sum = peff_sum = 0.0
    month_days = {}

    for i in range(-spin_up, length):
        day = start + dt.timedelta(days=i)
        m = day.month
        c = clim[m]
        ndays = calendar.monthrange(day.year, m)[1]
        kc = crop['kc'][m - 1] if crop['perennial'] else annual_kc(i, crop['stages'], crop['kc'])
        etc = kc * c['et0']
        peff = effective_rain(c[rain_key]) / ndays

        # rainfed bucket
        depl_rf = max(depl_rf - peff, 0.0)
        ks = 1.0 if depl_rf <= raw else max((taw - depl_rf) / (taw - raw), 0.0)
        eta = ks * etc
        depl_rf = min(depl_rf + eta, taw)

        # irrigated bucket
        depl_ir = max(depl_ir - peff, 0.0) + etc
        irr = 0.0
        if depl_ir > raw:
            irr, depl_ir = depl_ir, 0.0

        if i < 0:
            continue
        etc_sum += etc
        eta_sum += eta
        irr_sum += irr
        peff_sum += peff
        month_days[m] = month_days.get(m, 0) + 1

    return {'etc_mm': etc_sum, 'eta_mm': eta_sum, 'net_irrigation_mm': irr_sum,
            'peff_mm': peff_sum, 'month_days': month_days}


def score_crop(key, clim, soil=None, sow_month=None, mode='rainfed',
               rain_key='rain_mean', water_supply_mm=None, irrigation_efficiency=0.85):
    """Score one crop at one sowing month. Returns a dict of factors."""
    crop = CROPS[key]
    soil = soil or {}
    tex = texture_class(soil.get('sand_pct'), soil.get('clay_pct'))
    taw_per_m = soil.get('awc_mm_per_m') or AWC_MM_PER_M.get(tex, 150.0)

    sim = simulate_season(crop, clim, sow_month or crop['planting_months'][0],
                          rain_key=rain_key, taw_per_m=taw_per_m)
    # Temperature. Perennials: worst calendar month (they must survive and
    # crop through all of them). Annuals: day-weighted season mean against
    # the optimum, zeroed if any month (>= 10 days) breaches an absolute
    # limit, so a cool transplanting fortnight does not dominate the score.
    days = {m: n for m, n in sim['month_days'].items() if n >= 10}
    if not days:
        temp = None
    elif crop['perennial']:
        temp = min(trapezoid(clim[m]['tmean'], *crop['temp']) for m in days)
    else:
        abs_min, _, _, abs_max = crop['temp']
        if any(not abs_min < clim[m]['tmean'] < abs_max for m in days):
            temp = 0.0
        else:
            mean_t = sum(clim[m]['tmean'] * n for m, n in days.items()) / sum(days.values())
            temp = trapezoid(mean_t, *crop['temp'])

    factors = {
        'temperature': temp,
        'ph': trapezoid(soil.get('ph'), *crop['ph']),
        'texture': (1.0 if tex in crop['texture'] else OFF_TEXTURE_FACTOR) if tex else None,
        'salinity': salinity_factor(soil.get('ece_dsm'), crop),
    }

    etc = sim['etc_mm']
    rel_et = sim['eta_mm'] / etc if etc else 1.0
    rainfed_yield = float(np.clip(1 - crop['ky'] * (1 - rel_et), 0, 1))
    gross_irr = sim['net_irrigation_mm'] / irrigation_efficiency
    if mode == 'irrigated':
        water = 1.0 if water_supply_mm is None or gross_irr <= 0 else \
            float(np.clip(water_supply_mm / gross_irr, 0, 1))
    else:
        water = rainfed_yield
    factors['water'] = water

    known = {k: v for k, v in factors.items() if v is not None}
    cap = min([known[k] for k in ('temperature', 'ph') if k in known] or [1.0])
    score = 100.0 * cap * known.get('texture', 1.0) * known.get('salinity', 1.0) * water
    limiting = min(known, key=known.get) if known else None
    cls = next(c for c in SUITABILITY_CLASSES if score >= c[0])

    return {
        'crop': key,
        'names': crop['names'],
        'perennial': crop['perennial'],
        'sow_month': None if crop['perennial'] else sow_month,
        'score': round(score, 1),
        'class': cls[1],
        'class_label': cls[2],
        'limiting_factor': limiting if known.get(limiting, 1.0) < 1.0 else None,
        'factors': {k: (None if v is None else round(v, 2)) for k, v in factors.items()},
        'water_balance': {
            'etc_mm': round(etc), 'effective_rain_mm': round(sim['peff_mm']),
            'rainfed_eta_etc': round(rel_et, 2),
            'rainfed_relative_yield': round(rainfed_yield, 2),
            'net_irrigation_mm': round(sim['net_irrigation_mm']),
            'gross_irrigation_mm': round(gross_irr),
            'gross_irrigation_m3_per_ha': round(gross_irr * 10),
        },
    }


def rank_crops(clim, soil=None, month=None, mode='rainfed', scenario='normal',
               water_supply_mm=None, crops=None):
    """Rank all crops. For annual crops every sowing month in the planting
    window is tried and the best kept; `month` flags which crops can be
    sown now. scenario 'dry' uses the 25th-percentile monthly rainfall."""
    rain_key = 'rain_p25' if scenario == 'dry' else 'rain_mean'
    results = []
    for key in (crops or CROPS):
        crop = CROPS[key]
        if crop['perennial']:
            options = [None]
        elif month in crop['planting_months']:
            options = [month]
        else:
            options = crop['planting_months']
        best = max((score_crop(key, clim, soil, m, mode, rain_key, water_supply_mm)
                    for m in options), key=lambda r: r['score'])
        best['plantable_now'] = month in crop['planting_months'] if month else None
        if month and not best['plantable_now']:
            later = sorted(crop['planting_months'], key=lambda m: (m - month) % 12)
            best['next_planting_month'] = later[0]
        results.append(best)
    results.sort(key=lambda r: (-(r['plantable_now'] or False), -r['score']))
    return results


# ------------------------------------------------------------------ #
# Django data access
# ------------------------------------------------------------------ #

def region_climatology(region):
    """Monthly climatology from the region's own ClimateMetrics history.

    ET0 is recomputed here with full FAO-56 from monthly means of the raw
    weather fields instead of averaging the stored ET0 column, whose values
    differ ~3x between Ichkeul's two sample points.
    """
    from django.core.cache import cache
    from dashboard.prediction_engine.physical_helpers import fao56_et0
    from dashboard.prediction_engine.spei_features import build_spei_dataset

    if region.latitude is None and not region.sample_points:
        return None
    cache_key = f'crop_suit_clim_{region.id}'
    cached = cache.get(cache_key)
    if cached:
        return cached

    monthly = build_spei_dataset(region.id)
    if monthly.empty:
        return None
    need = ['rainfall_mm', 'temperature_max_c', 'temperature_min_c',
            'solar_radiation_mjm2day', 'relative_humidity_percent', 'wind_speed_ms']
    if any(c not in monthly.columns for c in need):
        return None
    by_month = monthly.groupby(monthly.index.month)
    lat = float(region.latitude if region.latitude is not None
                else region.sample_points[0]['lat'])
    elev = float(region.elevation_m or 0)

    clim = {}
    for m, g in by_month:
        mean = g[need].mean()
        tmax, tmin = float(mean['temperature_max_c']), float(mean['temperature_min_c'])
        clim[int(m)] = {
            'rain_mean': float(g['rainfall_mm'].mean()),
            'rain_p25': float(g['rainfall_mm'].quantile(0.25)),
            'tmean': (tmax + tmin) / 2,
            'et0': fao56_et0(tmax, tmin, float(mean['solar_radiation_mjm2day']),
                             float(mean['relative_humidity_percent']),
                             float(mean['wind_speed_ms']), lat,
                             int(30.4 * m - 15), elevation_m=elev),
        }
    if len(clim) < 12:
        return None
    clim['_meta'] = {'years': f'{monthly.index.min().year}-{monthly.index.max().year}',
                     'n_months': int(len(monthly))}
    cache.set(cache_key, clim, 6 * 3600)
    return clim


def region_soil(region):
    """Average of the region's SoilMetrics rows (see fetch_soilgrids)."""
    from django.db.models import Avg
    from dashboard.models import SoilMetrics

    agg = SoilMetrics.objects.filter(region=region).aggregate(
        sand=Avg('sand_ratio'), clay=Avg('clay_ratio'), ph=Avg('ph_level'),
        ece=Avg('salinity_ece_dsm'), fc=Avg('field_capacity_percent'),
        wp=Avg('wilting_point_percent'))
    if all(v is None for v in agg.values()):
        return None

    def f(v):
        return None if v is None else float(v)

    soil = {'sand_pct': f(agg['sand']), 'clay_pct': f(agg['clay']),
            'ph': f(agg['ph']), 'ece_dsm': f(agg['ece'])}
    if agg['fc'] is not None and agg['wp'] is not None and agg['fc'] > agg['wp']:
        soil['awc_mm_per_m'] = (float(agg['fc']) - float(agg['wp'])) * 10.0
    soil['texture_class'] = texture_class(soil['sand_pct'], soil['clay_pct'])
    return soil


def drought_scenario(region):
    """'dry' when the latest SPEI T+1 outlook raises a drought warning.

    Only the T+1 outlook is used: walk-forward evaluation showed the T+3
    SPEI forecast has no skill over climatology for this region.
    """
    from dashboard.models import SpeiForecast
    from dashboard.prediction_engine.spei_features import drought_warning

    fc = SpeiForecast.objects.filter(region=region).first()
    if fc is None:
        return 'normal', None
    warning, _ = drought_warning(fc.prob_drought_t1, fc.spei_t1)
    info = {'target_month': fc.target_month_t1, 'prob_drought': fc.prob_drought_t1,
            'spei': float(fc.spei_t1) if fc.spei_t1 is not None else None,
            'warning': bool(warning)}
    return ('dry' if warning else 'normal'), info
