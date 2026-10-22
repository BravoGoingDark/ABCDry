"""Grounded, generative brain for the AgroAI assistant.

Design (scientific integrity first):

  1. FACTS    deterministic SQL aggregation over the project tables
              (climate, SPEI/drought indices, forecasts, remote sensing).
  2. RULES    deterministic drought + agronomy decisions. The LLM never
              decides risk, level, score or the recommended action.
  3. LLM      a local Ollama model that only *explains* the facts in the
              user's language. Its output is validated against the facts
              before it is returned.
  4. FALLBACK trilingual template built from the same facts, used when the
              LLM is unavailable, too slow, or produces unverifiable numbers.

Nothing here invents data: if a value is missing it is reported as
"not available" instead of being defaulted to a reassuring number.
"""
import json
import logging
import re

import requests
from django.conf import settings
from django.core.cache import cache
from django.db.models import Avg, Count, Max, Min

from dashboard.models import (ClimateMetrics, DroughtIndices, Region,
                              RemoteSensingMetrics, SpeiForecast)
from dashboard.services import assistant_nlu as nlu
from dashboard.services.crop_kb import CROP_KB, LOW_WATER_CROPS, find_crop

logger = logging.getLogger(__name__)

ENGINE_VERSION = 'rag2'         # bump to invalidate every cached answer
LLM_CACHE_TTL = 60 * 60 * 6     # 6 h  (facts change, so keep it short)
TPL_CACHE_TTL = 60 * 60 * 24 * 20   # 20 days for deterministic templates
MODEL_CACHE_KEY = 'assistant:llm_model'
MODEL_CACHE_TTL = 60 * 5

# Preferred small models, best first (matches the models actually shipped
# with the project's local Ollama install).
MODEL_PREFERENCE = ('gemma3:4b', 'gemma3:1b', 'qwen2.5:3b', 'phi4-mini',
                    'llama3.2:3b', 'llama3.1:8b')

LANGUAGES = {'en': 'English', 'fr': 'French', 'ar': 'Arabic'}
MONTH_NAMES = {1: 'January', 2: 'February', 3: 'March', 4: 'April', 5: 'May',
               6: 'June', 7: 'July', 8: 'August', 9: 'September',
               10: 'October', 11: 'November', 12: 'December'}


def detect_language(text):
    """Detect whether user query is in Arabic, French, or English.

    The text is folded first (case, accents, Arabic marks), so "Sécheresse"
    and "سَقَاء" are recognised like their plain spellings.
    """
    if not text:
        return None
    if re.search(r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]', text):
        return 'ar'
    tokens = set(nlu.tokenize(text))
    fr_markers = {
        'je', 'tu', 'il', 'elle', 'on', 'nous', 'vous', 'ils', 'elles',
        'le', 'la', 'les', 'un', 'une', 'des', 'du', 'de', 'dans', 'en',
        'est', 'sont', 'suis', 'es', 'avez', 'avons', 'ont',
        'qui', 'que', 'quoi', 'quand', 'comment', 'pourquoi', 'ou', 'ou',
        'dois', 'peut', 'faire', 'arroser', 'irriguer', 'pluie', 'secheresse',
        'ble', 'tomate', 'olivier', 'merci', 'bonjour', 'salut'
    }
    en_markers = {
        'i', 'you', 'he', 'she', 'it', 'we', 'they',
        'the', 'a', 'an', 'is', 'are', 'am', 'was', 'were', 'have', 'has',
        'in', 'on', 'at', 'to', 'for', 'of', 'with', 'from',
        'who', 'what', 'when', 'where', 'why', 'how', 'which',
        'should', 'can', 'will', 'would', 'do', 'does', 'did',
        'water', 'irrigate', 'rain', 'drought', 'wheat', 'tomato', 'olive',
        'thanks', 'hello', 'hi'
    }
    fr_hits = len(tokens & fr_markers)
    en_hits = len(tokens & en_markers)
    if fr_hits > en_hits:
        return 'fr'
    if en_hits > fr_hits:
        return 'en'
    return None


# --------------------------------------------------------------------------- #
# LLM configuration + model resolution
# --------------------------------------------------------------------------- #
def llm_config():
    """Assistant LLM settings, read from Django settings / environment."""
    return {
        'url': getattr(settings, 'ASSISTANT_LLM_URL', 'http://localhost:11434'),
        'model': getattr(settings, 'ASSISTANT_LLM_MODEL', '') or '',
        'timeout': int(getattr(settings, 'ASSISTANT_LLM_TIMEOUT', 60)),
        'keep_alive': getattr(settings, 'ASSISTANT_LLM_KEEP_ALIVE', '30m'),
        'num_ctx': int(getattr(settings, 'ASSISTANT_LLM_NUM_CTX', 4096)),
        'temperature': float(getattr(settings, 'ASSISTANT_LLM_TEMPERATURE', 0.2)),
        'enabled': bool(getattr(settings, 'ASSISTANT_LLM_ENABLED', True)),
    }


def installed_models(url=None):
    """Names of the models the local Ollama server actually has."""
    url = url or llm_config()['url']
    try:
        resp = requests.get(f'{url}/api/tags', timeout=5)
        if resp.status_code == 200:
            return [m.get('name') for m in resp.json().get('models', []) if m.get('name')]
    except Exception as exc:              # noqa: BLE001 - never break an answer
        logger.warning('assistant: Ollama unreachable at %s (%s)', url, exc)
    return []


def resolve_model(force=False):
    """Configured model if installed, else the best installed model.

    Returns '' when no model is available (assistant runs template-only).
    The previous implementation silently required 'llama3.2:3b', which was
    never installed, so the LLM was never used at all.
    """
    cfg = llm_config()
    if not cfg['enabled']:
        return ''
    if not force:
        cached = cache.get(MODEL_CACHE_KEY)
        if cached is not None:
            return cached

    available = installed_models(cfg['url'])
    chosen = ''
    if cfg['model']:
        if cfg['model'] in available:
            chosen = cfg['model']
        else:
            logger.warning('assistant: configured model %r is not installed; '
                           'falling back to auto-detect', cfg['model'])
    if not chosen:
        for candidate in MODEL_PREFERENCE:
            if candidate in available:
                chosen = candidate
                break
    if not chosen and available:
        chosen = available[0]
    if not chosen:
        logger.warning('assistant: no Ollama model available - the assistant '
                       'will answer from deterministic templates only')
    cache.set(MODEL_CACHE_KEY, chosen, MODEL_CACHE_TTL)
    return chosen


def llm_available():
    return bool(resolve_model())


# --------------------------------------------------------------------------- #
# Numeric grounding: reject LLM text whose numbers are not in the facts
# --------------------------------------------------------------------------- #
_NUMBER_RE = re.compile(r'\d+(?:[.,]\d+)?')


def _collect_numbers(value, out):
    """Recursively collect every numeric value from the facts structure."""
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        out.append(float(value))
    elif isinstance(value, str):
        for token in _NUMBER_RE.findall(value):
            try:
                out.append(float(token.replace(',', '.')))
            except ValueError:
                pass
    elif isinstance(value, dict):
        for item in value.values():
            _collect_numbers(item, out)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _collect_numbers(item, out)


def allowed_numbers(facts, extra=None):
    """Numbers the assistant is permitted to mention.

    `extra` carries values that came from retrieved reference context, which
    the grounding check must accept alongside the database facts.
    """
    raw = []
    _collect_numbers(facts, raw)
    for value in (extra or ()):
        try:
            raw.append(float(value))
        except (TypeError, ValueError):
            continue
    allowed = set()
    for value in raw:
        allowed.add(round(value))
        allowed.add(round(value, 1))
        allowed.add(round(value, 2))
        allowed.add(int(value))
    # calendar-ish constants are always legitimate
    allowed.update(range(0, 13))                     # months, weeks, days
    allowed.update(range(1990, 2101))                # years
    allowed.update({15, 20, 25, 30, 40, 45, 50, 60, 75, 80, 90, 100})
    return allowed


def validate_numbers(text, facts, tolerance=None, extra=None):
    """Return the numbers in `text` that cannot be traced back to `facts`.

    A number is accepted when it matches a fact value, or is within a small
    rounding distance of one (``max(1, 2%)``) so that legitimate rounding by
    the model is not treated as a fabrication. `extra` widens the permitted
    set with values taken from retrieved reference context.
    """
    allowed = allowed_numbers(facts, extra=extra)
    bad = []
    for token in _NUMBER_RE.findall(text or ''):
        try:
            value = float(token.replace(',', '.'))
        except ValueError:
            continue
        if round(value) in allowed or round(value, 1) in allowed:
            continue
        limit = tolerance if tolerance is not None else max(1.0, abs(value) * 0.02)
        if any(abs(value - candidate) <= limit for candidate in allowed):
            continue
        bad.append(token)
    return bad


def _tidy(text):
    """Remove trailing bullet artefacts, leaked prompt tags, and duplicated whitespace."""
    if not text:
        return text
    # Normalize unicode dashes and quotes
    text = text.replace('\u2013', '-').replace('\u2014', '-').replace('\u2018', "'").replace('\u2019', "'")
    # Strip any leaked prompt references or SQL/bash codeblocks
    text = re.sub(r'REFERENCE\s+\d+.*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'psql\s+-U.*', '', text, flags=re.IGNORECASE)
    cleaned = []
    for line in text.splitlines():
        stripped = line.rstrip()
        if stripped.strip() in ('-', '*', '•'):
            continue
        cleaned.append(stripped)
    return re.sub(r'[ \t]{2,}', ' ', '\n'.join(cleaned)).strip()


# --------------------------------------------------------------------------- #
# FACTS: deterministic aggregation over the project tables
# --------------------------------------------------------------------------- #
def _f(value):
    """Decimal/None -> float/None."""
    return None if value is None else float(value)


def _round(value, digits=1):
    return None if value is None else round(float(value), digits)


def _resolve_region(region_id):
    """Explicit region, else Ichkeul, else the region with the most climate data."""
    if region_id:
        region = Region.objects.filter(id=region_id).first()
        if region:
            return region
    region = Region.objects.filter(name__iexact='Ichkeul').first()
    if region:
        return region
    busiest = (ClimateMetrics.objects.values('region')
               .annotate(n=Count('id')).order_by('-n').first())
    if busiest:
        return Region.objects.filter(id=busiest['region']).first()
    return Region.objects.first()


def _daily_climate(region, start=None, end=None, month=None):
    """Per-date climate for a region, averaging the region's stations.

    Aggregating per date (instead of taking an arbitrary first row) is what
    stops a two-station region such as Ichkeul from returning whichever
    station the database happened to order first.
    """
    qs = ClimateMetrics.objects.filter(region=region)
    if start is not None:
        qs = qs.filter(measurement_date__gte=start)
    if end is not None:
        qs = qs.filter(measurement_date__lte=end)
    if month is not None:
        qs = qs.filter(measurement_date__month=month)
    return list(qs.values('measurement_date').annotate(
        rain=Avg('rainfall_mm'), tmean=Avg('temperature_mean_c'),
        tmax=Max('temperature_max_c'), tmin=Min('temperature_min_c'),
        rh=Avg('relative_humidity_percent'), wind=Avg('wind_speed_ms'),
        solar=Avg('solar_radiation_mjm2day'),
        et0=Avg('evapotranspiration_et0_mmday'),
        etc=Avg('evapotranspiration_etc_mmday'),
    ).order_by('measurement_date'))


def _total(rows, key):
    values = [float(r[key]) for r in rows if r.get(key) is not None]
    return round(sum(values), 1) if values else None


def _mean(rows, key, digits=1):
    values = [float(r[key]) for r in rows if r.get(key) is not None]
    return round(sum(values) / len(values), digits) if values else None


def _extreme(rows, key, biggest=True):
    values = [float(r[key]) for r in rows if r.get(key) is not None]
    if not values:
        return None
    return round(max(values) if biggest else min(values), 1)


def _daily_rs(region, start=None, end=None):
    """Per-date remote-sensing aggregates for a region."""
    qs = RemoteSensingMetrics.objects.filter(region=region)
    if start is not None:
        qs = qs.filter(measurement_date__gte=start)
    if end is not None:
        qs = qs.filter(measurement_date__lte=end)
    return list(qs.values('measurement_date').annotate(
        ndvi=Avg('ndvi'), ndwi=Avg('ndwi'),
        lst=Avg('land_surface_temperature_c'),
        soil=Avg('satellite_soil_moisture_percent'),
        vci=Avg('vegetation_condition_index'),
        sebal=Avg('evapotranspiration_sebal_mmday'),
    ).order_by('measurement_date'))


def _trend(rows, key):
    """Change between the first and last available value of a series."""
    values = [float(r[key]) for r in rows if r.get(key) is not None]
    if len(values) < 2:
        return None
    return round(values[-1] - values[0], 3)


def _season(month):
    return {12: 'winter', 1: 'winter', 2: 'winter',
            3: 'spring', 4: 'spring', 5: 'spring',
            6: 'summer', 7: 'summer', 8: 'summer'}.get(month, 'autumn')


def _score_from_spei(spei):
    """Deterministic SPEI-3 -> 0-100 risk score (documented convention)."""
    if spei is None:
        return None
    if spei >= 0:
        return 10
    if spei >= -0.5:
        return round(10 + (-spei / 0.5) * 10)
    if spei >= -1.0:
        return round(20 + ((-spei - 0.5) / 0.5) * 20)
    if spei >= -1.5:
        return round(40 + ((-spei - 1.0) / 0.5) * 20)
    if spei >= -2.0:
        return round(60 + ((-spei - 1.5) / 0.5) * 20)
    return min(100, round(80 + ((-spei - 2.0) / 1.0) * 20))


def _requested_period(question):
    """Detect 'July 2019' / '2019-07' style periods in the question."""
    text = (question or '').lower()
    month = None
    for number, name in MONTH_NAMES.items():
        if name.lower() in text:
            month = number
            break
    if month is None:
        match = re.search(r'\b(20\d{2})[-/](\d{1,2})\b', text)
        if match:
            month = int(match.group(2))
    years = [int(y) for y in re.findall(r'\b(19\d{2}|20\d{2})\b', text)]
    year = years[-1] if years else None
    if month and not 1 <= month <= 12:
        month = None
    return year, month


def _spei_level(spei):
    if spei is None:
        return 'unknown'
    if spei > -0.5:
        return 'Normal'
    if spei > -1.0:
        return 'Mild'
    if spei > -1.5:
        return 'Moderate'
    if spei > -2.0:
        return 'Severe'
    return 'Extreme'


# Forecast rows sometimes store a level string (Low/Moderate/High/...) and
# sometimes leave it empty; map both conventions onto one vocabulary.
LEVEL_ALIASES = {'low': 'Normal', 'normal': 'Normal', 'mild': 'Mild',
                 'moderate': 'Moderate', 'medium': 'Moderate',
                 'high': 'Severe', 'severe': 'Severe', 'extreme': 'Extreme',
                 'very high': 'Extreme', '': None, None: None}


def _level_from_score(score):
    """Documented score -> level convention (0-100)."""
    if score is None:
        return None
    if score <= 20:
        return 'Normal'
    if score <= 40:
        return 'Mild'
    if score <= 60:
        return 'Moderate'
    if score <= 80:
        return 'Severe'
    return 'Extreme'


def _normalise_level(raw_level, score=None):
    """Level from the database, falling back to the score, else SPEI."""
    if raw_level is not None:
        mapped = LEVEL_ALIASES.get(str(raw_level).strip().lower(), None)
        if mapped:
            return mapped
    return _level_from_score(score)



def build_facts(region_id=None, crop=None, question=''):
    """Everything the assistant is allowed to talk about, from the database."""
    from datetime import timedelta

    region = _resolve_region(region_id)
    if region is None:
        return {'region': 'unknown', 'data_available': False,
                'data_warnings': ['no region is configured in the system']}

    latest = ClimateMetrics.objects.filter(region=region).aggregate(
        last=Max('measurement_date'), first=Min('measurement_date'),
        rows=Count('id'))
    last_date = latest['last']
    station_count = (ClimateMetrics.objects.filter(region=region)
                     .values('latitude', 'longitude').distinct().count()) or 1

    facts = {
        'region': region.name,
        'country': region.country,
        'region_latitude': _f(region.latitude),
        'region_longitude': _f(region.longitude),
        'elevation_m': region.elevation_m,
        'area_km2': _f(region.area_km2),
        'stations_aggregated': station_count,
        'data_available': bool(last_date),
        'measured_until': last_date,
        'measured_from': latest['first'],
        'climate_rows': latest['rows'],
        'crop': crop,
        'month': MONTH_NAMES.get(last_date.month) if last_date else None,
        'season': _season(last_date.month) if last_date else None,
    }
    warnings = []
    if not last_date:
        warnings.append('no climate measurements exist for this region')
        facts['data_warnings'] = warnings
        return facts

    # ── climate windows (per-date means, so stations are averaged) ──────
    climate = {}
    for label, days in {'30d': 30, '90d': 90, '180d': 180, '365d': 365}.items():
        start = last_date - timedelta(days=days - 1)
        rows = _daily_climate(region, start=start, end=last_date)
        climate[f'rain_{label}_mm'] = _total(rows, 'rain')
        climate[f'et0_{label}_mm'] = _total(rows, 'et0')
        climate[f'days_with_data_{label}'] = len(rows)
        if label in ('30d', '90d'):
            climate[f'tmean_{label}_c'] = _mean(rows, 'tmean')
            climate[f'tmax_{label}_c'] = _extreme(rows, 'tmax')
            climate[f'tmin_{label}_c'] = _extreme(rows, 'tmin', biggest=False)
            climate[f'humidity_{label}_pct'] = _mean(rows, 'rh')
            climate[f'wind_{label}_ms'] = _mean(rows, 'wind')
            climate[f'solar_{label}_mjm2day'] = _mean(rows, 'solar')

    rain30, et030 = climate.get('rain_30d_mm'), climate.get('et0_30d_mm')
    if rain30 is not None and et030 is not None:
        climate['water_balance_30d_mm'] = round(rain30 - et030, 1)

    # ── climatology for the current calendar month (all stored years) ───
    month_rows = _daily_climate(region, month=last_date.month)
    per_year = {}
    for row in month_rows:
        per_year[row['measurement_date'].year] = (
            per_year.get(row['measurement_date'].year, 0.0)
            + float(row['rain'] or 0.0))
    if per_year:
        totals = [round(v, 1) for v in per_year.values()]
        clim_mean = round(sum(totals) / len(totals), 1)
        this_year = per_year.get(last_date.year)
        climate['rain_this_month_mm'] = round(this_year, 1) if this_year is not None else None
        climate['rain_month_climatology_mm'] = clim_mean
        climate['rain_month_years_used'] = len(totals)
        if this_year is not None and clim_mean > 0:
            climate['rain_month_deficit_pct'] = round(
                100 * (this_year - clim_mean) / clim_mean)

    # ── explicitly requested period (e.g. "rainfall July 2019") ─────────
    year, month = _requested_period(question)
    if month:
        requested = [r for r in month_rows
                     if year is None or r['measurement_date'].year == year]
        if requested:
            facts['requested_period'] = {
                'month': MONTH_NAMES.get(month),
                'year': year,
                'rain_mm': _total(requested, 'rain'),
                'et0_mm': _total(requested, 'et0'),
                'tmean_c': _mean(requested, 'tmean'),
                'days': len(requested),
            }
        else:
            warnings.append(f'no measurements are stored for '
                            f'{MONTH_NAMES.get(month)}' + (f' {year}' if year else ''))

    facts['climate'] = climate

    # ── drought indices (SPEI) ──────────────────────────────────────────
    drought_rows = list(DroughtIndices.objects.filter(region=region)
                        .order_by('-measurement_date')[:6])
    if drought_rows:
        newest = drought_rows[0]
        facts['drought'] = {
            'as_of': newest.measurement_date,
            'spei_3month': _f(newest.spei_3month),
            'spei_12month': _f(newest.spei_12month),
            'spi_3month': _f(newest.spi_3month),
            'pdsi': _f(newest.pdsi_value),
            'severity_class': newest.drought_severity_class,
        }
        if (len(drought_rows) > 3 and drought_rows[0].spei_3month is not None
                and drought_rows[3].spei_3month is not None):
            facts['drought']['spei_3month_change_3m'] = round(
                float(drought_rows[0].spei_3month)
                - float(drought_rows[3].spei_3month), 2)
    else:
        warnings.append('no SPEI/drought index rows exist for this region')

    # ── forecast (ordered - the previous code took an arbitrary row) ────
    forecast = (SpeiForecast.objects.filter(region=region)
                .order_by('-generated_at', '-feature_month').first())
    if forecast:
        facts['forecast'] = {
            'model_version': forecast.model_version,
            'generated_at': forecast.generated_at,
            'feature_month': forecast.feature_month,
            'next_month': {
                'target_month': forecast.target_month_t1,
                'spei': _f(forecast.spei_t1),
                'risk_score': forecast.score_t1,
                'level': forecast.level_t1,
                'probability_drought_pct': (
                    round(float(forecast.prob_drought_t1) * 100)
                    if forecast.prob_drought_t1 is not None else None),
            },
            'top_drivers': forecast.top_drivers,
        }
        # T+3 is withheld unless explicitly re-enabled: it has no measured
        # out-of-sample skill, so exposing it would invite decisions that the
        # data cannot support.
        if getattr(settings, 'SPEI_T3_ENABLED', False):
            facts['forecast']['three_month'] = {
                'target_month': forecast.target_month_t3,
                'spei': _f(forecast.spei_t3),
                'risk_score': forecast.score_t3,
                'level': forecast.level_t3,
                'probability_drought_pct': (
                    round(float(forecast.prob_drought_t3) * 100)
                    if forecast.prob_drought_t3 is not None else None),
            }
        elif forecast.spei_t3 is not None:
            warnings.append(
                'the 3-month outlook is withheld: it showed no predictive skill '
                'in backtesting, so only the 1-month forecast is offered')
    else:
        warnings.append('no SPEI forecast has been generated for this region yet')

    # ── remote sensing ──────────────────────────────────────────────────
    rs_all = _daily_rs(region)
    if rs_all:
        rs90 = _daily_rs(region, start=last_date - timedelta(days=89), end=last_date)
        facts['remote_sensing'] = {
            'as_of': rs_all[-1]['measurement_date'],
            'ndvi': _round(rs_all[-1]['ndvi'], 3),
            'ndwi': _round(rs_all[-1]['ndwi'], 3),
            'vegetation_condition_index': _round(rs_all[-1]['vci'], 1),
            'land_surface_temperature_c': _round(rs_all[-1]['lst'], 1),
            'soil_moisture_pct': _round(rs_all[-1]['soil'], 1),
            'evapotranspiration_sebal_mmday': _round(rs_all[-1]['sebal'], 2),
            'ndvi_trend_90d': _trend(rs90, 'ndvi'),
            'soil_moisture_trend_90d': _trend(rs90, 'soil'),
        }
    else:
        warnings.append('no satellite (remote sensing) rows exist for this region')

    # ── crop knowledge ──────────────────────────────────────────────────
    if crop and crop in CROP_KB:
        info = CROP_KB[crop]
        facts['crop_profile'] = {
            'name': crop,
            'water_need': info.get('water_need'),
            'planting_months': info.get('planting_months'),
            'critical_stages': (info.get('critical_stages') or {}).get('en'),
            'in_planting_window_now': last_date.month in (info.get('planting_months') or []),
        }
    if crop is None:
        facts['low_water_crop_options'] = list(LOW_WATER_CROPS)[:6]

    # ── deterministic risk statement (never the LLM's job) ──────────────
    next_month = (facts.get('forecast') or {}).get('next_month') or {}
    three_month = (facts.get('forecast') or {}).get('three_month') or {}
    spei3 = (facts.get('drought') or {}).get('spei_3month')
    # Use the stored level when present, else derive it from the score so the
    # answer never says "unknown" while a score exists.
    if next_month.get('risk_score') is not None:
        next_month['level'] = _normalise_level(next_month.get('level'),
                                               next_month.get('risk_score'))
    if three_month.get('risk_score') is not None:
        three_month['level'] = _normalise_level(three_month.get('level'),
                                                three_month.get('risk_score'))
    if next_month.get('risk_score') is not None:
        summary = {'risk_score': next_month['risk_score'],
                   'risk_level': next_month.get('level'),
                   'risk_source': 'SPEI forecast model (T+1)'}
    elif spei3 is not None:
        summary = {'risk_score': _score_from_spei(spei3),
                   'risk_level': _spei_level(spei3),
                   'risk_source': 'observed SPEI-3 (no forecast available)'}
    else:
        summary = {'risk_score': None, 'risk_level': 'unknown',
                   'risk_source': 'insufficient data'}
        warnings.append('SPEI-3 is missing, so no reliable drought level can be stated')
    if next_month.get('probability_drought_pct') is not None:
        prob = next_month['probability_drought_pct']
        summary['probability_drought_next_month_pct'] = prob
        # Deterministic yes/no verdict: 24% must NOT be reported as "drought
        # expected" (a local model got that wrong when left to decide).
        summary['next_month_verdict'] = (
            'likely' if prob >= 60 else 'possible' if prob >= 30 else 'unlikely')
    facts['summary'] = summary

    if station_count > 1:
        warnings.append(f'values are the average of {station_count} stations '
                        'in this region')
    if climate.get('et0_30d_mm') is not None and climate['et0_30d_mm'] < 15:
        warnings.append('the stored ET0 values look implausibly low for this '
                        'region; the SPEI may be affected - verify the import')
    facts['data_warnings'] = warnings
    return facts


# --------------------------------------------------------------------------- #
# INTENT: what is the user actually asking?
# --------------------------------------------------------------------------- #
# The keyword table lives in the NLU layer, which owns normalisation and
# fuzzy matching; it is re-exported here for existing importers.
INTENT_KEYWORDS = nlu.INTENT_KEYWORDS


def classify_intent(question):
    """Keyword intent classifier with a real `freeform` fallback.

    The old version silently mapped every unrecognised question to
    'drought_status', so "who are you?" and "my wheat is yellow" both got the
    same drought paragraph. Matching now runs through the NLU layer, which
    folds accents and Arabic marks and tolerates typos, while still anchoring
    on a word boundary so "wheat" does not match the keyword "heat".
    """
    return nlu.match_intent(question)[0]


# --------------------------------------------------------------------------- #
# RULES: deterministic decisions (the LLM never sets risk or action)
# --------------------------------------------------------------------------- #
def apply_rules(facts, intent, crop=None):
    """Return the deterministic action code + supporting evidence."""
    summary = facts.get('summary') or {}
    score = summary.get('risk_score')
    level = summary.get('risk_level') or 'unknown'
    bucket = (level or '').lower()
    profile = facts.get('crop_profile') or {}
    water_need = profile.get('water_need')
    rs = facts.get('remote_sensing') or {}
    soil = rs.get('soil_moisture_pct')
    drought = facts.get('drought') or {}
    spei3 = drought.get('spei_3month')

    if score is None:
        action = 'no_data'
    elif intent == 'irrigation':
        if bucket in ('severe', 'extreme'):
            action = 'urgent'
        elif bucket == 'high' or (water_need == 'high' and (soil if soil is not None else 100) < 55):
            action = 'soon'
        elif bucket == 'moderate' or (soil is not None and soil < 40):
            action = 'monitor'
        else:
            action = 'normal'
    elif intent == 'planting':
        if not profile:
            action = ('recommend_low_water' if bucket in ('severe', 'extreme')
                      else 'lean_low_water' if bucket == 'high' else 'normal_choice')
        else:
            in_window = profile.get('in_planting_window_now')
            if bucket in ('severe', 'extreme'):
                action = ('postpone_or_switch'
                          if (not in_window or water_need == 'high') else 'caution')
            elif bucket == 'high':
                action = 'caution'
            else:
                action = 'go' if in_window else 'wait_window'
    elif intent == 'water_reduction':
        action = ('mandatory' if bucket in ('severe', 'extreme')
                  else 'strong' if bucket == 'high'
                  else 'voluntary' if bucket == 'moderate' else 'none')
    elif intent == 'crop_care':
        action = ('stress_watch' if bucket in ('high', 'severe', 'extreme')
                  else 'routine')
    else:
        action = 'inform'

    note = None
    trend = drought.get('spei_3month_change_3m')
    if soil is not None and soil < 25:
        note = 'satellite soil moisture is very low'
    elif rs.get('ndvi_trend_90d') is not None and rs['ndvi_trend_90d'] < -0.05:
        note = 'vegetation greenness declined over the last 90 days'
    elif trend is not None and trend < -0.3:
        note = 'SPEI-3 has been deteriorating over the last three months'

    return {
        'action': action,
        'risk_score': score,
        'risk_level': level,
        'bucket': bucket,
        'spei_3month': spei3,
        'priority_note': note,
        'evidence': [line for line in (
            f'SPEI-3={spei3}' if spei3 is not None else None,
            f'soil_moisture={soil}%' if soil is not None else None,
            f'ndvi={rs.get("ndvi")}' if rs.get('ndvi') is not None else None,
        ) if line],
    }


# --------------------------------------------------------------------------- #
# Trilingual deterministic answers (fallback + always the source of truth)
# --------------------------------------------------------------------------- #
ACTIONS = {
    'urgent': ('Water stress is severe: irrigate critical crops within 2-3 days, '
               'prioritise the highest-value crops and irrigate at dawn or dusk.',
               "Stress hydrique sévère : irriguez les cultures critiques sous 2-3 jours, "
               "priorité aux cultures à plus forte valeur, tôt le matin ou en soirée.",
               'الإجهاد المائي شديد: اسقِ المحاصيل الحساسة خلال 2 إلى 3 أيام، '
               'وأعطِ الأولوية للمحاصيل الأعلى قيمة، مع السقي عند الفجر أو الغروب.'),
    'soon': ('Plan irrigation within 5-7 days for your most valuable crops, '
             'after checking soil moisture.',
             "Prévoyez l'irrigation dans 5 à 7 jours pour vos cultures les plus "
             "précieuses, après contrôle de l'humidité du sol.",
             'خطّط للسقي خلال 5 إلى 7 أيام للمحاصيل الأكثر أهمية، بعد التحقق من رطوبة التربة.'),
    'monitor': ('No immediate irrigation is needed, but check soil moisture twice '
                'a week and be ready to irrigate.',
                "Aucune irrigation immédiate n'est nécessaire, mais contrôlez "
                "l'humidité du sol deux fois par semaine.",
                'لا حاجة لسقي فوري، لكن راقب رطوبة التربة مرتين أسبوعياً وكن مستعداً للسقي.'),
    'normal': ('Keep your usual irrigation schedule and monitor weekly.',
               "Gardez votre calendrier d'irrigation habituel et surveillez chaque semaine.",
               'حافظ على جدول السقي المعتاد وراقب الوضع أسبوعياً.'),
    'postpone_or_switch': ('Postpone sowing or switch to a lower-water crop.',
                           "Reportez le semis ou passez à une culture moins gourmande en eau.",
                           'أجّل البذر أو انتقل إلى محصول أقل استهلاكاً للماء.'),
    'caution': ('Sowing is possible but risky in these conditions: sow only with '
                'assured irrigation and mulching.',
                "Le semis reste possible mais risqué : semez uniquement avec une "
                "irrigation assurée et un paillage.",
                'الزراعة ممكنة لكنها محفوفة بالمخاطر: ازرع فقط مع ضمان الري والتغطية بالنشارة.'),
    'go': ('Conditions allow sowing this month; follow the usual density and '
           'irrigate at emergence.',
           "Les conditions permettent le semis ce mois-ci ; respectez la densité "
           "habituelle et irriguez à la levée.",
           'الظروف مناسبة للزراعة هذا الشهر؛ التزم بالكثافة المعتادة واسقِ عند الإنبات.'),
    'wait_window': ('Wait for the recommended planting window for this crop.',
                    "Attendez la fenêtre de plantation recommandée pour cette culture.",
                    'انتظر الفترة الموصى بها لزراعة هذا المحصول.'),
    'recommend_low_water': ('Prefer low-water crops for this season.',
                            "Préférez des cultures économes en eau pour cette saison.",
                            'يفضّل اختيار محاصيل قليلة الاستهلاك للماء هذا الموسم.'),
    'lean_low_water': ('Consider shifting part of the area to low-water crops.',
                       "Envisagez de basculer une partie de la surface vers des "
                       "cultures économes en eau.",
                       'فكّر في تحويل جزء من المساحة إلى محاصيل قليلة الاستهلاك للماء.'),
    'normal_choice': ('The usual crop choice remains suitable for this season.',
                      "Le choix habituel de culture reste adapté à cette saison.",
                      'الخيار المعتاد للمحصول يبقى مناسباً هذا الموسم.'),
    'mandatory': ('Apply mandatory water restrictions now: stop non-essential use '
                  'and protect drinking-water supply.',
                  "Appliquez des restrictions d'eau obligatoires : arrêtez les usages "
                  "non essentiels et protégez l'eau potable.",
                  'طبّق قيوداً إلزامية على الماء الآن: أوقف الاستخدامات غير الضرورية '
                  'واحمِ مياه الشرب.'),
    'strong': ('Reduce water use now: prioritise essential needs and repair leaks.',
               "Réduisez la consommation d'eau : priorisez l'essentiel et réparez les fuites.",
               'قلّل استهلاك الماء: أعطِ الأولوية للاحتياجات الأساسية وأصلح التسربات.'),
    'voluntary': ('Voluntary savings are advisable: irrigate at night and avoid losses.',
                  "Des économies volontaires sont conseillées : irriguez la nuit et "
                  "évitez les pertes.",
                  'يُنصح بترشيد طوعي: اسقِ ليلاً وتجنّب الفاقد.'),
    'none': ('No water restriction is needed at this time.',
             "Aucune restriction d'eau n'est nécessaire actuellement.",
             'لا حاجة لقيود على الماء حالياً.'),
    'stress_watch': ('Watch the crop closely: heat and water stress can cut yield at '
                     'this stage.',
                     "Surveillez la culture de près : le stress hydrique et thermique "
                     "peut réduire le rendement à ce stade.",
                     'راقب المحصول بدقة: الإجهاد المائي والحراري قد يخفض المردود في هذه المرحلة.'),
    'routine': ('Routine crop care is sufficient; keep monitoring as usual.',
                "L'entretien habituel suffit ; poursuivez la surveillance normale.",
                'العناية المعتادة كافية، وواصل المراقبة بشكل طبيعي.'),
    'no_data': ('No reliable drought index is available for this region yet, so no '
                'data-based recommendation can be given.',
                "Aucun indice de sécheresse fiable n'est encore disponible pour cette "
                "région : aucune recommandation fondée sur les données n'est possible.",
                'لا يتوفر مؤشر جفاف موثوق لهذه المنطقة بعد، لذا لا يمكن إعطاء توصية مبنية على البيانات.'),
    'inform': ('Use the figures above to plan your next operations.',
               "Utilisez les chiffres ci-dessus pour planifier vos prochaines opérations.",
               'استعن بالأرقام أعلاه لتخطيط عملياتك القادمة.'),
}

LEVEL_TEXT = {
    'normal': ('Normal', 'Normal', 'طبيعي'),
    'mild': ('Mild drought', 'Sécheresse légère', 'جفاف طفيف'),
    'moderate': ('Moderate drought', 'Sécheresse modérée', 'جفاف متوسط'),
    'severe': ('Severe drought', 'Sécheresse sévère', 'جفاف حاد'),
    'extreme': ('Extreme drought', 'Sécheresse extrême', 'جفاف شديد جداً'),
    'unknown': ('unknown', 'inconnu', 'غير معروف'),
}

# Yes/no statement derived from the drought probability (deterministic).
VERDICT = {
    'likely': ('Drought is likely next month;',
               'Une sécheresse est probable le mois prochain ;',
               'الجفاف مرجّح الشهر القادم؛'),
    'possible': ('Drought is possible but not likely next month;',
                 'Une sécheresse est possible mais peu probable le mois prochain ;',
                 'الجفاف ممكن لكنه غير مرجّح الشهر القادم؛'),
    'unlikely': ('Drought is not expected next month;',
                 "Une sécheresse n'est pas attendue le mois prochain ;",
                 'لا يُتوقع جفاف الشهر القادم؛'),
}

KNOWLEDGE = {
    'ndvi': ('NDVI (Normalised Difference Vegetation Index) measures vegetation '
             'greenness from satellite imagery: high values mean dense, healthy '
             'vegetation, low values mean sparse or stressed cover.',
             "Le NDVI (indice de végétation par différence normalisée) mesure la "
             "végétation à partir d'images satellitaires : une valeur élevée indique "
             "une végétation dense et saine.",
             'مؤشر NDVI يقيس كثافة الغطاء النباتي من صور الأقمار الصناعية: القيم '
             'المرتفعة تعني غطاءً كثيفاً وسليماً والمنخفضة تعني غطاءً ضعيفاً أو مجهداً.'),
    'spei': ('SPEI (Standardised Precipitation-Evapotranspiration Index) is the '
             'drought index used here: it compares rainfall minus atmospheric water '
             'demand against the long-term climate record. Below -0.5 indicates '
             'drought, below -2.0 is extreme drought.',
             "Le SPEI est l'indice de sécheresse utilisé ici : il compare la pluie "
             "moins la demande évaporative à la climatologie. Sous -0.5 : sécheresse ; "
             "sous -2.0 : sécheresse extrême.",
             'مؤشر SPEI هو مؤشر الجفاف المستخدم هنا: يقارن المطر ناقص الطلب التبخري '
             'بالمعدلات المناخية الطويلة. أقل من -0.5 يعني جفافاً، وأقل من -2.0 جفاف شديد.'),
    'vci': ('VCI (Vegetation Condition Index) compares current greenness with the '
            'best and worst years on record: near 0 means very poor vegetation '
            'conditions, near 100 means very good.',
            "Le VCI compare la végétation actuelle aux meilleures et pires années "
            "enregistrées : proche de 0 = très mauvais état, proche de 100 = très bon.",
            'مؤشر VCI يقارن حالة الغطاء النباتي الحالية بأفضل وأسوأ السنوات المسجلة: '
            'قريب من 0 يعني حالة سيئة جداً وقريب من 100 يعني حالة ممتازة.'),
}


def _loc(pack, lang):
    return pack[{'en': 0, 'fr': 1, 'ar': 2}.get(lang, 0)]


def _headline(facts, lang):
    s = facts.get('summary') or {}
    region = facts.get('region')
    level = _loc(LEVEL_TEXT.get((s.get('risk_level') or 'unknown').lower(),
                                LEVEL_TEXT['unknown']), lang)
    score = s.get('risk_score')
    prob = s.get('probability_drought_next_month_pct')
    source = s.get('risk_source')
    verdict = s.get('next_month_verdict')
    lead = _loc(VERDICT[verdict], lang) + ' ' if verdict in VERDICT else ''
    if lang == 'fr':
        text = f'{lead}{region} : {level}'
        if score is not None:
            text += f' (score {score}/100)'
        if prob is not None:
            text += f', probabilité de sécheresse le mois prochain {prob}%'
        return f'{text}. Source : {source}.'
    if lang == 'ar':
        text = f'{lead}{region}: {level}'
        if score is not None:
            text += f' (الدرجة {score}/100)'
        if prob is not None:
            text += f'، واحتمال الجفاف الشهر القادم {prob}%'
        return f'{text}. المصدر: {source}.'
    text = f'{lead}{region}: {level}'
    if score is not None:
        text += f' (score {score}/100)'
    if prob is not None:
        text += f', probability of drought next month {prob}%'
    return f'{text}. Source: {source}.'


def _context_lines(facts, lang):
    """Data-driven context sentences, only for values that exist."""
    climate = facts.get('climate') or {}
    drought = facts.get('drought') or {}
    rs = facts.get('remote_sensing') or {}
    lines = []
    rain30 = climate.get('rain_30d_mm')
    clim = climate.get('rain_month_climatology_mm')
    deficit = climate.get('rain_month_deficit_pct')
    if rain30 is not None:
        if lang == 'fr':
            line = f'Pluie des 30 derniers jours : {rain30} mm'
            if clim is not None:
                line += f' (moyenne du mois : {clim} mm)'
            if deficit is not None:
                line += f', écart {deficit}%'
        elif lang == 'ar':
            line = f'أمطار آخر 30 يوماً: {rain30} مم'
            if clim is not None:
                line += f' (المعدل الشهري: {clim} مم)'
            if deficit is not None:
                line += f'، الفارق {deficit}%'
        else:
            line = f'Rainfall over the last 30 days: {rain30} mm'
            if clim is not None:
                line += f' (monthly average {clim} mm)'
            if deficit is not None:
                line += f', a {deficit}% deviation'
        lines.append(line + '.')

    balance = climate.get('water_balance_30d_mm')
    et0 = climate.get('et0_30d_mm')
    if balance is not None:
        if lang == 'fr':
            lines.append(f'Bilan hydrique sur 30 jours : {balance} mm '
                         f'(demande évaporative {et0} mm).')
        elif lang == 'ar':
            lines.append(f'الرصيد المائي خلال 30 يوماً: {balance} مم '
                         f'(الطلب التبخري {et0} مم).')
        else:
            lines.append(f'30-day water balance: {balance} mm '
                         f'(atmospheric demand {et0} mm).')

    spei3 = drought.get('spei_3month')
    if spei3 is not None:
        change = drought.get('spei_3month_change_3m')
        if lang == 'fr':
            line = f'SPEI-3 observé : {spei3}'
            if change is not None:
                line += f' (évolution sur 3 mois {change:+})'
        elif lang == 'ar':
            line = f'مؤشر SPEI-3 المرصود: {spei3}'
            if change is not None:
                line += f' (التغير خلال 3 أشهر {change:+})'
        else:
            line = f'Observed SPEI-3: {spei3}'
            if change is not None:
                line += f' (change over 3 months {change:+})'
        lines.append(line + '.')

    soil = rs.get('soil_moisture_pct')
    ndvi = rs.get('ndvi')
    if soil is not None or ndvi is not None:
        bits = []
        if soil is not None:
            bits.append(f'soil moisture {soil}%' if lang == 'en' else
                        f'humidité du sol {soil}%' if lang == 'fr' else
                        f'رطوبة التربة {soil}%')
        if ndvi is not None:
            bits.append(f'NDVI {ndvi}' if lang == 'en' else
                        f'NDVI {ndvi}' if lang == 'fr' else
                        f'NDVI {ndvi}')
        trend = rs.get('ndvi_trend_90d')
        if trend is not None:
            bits.append(f'90-day NDVI trend {trend:+}' if lang == 'en' else
                        f'tendance NDVI sur 90 jours {trend:+}' if lang == 'fr' else
                        f'اتجاه NDVI خلال 90 يوماً {trend:+}')
        prefix = ('Satellite: ' if lang == 'en' else
                  'Satellite : ' if lang == 'fr' else 'الأقمار الصناعية: ')
        lines.append(prefix + ', '.join(bits) + '.')

    requested = facts.get('requested_period')
    if requested and requested.get('rain_mm') is not None:
        if lang == 'fr':
            lines.append(f"Période demandée {requested.get('month')} "
                         f"{requested.get('year')} : {requested['rain_mm']} mm de pluie "
                         f"sur {requested.get('days')} jours.")
        elif lang == 'ar':
            lines.append(f"الفترة المطلوبة {requested.get('month')} "
                         f"{requested.get('year')}: {requested['rain_mm']} مم مطر "
                         f"خلال {requested.get('days')} يوماً.")
        else:
            lines.append(f"Requested period {requested.get('month')} "
                         f"{requested.get('year')}: {requested['rain_mm']} mm of rain "
                         f"over {requested.get('days')} days.")
    return lines


ORIENTATION = {
    'greeting': ('Hello. I am AgroAI, the agronomic assistant of this drought '
                 'platform. I can explain the current drought level for your region, '
                 'the 1-month outlook, irrigation timing, what to plant '
                 'now, how to save water, and what the satellite indicators show.',
                 "Bonjour. Je suis AgroAI, l'assistant agronomique de la plateforme. "
                 "Je peux expliquer le niveau de sécheresse actuel, la prévision à "
                 "1 mois, le calendrier d'irrigation, ce qu'il faut planter, "
                 "comment économiser l'eau et ce que montrent les indicateurs satellites.",
                 'مرحباً. أنا AgroAI، المساعد الزراعي لمنصة الجفاف. يمكنني شرح مستوى '
                 'الجفاف الحالي، وتوقع الشهر القادم، ومواعيد السقي، وما يمكن '
                 'زراعته الآن، وكيفية ترشيد الماء، وما تُظهره مؤشرات الأقمار الصناعية.'),
    'help': ('I answer from this platform\'s own measurements: SPEI drought indices, '
             'rainfall, temperature, evapotranspiration, satellite vegetation and soil '
             'moisture, plus crop-type forecasts. Pick a region and ask about drought '
             'risk, irrigation, planting, or water saving.',
             "Je réponds à partir des mesures de la plateforme : indices de sécheresse "
             "SPEI, pluie, température, évapotranspiration, végétation satellite et "
             "humidité du sol, ainsi que les prévisions par culture. Choisissez une "
             "région et interrogez-moi sur le risque, l'irrigation ou l'économie d'eau.",
             'أجيب من قياسات المنصة نفسها: مؤشرات SPEI، والأمطار، والحرارة، '
             'والتبخر-النتح، والغطاء النباتي ورطوبة التربة من الأقمار الصناعية. '
             'اختر منطقة واسأل عن خطر الجفاف أو السقي أو الزراعة أو ترشيد الماء.'),
}


def _knowledge_text(question, facts, lang):
    text = (question or '').lower()
    for key, pack in KNOWLEDGE.items():
        if key in text:
            quote = _loc(pack, lang)
            break
    else:
        quote = _loc(KNOWLEDGE['spei'], lang)
    context = _context_lines(facts, lang)
    return ' '.join([quote] + context[:2])


# ---------------------------------------------------------------------------
# WEBSITE GUIDE: structured sub-topic answers + smart dispatcher
# ---------------------------------------------------------------------------
# Each entry: (en_answer, fr_answer, ar_answer)
_WG = {
    'overview': (
        "APWRS / ABCDry is an advanced agricultural drought monitoring, climate forecasting, "
        "and decision-support platform for Mediterranean farming basins in Tunisia (Ichkeul, "
        "Medjerda, Kairouan, Siliana, Cap Bon, Zaghouan, Bizerte, Jendouba, Beja, and more). "
        "It combines 30 years of satellite data, ground weather stations, and machine-learning "
        "models to help farmers, agronomists, and water-resource managers anticipate water stress, "
        "optimise irrigation, and prevent crop failure. "
        "Main pages: Dashboard (/dashboard/), SPEI Outlook (/analysis/spei-outlook/), "
        "Historical Trends (/historical/), Data Ingestion (/data-ingestion/), "
        "Metrics Browser (/metrics/browser/), Calculations (/analysis/calculations/), "
        "and Data Exports (/analysis/).",
        "APWRS / ABCDry est une plateforme avancée de surveillance de la sécheresse, de "
        "prévision climatique et d'aide à la décision agricole pour les bassins méditerranéens "
        "tunisiens (Ichkeul, Medjerda, Kairouan, Cap Bon, etc.). Elle combine 30 ans de données "
        "satellitaires, des stations météo de terrain et des modèles ML pour anticiper le stress "
        "hydrique et optimiser l'irrigation. "
        "Pages principales : Tableau de bord (/dashboard/), Prévisions SPEI (/analysis/spei-outlook/), "
        "Tendances historiques (/historical/), Ingestion de données (/data-ingestion/), "
        "Navigateur de métriques (/metrics/browser/), Formules (/analysis/calculations/), "
        "et Exports (/analysis/).",
        "منصة APWRS / ABCDry هي نظام متقدم لمراقبة الجفاف والتنبؤ بالمناخ ودعم القرار الزراعي "
        "للأحواض الزراعية المتوسطية في تونس (إشكل، مجردة، القيروان، الشمال الشرقي، وغيرها). "
        "تجمع بين 30 عاماً من البيانات الفضائية، ومحطات الطقس الأرضية، ونماذج التعلم الآلي "
        "لمساعدة المزارعين على تفادي الإجهاد المائي وتحسين الري. "
        "الصفحات الرئيسية: لوحة التحكم (/dashboard/)، توقعات SPEI (/analysis/spei-outlook/)، "
        "السجلات التاريخية (/historical/)، رفع البيانات (/data-ingestion/)، "
        "مستعرض المقاييس (/metrics/browser/)، المعادلات (/analysis/calculations/)، والتصدير (/analysis/).",
    ),
    'dashboard': (
        "The Interactive Dashboard (/dashboard/) is the command centre of the platform. "
        "It shows: (1) a Leaflet colour-coded basin map (Green = Normal 0–25, Yellow = Moderate 26–50, "
        "Orange = Severe 51–75, Red = Extreme 76–100); (2) live weather dials for 30-day rainfall, "
        "ET₀, temperature, humidity, wind, and solar radiation; (3) a composite Drought Risk Score "
        "gauge (0–100); and (4) a region selector to switch instantly between Tunisian agricultural basins. "
        "The AgroAI chat bubble is also accessible from every page.",
        "Le Tableau de bord interactif (/dashboard/) est le centre de contrôle de la plateforme. "
        "Il affiche : (1) une carte Leaflet des bassins avec code couleur (Vert = Normal 0–25, "
        "Jaune = Modéré 26–50, Orange = Sévère 51–75, Rouge = Extrême 76–100) ; "
        "(2) des jauges météo en temps réel (pluie 30j, ET₀, température, humidité, vent, rayonnement) ; "
        "(3) un score de risque de sécheresse composite (0–100) ; "
        "(4) un sélecteur de région pour passer instantanément d'un bassin à l'autre.",
        "لوحة التحكم التفاعلية (/dashboard/) هي مركز القيادة للمنصة. "
        "تعرض: (1) خريطة Leaflet مرمّزة بالألوان (أخضر = طبيعي 0–25، أصفر = متوسط 26–50، "
        "برتقالي = شديد 51–75، أحمر = بالغ 76–100)؛ (2) مؤشرات طقس فورية للأمطار وET₀ والحرارة؛ "
        "(3) مقياس درجة خطر الجفاف المركّب (0–100)؛ "
        "(4) قائمة لاختيار المنطقة والتنقل بين الأحواض الزراعية فوراً.",
    ),
    'spei_outlook': (
        "The SPEI Outlook page (/analysis/spei-outlook/) provides machine-learning drought forecasts "
        "from 1 to 6 months ahead. It shows multi-scale SPEI curves (SPEI-1 meteorological, SPEI-3 "
        "agricultural, SPEI-6, SPEI-12 hydrological, SPEI-24 deep groundwater), the next-month drought "
        "probability, and the top driving factors (rainfall deficit, temperature anomaly, humidity). "
        "The ML ensemble combines Random Forest, LightGBM, and XGBoost models trained on 30 years of data.",
        "La page Prévisions SPEI (/analysis/spei-outlook/) fournit des prévisions de sécheresse ML "
        "de 1 à 6 mois. Elle affiche les courbes SPEI multi-échelles (SPEI-1 météo, SPEI-3 agricole, "
        "SPEI-6, SPEI-12 hydrologique, SPEI-24 eaux souterraines), la probabilité de sécheresse "
        "et les facteurs déterminants. L'ensemble ML combine Random Forest, LightGBM et XGBoost.",
        "صفحة توقعات SPEI (/analysis/spei-outlook/) تقدم تنبؤات التعلم الآلي للجفاف من شهر إلى 6 أشهر. "
        "تعرض منحنيات SPEI متعددة المقاييس (SPEI-1 الجوي، SPEI-3 الزراعي، SPEI-12 الهيدرولوجي)، "
        "واحتمالية الجفاف للشهر القادم، وأهم العوامل المحركة للخطر. "
        "يجمع النظام نماذج Random Forest وLightGBM وXGBoost مدربة على 30 عاماً من البيانات.",
    ),
    'upload': (
        "To upload data, go to Data Ingestion (/data-ingestion/). "
        "Drag and drop your .xlsx or .csv file into the upload zone (or click to browse). "
        "The system automatically normalises headers, parses dates, detects duplicates, validates rows, "
        "and imports the data. You can download blank sample templates from the same page to match "
        "the expected column layout. Import logs show successfully imported rows and any validation warnings.",
        "Pour importer des données, allez sur Ingestion de données (/data-ingestion/). "
        "Glissez-déposez votre fichier .xlsx ou .csv dans la zone d'upload (ou cliquez pour parcourir). "
        "Le système normalise automatiquement les en-têtes, analyse les dates, détecte les doublons, "
        "valide les lignes et importe les données. Téléchargez des modèles vierges sur la même page. "
        "Les journaux d'importation affichent les lignes importées et les avertissements.",
        "لرفع البيانات، انتقل إلى صفحة استيراد البيانات (/data-ingestion/). "
        "اسحب وأسقط ملف .xlsx أو .csv في منطقة الرفع، أو انقر للاستعراض. "
        "يقوم النظام تلقائياً بتوحيد الأعمدة وتحليل التواريخ واكتشاف التكرارات والتحقق من الصفوف وحفظها. "
        "يمكنك تنزيل نماذج Excel جاهزة من نفس الصفحة. "
        "سجلات الاستيراد تُظهر الصفوف المستوردة بنجاح وأي تحذيرات تحقق.",
    ),
    'export': (
        "To export data: go to Analysis (/analysis/) and click Export CSV (/api/analysis-export/) "
        "or Export Excel (/api/historical-export/) for full multi-year reports. "
        "For raw metric tables, go to Metrics Browser (/metrics/browser/), select a category "
        "(Soil, Climate, Drought, etc.), and click Export to Excel on that page. "
        "Executive PDF summaries can also be generated from the Analysis page.",
        "Pour exporter des données : allez sur Analyse (/analysis/) et cliquez sur Export CSV "
        "(/api/analysis-export/) ou Export Excel (/api/historical-export/) pour des rapports complets. "
        "Pour les tables brutes, allez sur Navigateur de métriques (/metrics/browser/), "
        "choisissez une catégorie et cliquez sur Exporter vers Excel. "
        "Des rapports PDF exécutifs sont aussi disponibles depuis la page Analyse.",
        "لتصدير البيانات: انتقل إلى صفحة التحليل (/analysis/) وانقر على تصدير CSV (/api/analysis-export/) "
        "أو تصدير Excel (/api/historical-export/) للحصول على تقارير كاملة متعددة السنوات. "
        "لجداول المقاييس الخام، انتقل إلى مستعرض المقاييس (/metrics/browser/)، "
        "اختر الفئة (تربة، مناخ، جفاف...) وانقر على تصدير إلى Excel. "
        "تقارير PDF تنفيذية متاحة أيضاً من صفحة التحليل.",
    ),
    'metrics': (
        "The Metrics Browser (/metrics/browser/) lets you view and manage all platform data. "
        "Categories include: Soil Metrics (/metrics/soil/) — moisture, pH, N/P/K, organic matter; "
        "Climate Metrics (/metrics/climate/) — precipitation, ET₀, temperature, humidity, wind, solar; "
        "Drought Indices (/metrics/drought/) — SPEI-1/3/6/12/24, SPI, PDSI; "
        "Agricultural Metrics (/metrics/agricultural/) — crop types, area, stage, irrigation, yield; "
        "Remote Sensing (/metrics/remote-sensing/) — NDVI, NDWI, VCI, LST; "
        "Hydrology (/metrics/hydrology/) — river discharge, groundwater, dam storage. "
        "Use the + Add button to add entries, the Edit icon to modify, and Export to Excel to download.",
        "Le Navigateur de métriques (/metrics/browser/) permet de consulter et gérer toutes les données. "
        "Catégories : Métriques sol (/metrics/soil/) — humidité, pH, N/P/K ; "
        "Métriques climat (/metrics/climate/) — pluie, ET₀, température ; "
        "Indices de sécheresse (/metrics/drought/) — SPEI-1/3/6/12/24, SPI, PDSI ; "
        "Métriques agricoles — cultures, surfaces, stade, rendement ; "
        "Télédétection — NDVI, VCI, LST ; Hydrologie — débit, nappes, barrages. "
        "Bouton + Ajouter pour saisir, icône Modifier pour éditer, et Exporter pour télécharger.",
        "مستعرض المقاييس (/metrics/browser/) يتيح عرض وإدارة جميع بيانات المنصة. "
        "الفئات تشمل: مقاييس التربة (رطوبة، pH، N/P/K)؛ "
        "المناخ (أمطار، ET₀، حرارة، رطوبة، رياح)؛ "
        "مؤشرات الجفاف (SPEI-1/3/6/12/24، SPI، PDSI)؛ "
        "الزراعة (أنواع المحاصيل، المساحات، مرحلة النمو، الري، المردود)؛ "
        "الاستشعار عن بعد (NDVI، VCI، LST)؛ الهيدرولوجيا (تدفق الأنهار، المياه الجوفية، السدود). "
        "زر + إضافة لإدراج سجلات، أيقونة التعديل للتحرير، وزر التصدير لتنزيل Excel.",
    ),
    'calculations': (
        "The Calculations page (/analysis/calculations/) explains all scientific formulas used: "
        "• Hargreaves-Samani ET₀: 0.0023 × Rₐ × (Tmean + 17.8) × √(Tmax − Tmin) "
        "• FAO-56 Penman-Monteith ET₀: combines net radiation, soil heat flux, temperature, wind, and vapour pressure deficit. "
        "• Climatic Water Balance: D = P − ET₀ "
        "• SPEI: fits a 3-parameter log-logistic distribution to D, then converts to a standard normal score. "
        "Use this page to understand exactly how every index on the dashboard is computed.",
        "La page Formules et calculs (/analysis/calculations/) explique toutes les formules scientifiques : "
        "• ET₀ Hargreaves-Samani : 0.0023 × Rₐ × (Tmoy + 17.8) × √(Tmax − Tmin) "
        "• ET₀ FAO-56 Penman-Monteith : combine rayonnement, flux de chaleur, température, vent et déficit de pression. "
        "• Bilan hydrique climatique : D = P − ET₀ "
        "• SPEI : ajustement log-logistique sur D, puis conversion en score normal standard.",
        "صفحة المعادلات (/analysis/calculations/) تشرح جميع الصيغ العلمية المستخدمة: "
        "• ET₀ هارغريفز-ساماني: 0.0023 × Rₐ × (Tوسط + 17.8) × √(Tmax − Tmin) "
        "• ET₀ فاو-56 بينمان-مونتيث: يجمع الإشعاع والحرارة والرياح وعجز الضغط البخاري. "
        "• الميزان المائي: D = P − ET₀ "
        "• SPEI: يُطبّق توزيع لوغاريتمي على D ويحوله إلى نقاط بمتوسط صفر وانحراف معياري واحد.",
    ),
    'assistant': (
        "The AgroAI Assistant is available as a floating chat bubble in the bottom-right corner of every "
        "page, or as a full page at /assistant/. You can ask it anything about: the website and how to "
        "navigate it, agronomic advice (irrigation, planting, drought outlook), and scientific concepts "
        "(SPEI, NDVI, ET₀). It speaks English, French, and Arabic automatically. "
        "Click the microphone icon to speak your question by voice.",
        "L'assistant AgroAI est accessible via la bulle de chat en bas à droite de chaque page, "
        "ou en page complète sur /assistant/. Posez-lui des questions sur le site, la navigation, "
        "les conseils agronomiques (irrigation, semis, sécheresse) et les concepts scientifiques. "
        "Il répond en anglais, français ou arabe automatiquement. "
        "Cliquez sur l'icône microphone pour poser une question vocalement.",
        "مساعد AgroAI متاح كفقاعة دردشة في أسفل يمين كل صفحة، أو كصفحة كاملة على /assistant/. "
        "يمكنك سؤاله عن: كيفية استخدام الموقع، النصائح الزراعية (ري، زراعة، توقعات الجفاف)، "
        "والمفاهيم العلمية (SPEI، NDVI، ET₀). يتحدث عربياً وفرنسياً وإنجليزياً تلقائياً. "
        "انقر على أيقونة الميكروفون للسؤال بالصوت.",
    ),
    'sensors': (
        "The IoT Sensor Network (/api/sensors/) shows active ground sensors, their GPS coordinates, "
        "battery status, and telemetry history (temperature, soil moisture, rainfall). "
        "Automated telemetry loggers (LoRaWAN, 4G, Campbell Scientific) push data via the REST "
        "ingestion endpoint at /api/ingest/.",
        "Le réseau de capteurs IoT (/api/sensors/) affiche les capteurs actifs, leurs coordonnées GPS, "
        "l'état de la batterie et l'historique de télémétrie. Les enregistreurs automatiques "
        "(LoRaWAN, 4G, Campbell Scientific) envoient les données via /api/ingest/.",
        "شبكة مستشعرات إنترنت الأشياء (/api/sensors/) تعرض المستشعرات النشطة وإحداثياتها "
        "وحالة البطارية وسجل القياسات (حرارة، رطوبة تربة، أمطار). "
        "أجهزة التسجيل الآلي (LoRaWAN، 4G) ترسل البيانات عبر /api/ingest/.",
    ),
    'map': (
        "The interactive Leaflet map on the Dashboard (/dashboard/) colour-codes each Tunisian "
        "agricultural basin by its current Drought Risk Score: Green (0–25 Normal), Yellow (26–50 "
        "Moderate), Orange (51–75 Severe), Red (76–100 Extreme). Click any basin marker to drill into "
        "its detailed weather and drought data. Use the Region Selector dropdown to switch regions.",
        "La carte Leaflet interactive du Tableau de bord (/dashboard/) code chaque bassin tunisien "
        "par son score de risque : Vert (0–25 Normal), Jaune (26–50 Modéré), Orange (51–75 Sévère), "
        "Rouge (76–100 Extrême). Cliquez sur un marqueur pour voir les détails. "
        "Utilisez le sélecteur de région pour changer de bassin.",
        "خريطة Leaflet التفاعلية في لوحة التحكم (/dashboard/) ترمّز كل حوض زراعي تونسي بلون حسب "
        "درجة خطر الجفاف: أخضر (0–25 طبيعي)، أصفر (26–50 متوسط)، برتقالي (51–75 شديد)، "
        "أحمر (76–100 بالغ). انقر على أي علامة للاطلاع على التفاصيل. "
        "استخدم قائمة تحديد المنطقة للتنقل بين الأحواض.",
    ),
    'historical': (
        "The Historical Trends page (/historical/) provides 30-year climatological baselines "
        "from 1996 to the present day. It includes monthly precipitation anomalies and deficits "
        "compared to the 30-year normal, historical drought chronology heatmaps, and multi-year "
        "timelines showing past drought episodes across all Tunisian regions.",
        "La page Tendances historiques (/historical/) fournit des données climatologiques sur 30 ans "
        "(depuis 1996). Elle inclut les anomalies et déficits pluviométriques mensuels par rapport "
        "à la normale, les cartes thermiques de chronologie des sécheresses passées, et les chronologies "
        "pluriannuelles des épisodes de sécheresse par région.",
        "صفحة السجلات التاريخية (/historical/) توفر بيانات مناخية لـ 30 عاماً (منذ 1996). "
        "تتضمن شذوذات الأمطار الشهرية مقارنةً بالمعدل الطبيعي، وخرائط حرارية لأحداث الجفاف التاريخية، "
        "وجداول زمنية متعددة السنوات لكافة مناطق الأحواض التونسية.",
    ),
    'login': (
        "Users log in at /login/. The platform uses role-based access control: Farmer, Agronomist, "
        "Manager, and Administrator roles. User and account management is handled via the Admin Panel "
        "at /admin-panel/. Administrators can create accounts, assign roles, and manage access.",
        "Les utilisateurs se connectent sur /login/. La plateforme utilise un contrôle d'accès basé "
        "sur les rôles : Agriculteur, Agronome, Gestionnaire, Administrateur. La gestion des comptes "
        "se fait via le Panneau d'administration (/admin-panel/).",
        "يتم تسجيل الدخول عبر /login/. تستخدم المنصة التحكم في الوصول المبني على الأدوار: "
        "مزارع، زراعي، مدير، مسؤول. تتم إدارة الحسابات عبر لوحة الإدارة (/admin-panel/).",
    ),
    'datasets': (
        "APWRS draws from four data sources: "
        "(1) CHIRPS 0.05° gridded daily rainfall (Climate Hazards Group); "
        "(2) ECMWF ERA5 reanalysis for temperature, wind, humidity, and solar radiation; "
        "(3) Google Earth Engine MODIS and Sentinel-2 for NDVI, VCI, and Land Surface Temperature; "
        "(4) Local ground weather stations and deployed IoT field sensors. "
        "Historical records span from 1 January 1996 to the present day.",
        "APWRS utilise quatre sources de données : (1) CHIRPS pluie journalière 0.05° ; "
        "(2) ECMWF ERA5 pour température, vent, humidité et rayonnement ; "
        "(3) Google Earth Engine (MODIS et Sentinel-2) pour NDVI, VCI et LST ; "
        "(4) Stations météo locales et capteurs IoT déployés sur le terrain. "
        "Les données historiques couvrent du 1er janvier 1996 à aujourd'hui.",
        "تعتمد APWRS على أربعة مصادر بيانات: (1) أمطار CHIRPS اليومية بدقة 0.05°؛ "
        "(2) إعادة تحليل ECMWF ERA5 للحرارة والرياح والرطوبة والإشعاع الشمسي؛ "
        "(3) Google Earth Engine (MODIS وSentinel-2) لمؤشرات NDVI وVCI ودرجة حرارة السطح؛ "
        "(4) محطات الطقس الأرضية ومستشعرات IoT الميدانية. "
        "السجلات التاريخية تمتد من 1 يناير 1996 حتى اليوم.",
    ),
}

# Map of question keywords → sub-topic key
_WG_RULES = [
    ('upload', ['upload', 'ingest', 'import', 'televerser', 'rafe', 'importer', 'fichier',
                'رفع', 'استيراد', 'تحميل ملف', 'file', 'xlsx', 'csv', 'excel']),
    ('export', ['export', 'download', 'telecharger', 'rapport', 'report', 'pdf',
                'تصدير', 'تنزيل', 'تقرير']),
    ('spei_outlook', ['spei outlook', 'outlook', 'forecast', 'prevision', 'prediction',
                      'ml forecast', 'next month', 'probability', 'probabilite',
                      'توقعات', 'تنبؤ', 'الشهر القادم']),
    ('dashboard', ['dashboard', 'tableau de bord', 'risk map', 'risk score', 'gauge',
                   'weather dial', 'لوحة', 'خريطة', 'مقياس']),
    ('map', ['map', 'carte', 'basin', 'bassin', 'colour', 'color', 'green', 'red',
             'خريطة', 'حوض', 'لون']),
    ('metrics', ['metric', 'soil', 'climate', 'drought index', 'soil moisture',
                 'add entry', 'edit entry', 'delete', 'browser', 'navigateur',
                 'مقاييس', 'تربة', 'مناخ', 'مستعرض']),
    ('calculations', ['formula', 'formule', 'calculation', 'calcul', 'hargreaves',
                      'penman', 'water balance', 'bilan', 'معادلة', 'حساب', 'هارغريفز']),
    ('assistant', ['assistant', 'chatbot', 'agroai', 'chat', 'voice', 'microphone',
                   'مساعد', 'دردشة', 'صوت']),
    ('sensors', ['sensor', 'iot', 'capteur', 'telemetry', 'lorawan', 'مستشعر', 'حساس']),
    ('historical', ['history', 'historical', 'historique', 'past', 'trend', '1996',
                    '30 year', '30-year', 'تاريخي', 'السجلات', 'ماضي']),
    ('login', ['login', 'account', 'user', 'role', 'admin', 'connexion', 'compte',
               'تسجيل', 'حساب', 'مستخدم', 'مسؤول']),
    ('datasets', ['data source', 'chirps', 'era5', 'ecmwf', 'sentinel', 'modis',
                  'earth engine', 'dataset', 'donnees source', 'مصدر البيانات']),
]

WEBSITE_ORIENTATION = {
    'en': _WG['overview'][0],
    'fr': _WG['overview'][1],
    'ar': _WG['overview'][2],
}


def _website_guide_answer(question, lang):
    """Match the question to the most specific website guide sub-topic.

    Falls back to the full platform overview when no specific topic is matched.
    """
    q = question.lower() if question else ''
    idx = {'en': 0, 'fr': 1, 'ar': 2}.get(lang, 0)
    for topic, keywords in _WG_RULES:
        if any(kw in q for kw in keywords):
            return _WG[topic][idx]
    return _WG['overview'][idx]


def _website_guide_context():
    """Return a compact, LLM-friendly reference block from the PLATFORM_GUIDE.

    This is injected into the LLM prompt for every website_guide question so
    the model has grounded documentation even when RAG retrieval is empty.
    """
    try:
        from pathlib import Path
        from django.conf import settings as _settings
        guide_path = Path(getattr(_settings, 'BASE_DIR', Path.cwd())) / 'docs' / 'PLATFORM_GUIDE.md'
        if guide_path.exists():
            text = guide_path.read_text(encoding='utf-8', errors='ignore')
            # Trim to 3000 chars to fit in prompt
            return text[:3000]
    except Exception:
        pass
    return ''


def fallback_answer(facts, intent, rules, lang='en', question=''):
    """Deterministic, data-rich answer used whenever the LLM is unusable."""
    if intent == 'website_guide':
        return _website_guide_answer(question, lang)
    parts = [_headline(facts, lang)]
    if intent == 'knowledge':
        parts.append(_knowledge_text(question, facts, lang))
    elif intent in ('greeting', 'help'):
        parts.append(_loc(ORIENTATION[intent], lang))
    else:
        parts.extend(_context_lines(facts, lang))
    action = rules.get('action')
    if action and action != 'inform':
        parts.append(_loc(ACTIONS.get(action, ACTIONS['inform']), lang))
    note = rules.get('priority_note')
    if note:
        prefix = {'en': 'Technical note: ', 'fr': 'Note technique : ',
                  'ar': 'ملاحظة فنية: '}.get(lang, 'Technical note: ')
        parts.append(prefix + note + '.')
    warnings = facts.get('data_warnings') or []
    if warnings:
        prefix = {'en': 'Data note: ', 'fr': 'Données : ',
                  'ar': 'بيانات: '}.get(lang, 'Data note: ')
        parts.append(prefix + '; '.join(warnings) + '.')
    return ' '.join(part for part in parts if part)


def _json_safe(value):
    """Make facts JSON-serialisable and hide internal keys."""
    from datetime import date, datetime
    from decimal import Decimal
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items() if not k.startswith('_')}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def data_signature(facts):
    """Identifies the data snapshot an answer was built from (cache safety)."""
    return '|'.join(str(x) for x in (
        facts.get('measured_until'), facts.get('climate_rows'),
        (facts.get('drought') or {}).get('as_of'),
        (facts.get('drought') or {}).get('spei_3month'),
        (facts.get('forecast') or {}).get('generated_at'),
        (facts.get('forecast') or {}).get('feature_month'),
        (facts.get('summary') or {}).get('risk_score'),
        facts.get('stations_aggregated'),
    ))


SYSTEM_PROMPT = """You are AgroAI, the intelligent assistant for the APWRS / ABCDry drought and agricultural platform.
Your objective is to provide helpful, natural, and conversational explanations based on FACTS and REFERENCE documentation.

Key Instructions:
1. Conciseness & Precision:
   - Provide a clear, natural explanation in 2 to 3 complete sentences. Do not ramble, repeat the question, or recite data tables.
   - Answer ONLY what the user asked. Do not dump unrequested historical metrics, date ranges, or row counts.
2. Anti-Leak & Clean Output:
   - NEVER output internal system labels or prompt tags (such as 'REFERENCE', 'Context', 'FACTS', 'relevance', or 'source:').
   - NEVER output SQL queries, bash commands, database table names, or internal database row counts.
3. Grounding:
   - For regional agronomy, drought assessments, and weather: do not invent numbers. Numerical values must match the provided REGIONAL FACTS. Never contradict the drought level, risk score, or recommended action.
   - For website, platform, and navigation questions: use the documentation to explain the platform's features, tools, pages, and how-to procedures clearly and step-by-step. Do not mention regional drought status unless asked.
4. Language:
   - Write in {language}. Keep the tone professional, friendly, and practical."""


def _facts_for_prompt(facts, intent):
    """Concise, relevant facts representation to prevent data dumps and hallucination."""
    summary = facts.get('summary') or {}
    climate = facts.get('climate') or {}
    drought = facts.get('drought') or {}
    remote = facts.get('remote_sensing') or {}
    clean = {
        'region': facts.get('region'),
        'risk_score': summary.get('risk_score'),
        'risk_level': summary.get('risk_level'),
        'probability_drought_next_month_pct': summary.get('probability_drought_next_month_pct'),
        'next_month_verdict': summary.get('next_month_verdict'),
        'recent_30d_rain_mm': climate.get('rain_30d_mm'),
        'recent_30d_mean_temp_c': climate.get('tmean_30d_c'),
        'recent_30d_et0_mm': climate.get('et0_30d_mm'),
        'spei_3month': drought.get('spei_3month'),
        'vegetation_ndvi': remote.get('ndvi'),
        'soil_moisture_pct': remote.get('soil_moisture_pct'),
    }
    return {k: v for k, v in clean.items() if v is not None}


def llm_answer(question, facts, rules, intent, lang, history=None, repair_bad=None,
               context=None):
    """Ask the local model to explain the (already computed) facts.

    Returns (text_or_None, model_name). Any failure returns None so the
    caller falls back to the deterministic answer. ``repair_bad`` lists
    numbers from a previous attempt that were not found in the facts.
    ``context`` is the retrieved reference material (see :mod:`retrieval`).
    """
    model = resolve_model()
    if not model:
        return None, ''
    cfg = llm_config()
    action = rules.get('action')
    action_sentence = (_loc(ACTIONS.get(action), 'en')
                       if action and action != 'inform' else '')
    verdict_code = (facts.get('summary') or {}).get('next_month_verdict')
    verdict = (_loc(VERDICT[verdict_code], 'en').rstrip(';')
               if verdict_code in VERDICT else '')
    instruction = ''
    if repair_bad:
        instruction = ('\n\nCORRECTION REQUIRED: your previous answer used these '
                       'numbers which are NOT in FACTS: '
                       + ', '.join(str(x) for x in repair_bad)
                       + '. Rewrite the answer using only numbers copied from FACTS.')
    messages = [{'role': 'system',
                 'content': SYSTEM_PROMPT.format(language=LANGUAGES[lang])}]
    for turn in list(history or [])[-6:]:
        content = (turn.get('content') or '').strip()
        if not content:
            continue
        role = 'assistant' if turn.get('role') in ('assistant', 'ai', 'bot') else 'user'
        messages.append({'role': role, 'content': content[:1500]})
    context_block = ''
    if context:
        try:
            from . import retrieval
            context_block = retrieval.prompt_block(context)
        except Exception as exc:                   # noqa: BLE001
            logger.warning('assistant: retrieval context unavailable (%s)', exc)
    if intent == 'website_guide':
        guide_text = _website_guide_context()
        specific = _website_guide_answer(question, lang)
        facts_block = (
            'ACTIVE REGION: ' + str(facts.get('region') or 'None') + '\n\n'
            'SPECIFIC GUIDE SECTION (answer this question using it):\n' + specific + '\n\n'
            + ('FULL PLATFORM GUIDE (additional reference):\n' + guide_text[:2000]
               if guide_text else '')
        )
    else:
        facts_block = 'REGIONAL FACTS:\n' + json.dumps(_facts_for_prompt(facts, intent), ensure_ascii=False)
    user_parts = [
        facts_block,
        f'RECOMMENDED ACTION: "{action_sentence or "(none - just inform)"}"',
        f'NEXT MONTH VERDICT: {verdict or "(not available)"}',
        f'INTENT: {intent}',
    ]
    if context_block:
        user_parts.append(context_block)
    if instruction:
        user_parts.append(instruction)
    user_parts.append(f'QUESTION: {question}')
    messages.append({'role': 'user', 'content': '\n\n'.join(user_parts)})
    try:
        resp = requests.post(
            f"{cfg['url']}/api/chat",
            json={'model': model, 'messages': messages, 'stream': False,
                  'keep_alive': cfg['keep_alive'],
                  'options': {'temperature': cfg['temperature'],
                              'num_ctx': cfg['num_ctx'],
                              'num_predict': 200}},
            timeout=cfg['timeout'])
        if resp.status_code != 200:
            logger.warning('assistant: Ollama returned HTTP %s for model %s',
                           resp.status_code, model)
            return None, model
        text = ((resp.json().get('message') or {}).get('content') or '').strip()
        return (text or None), model
    except Exception as exc:                       # noqa: BLE001
        logger.warning('assistant: LLM call failed with model %s (%s: %s)',
                       model, type(exc).__name__, exc)
        return None, model


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #
def _retrieval(question, lang, crop, region_id):
    """Retrieved reference context for this question, plus its source list.

    Retrieval is strictly additive: any failure returns an empty context so
    the answer is produced from the deterministic facts alone.
    """
    empty = ({'documents': [], 'data': [], 'numbers': [], 'signature': '',
              'dense': False, 'chunks': 0}, [])
    try:
        from . import retrieval
        if not retrieval.rag_config()['enabled']:
            return empty
        context = retrieval.gather(question, lang=lang, crop=crop,
                                   region=_resolve_region(region_id))
        return context, retrieval.sources_for(context)
    except Exception as exc:                       # noqa: BLE001
        logger.warning('assistant: retrieval skipped (%s: %s)', type(exc).__name__, exc)
        return empty


def _clarify(kind, lang, regions=None, question='', understood=None):
    """A deterministic clarifying question, or None."""
    try:
        text, options = nlu.clarification(kind, lang, regions=regions,
                                          question=question)
    except Exception as exc:                       # noqa: BLE001
        logger.warning('assistant: clarification failed (%s)', exc)
        return None, None
    if not text:
        return None, None
    # Keep whatever was understood: the next turn must not have to repeat the crop.
    understood = understood or {}
    understood_region = understood.get('region')
    region_name = (getattr(understood_region, 'name', None)
                   or understood.get('region_name'))
    return {
        'answer': text,
        'intent': 'clarification',
        'crop': understood.get('crop'),
        'region': region_name,
        'lang': lang,
        'from_cache': False,
        'engine': 'clarification',
        'engine_reason': f'asked for the {kind} before answering',
        'model': None,
        'rag': {'enabled': False, 'dense': False, 'documents': 0, 'data': 0},
        'sources': [],
        'suggestions': options,
        'clarification': {'kind': kind, 'options': options,
                          'understood_intent': understood.get('intent')},
        'details': {},
    }, options


def answer_question(question, region_id=None, crop=None, lang='en', use_llm=True,
                    history=None, conversation=None):
    """Full pipeline: understanding -> facts -> rules -> grounded LLM."""
    import hashlib

    detected = detect_language(question)
    if detected:
        lang = detected
    else:
        lang = lang if lang in LANGUAGES else 'en'
    try:
        regions = list(Region.objects.all())
    except Exception:                              # noqa: BLE001
        regions = []
    understood = nlu.resolve(question, history=history, explicit=conversation,
                             region_id=region_id, crop=crop, regions=regions)
    crop = understood['crop']
    intent = understood['intent']
    if understood['region'] is not None:
        region_id = understood['region'].id
    else:
        region_id = region_id

    context, sources = _retrieval(question, lang, crop, region_id)
    best_relevance = max([hit.get('relevance', 0.0)
                          for hit in context.get('documents') or []] or [0.0])
    kind = nlu.needs_clarification(
        intent, region_id=region_id, parsed_region=understood['region'],
        history=history, regions=regions, best_relevance=best_relevance,
        enabled=bool(getattr(settings, 'ASSISTANT_CLARIFY', True)))
    if kind:
        payload, _ = _clarify(kind, lang, regions, question=question,
                              understood=understood)
        if payload:
            return payload

    facts = build_facts(region_id=region_id, crop=crop, question=question)
    rules = apply_rules(facts, intent, crop)
    summary = facts.get('summary') or {}
    region_name = facts.get('region')

    template = fallback_answer(facts, intent, rules, lang, question)
    model = resolve_model() if use_llm else ''
    engine = 'llm' if model else 'template'
    digest = hashlib.md5(
        f'{intent}|{region_name}|{lang}|{model}|{data_signature(facts)}'
        f'|{context.get("signature", "")}'
        f'|{"|".join(sorted(hit["source"] for hit in sources))}'.encode()).hexdigest()

    key = f'{ENGINE_VERSION}:{engine}:{digest}'
    cached = cache.get(key)
    from_cache = cached is not None
    answer = cached
    reason = None
    extra = context.get('numbers') or None

    if answer is None:
        if engine == 'llm':
            text, _ = llm_answer(question, facts, rules, intent, lang, history,
                                 context=context)
            if intent == 'website_guide':
                unverified = []
            else:
                unverified = validate_numbers(text, facts, extra=extra) if text else []
                if text and unverified:
                    # one repair attempt: tell the model which numbers were invented
                    text, _ = llm_answer(question, facts, rules, intent, lang, history,
                                         repair_bad=unverified, context=context)
                    unverified = validate_numbers(text, facts, extra=extra) if text else []
            if not text:
                reason = 'LLM unavailable or call failed (see server log)'
            elif unverified:
                reason = f'LLM numbers not traceable to facts: {unverified[:5]}'
                logger.warning('assistant: rejected LLM answer - %s', reason)
            elif len(text.split()) < 6:
                reason = 'LLM reply too short to be useful'
                logger.warning('assistant: rejected LLM answer - %s', reason)
            else:
                answer = text
        if answer is None:
            engine = 'template'
            key = f'{ENGINE_VERSION}:template:{digest}'
            cached_template = cache.get(key)
            from_cache = cached_template is not None
            answer = cached_template or template
        cache.set(key, answer, LLM_CACHE_TTL if engine == 'llm' else TPL_CACHE_TTL)

    answer = _tidy(answer)

    prob_pct = summary.get('probability_drought_next_month_pct')
    return {
        'answer': answer,
        'intent': intent,
        'crop': crop,
        'region': region_name,
        'lang': lang,
        'from_cache': from_cache,
        'engine': engine,
        'engine_reason': reason,
        'model': model or None,
        'rag': {
            'enabled': bool(context.get('chunks')),
            'dense': bool(context.get('dense')),
            'documents': len(context.get('documents') or []),
            'data': len(context.get('data') or []),
        },
        'sources': sources,
        'understood': {
            'crop': crop,
            'intent': intent,
            'followup': bool(understood.get('followup')),
            'inherited': understood.get('inherited') or {},
        },
        'facts': {
            'level': summary.get('risk_level'),
            'risk_score': summary.get('risk_score'),
            'prob_drought': (round(prob_pct / 100, 3) if prob_pct is not None else None),
            'action': rules.get('action'),
            'spei_3month': rules.get('spei_3month'),
            'risk_source': summary.get('risk_source'),
            'data_warnings': facts.get('data_warnings') or [],
        },
        'details': _json_safe(facts),
    }


def prewarm_answers():
    """Pre-generate the common answers (called by the monthly task)."""
    langs = ['en', 'fr', 'ar']
    questions = {
        'irrigation': 'When should I irrigate?',
        'planting': 'What should I plant this season?',
        'drought_status': 'Is drought expected next month?',
        'water_reduction': 'How can I save water?',
        'crop_care': 'How do I care for my crops?',
    }
    count = 0
    for region in Region.objects.filter(latitude__isnull=False):
        for lang in langs:
            for question in questions.values():
                try:
                    answer_question(question, region_id=region.id, lang=lang,
                                    use_llm=True)
                    count += 1
                except Exception as exc:               # noqa: BLE001
                    logger.warning('assistant: prewarm failed for %s/%s (%s)',
                                   region.name, lang, exc)
    return count


def suggestions(lang='en'):
    S = {
        'en': ['What features does this platform have?',
               'Where can I find the drought risk map?',
               'How do I upload or export data?',
               'Is drought expected next month?',
               'When should I irrigate?'],
        'fr': ['Que puis-je faire sur cette plateforme ?',
               'Où trouver la carte du risque ?',
               'Comment importer ou exporter des données ?',
               'Une sécheresse est-elle prévue le mois prochain ?',
               'Quand dois-je irriguer ?'],
        'ar': ['ما هي ميزات هذه المنصة؟',
               'أين أجد خريطة مخاطر الجفاف؟',
               'كيف أقوم برفع أو تصدير البيانات؟',
               'هل يُتوقع جفاف الشهر القادم؟',
               'متى يجب أن أسقي؟'],
    }
    return S.get(lang, S['en'])












