"""What is driving today's drought risk (analysis page, "What's driving risk?").

The risk score shown on the page is computed from rain only:
    SPI-3 = 90-day rain total vs the same window in up to 30 earlier years
            (gamma fit, physical_helpers.spi_at)
    risk  = assistant_brain._score_from_spei(SPI-3)  (10 when SPI-3 >= 0,
            40 at -1, 60 at -1.5, 80 at -2, 100 at -3)
so rainfall is the one input of the score, and the breakdown says so.

The other signals are NOT in the score; they are shown as early warnings,
each as a standard anomaly against the same calendar window in earlier years:
    rain_30      SPI of the last 30 days of rain (stations, spi_at)
    temperature  30-day mean temperature, z and degrees above / below normal
    et0          30-day FAO-56 ET0 total (recomputed for every year), z and % of normal
    soil         ERA5-Land root-zone (0-28 cm) soil water, z vs 30 earlier years
    vegetation   MODIS NDVI of the two newest 16-day composites, z vs 2001 on
Soil and vegetation come from the same Earth Engine computation as the map's
drought layer and are left out when Earth Engine cannot be reached.

`stress` is the anomaly turned so that positive always means "pushes toward
drought" (less rain / soil water / greenness, more heat / evaporative demand).
"""
import logging

import numpy as np
import pandas as pd
from django.db.models import Avg

logger = logging.getLogger(__name__)

MAX_YEARS, MIN_YEARS = 30, 10


def _daily(region, field):
    from ..models import ClimateMetrics
    rows = (ClimateMetrics.objects.filter(region=region, **{f'{field}__isnull': False})
            .values('measurement_date').annotate(v=Avg(field)).order_by('measurement_date'))
    if not rows:
        return pd.Series(dtype='float64')
    idx = pd.DatetimeIndex(pd.to_datetime([r['measurement_date'] for r in rows], utc=True)
                           .tz_localize(None).normalize())
    # several measuring points per day -> one value per day
    return pd.Series([float(r['v']) for r in rows], index=idx, dtype='float64').groupby(level=0).mean()


def _daily_fao56_et0(region):
    """FAO-56 ET0 recomputed from each day's weather, per station, then averaged.

    The stored ET0 is not one series: the original dataset's 37.117 N station
    holds about a third of FAO-56 (see services/station_climate), while rows
    after 2025 are FAO-56. Comparing new days with that history would show a
    false +50 % "evaporation surge", so ET0 is rebuilt the same way for all
    years, as the SPEI update does."""
    from ..models import ClimateMetrics
    from ..prediction_engine.physical_helpers import fao56_et0
    from .station_climate import FIELD, STATIONS
    cols = [FIELD[k] for k in ('tmax', 'tmin', 'solar', 'rh', 'ws2')]
    per_station = []
    for st in STATIONS:
        df = pd.DataFrame.from_records(ClimateMetrics.objects.filter(
            region=region, latitude=st['lat'], longitude=st['lon']).values('measurement_date', *cols))
        if df.empty:
            continue
        df['d'] = pd.to_datetime(df.pop('measurement_date'), utc=True).dt.tz_localize(None).dt.normalize()
        df = df.set_index('d').astype(float).dropna()
        et0 = [fao56_et0(tx, tn, sol, rh, ws, st['lat'], d.dayofyear, elevation_m=st['alt'], wind_height_m=2)
               for d, tx, tn, sol, rh, ws in zip(df.index, *(df[c].values for c in cols))]
        per_station.append(pd.Series(np.maximum(0.0, np.asarray(et0, dtype=float)), index=df.index))
    if not per_station:
        return pd.Series(dtype='float64')
    return pd.concat(per_station, axis=1).mean(axis=1).sort_index()


def _window(s, end, days, how):
    w = s[(s.index > end - pd.Timedelta(days=days)) & (s.index <= end)]
    if len(w) < days * 0.9:              # tolerate a few missing days
        return None
    return float(w.sum() if how == 'sum' else w.mean())


def window_anomaly(series, end, days, how):
    """Current window value, the mean / sd of the same window in earlier years, and z."""
    if series is None or series.empty:
        return None
    end = pd.Timestamp(end).normalize()
    current = _window(series, end, days, how)
    past = [_window(series, end - pd.DateOffset(years=k), days, how) for k in range(1, MAX_YEARS + 1)]
    past = np.array([v for v in past if v is not None])
    if current is None or len(past) < MIN_YEARS:
        return None
    mean, sd = float(past.mean()), float(past.std(ddof=1))
    return {'value': current, 'normal': mean, 'z': (current - mean) / sd if sd > 0 else 0.0,
            'years': int(len(past))}


def _rain(series, end, days):
    from ..prediction_engine.physical_helpers import spi_at
    a = window_anomaly(series, end, days, 'sum')
    if a is None:
        return None
    spi = spi_at(series, end, days=days)
    if spi is None:
        return None
    a['z'] = float(spi)              # SPI (gamma) instead of a normal z: rain is skewed
    a['pct_of_normal'] = 100 * a['value'] / a['normal'] if a['normal'] > 0 else None
    return a


def _signal(key, a, stress_sign, unit, in_score=False, source='', window_days=None):
    z = float(a['z'])
    out = {
        'key': key, 'in_score': in_score, 'unit': unit, 'source': source,
        'value': round(a['value'], 1) if a.get('value') is not None else None,
        'normal': round(a['normal'], 1) if a.get('normal') is not None else None,
        'z': round(z, 2),
        'stress': round(stress_sign * z, 2),
        'window_days': window_days,
    }
    if a.get('pct_of_normal') is not None:
        out['pct_of_normal'] = round(a['pct_of_normal'])
    if a.get('value') is not None and a.get('normal') is not None:
        out['diff'] = round(a['value'] - a['normal'], 1)
        if a['normal']:
            out['diff_pct'] = round(100 * (a['value'] - a['normal']) / a['normal'])
    return out


def _satellite():
    """Basin-mean soil / vegetation anomalies from the map's Earth Engine layer."""
    try:
        from . import sentinel_tiles
        return sentinel_tiles.basin_anomalies()
    except Exception as exc:          # Earth Engine unreachable: leave them out
        logger.info('Satellite anomalies unavailable: %s', exc)
        return None


def build(region, end_date, risk_today=None, spi3=None, satellite=True):
    """Breakdown of today's risk for `region`, measured up to `end_date`."""
    from .assistant_brain import _score_from_spei
    end = pd.Timestamp(end_date).normalize()
    rain = _daily(region, 'rainfall_mm')
    signals = []

    r90 = _rain(rain, end, 90)
    if r90 is not None:
        if spi3 is not None:
            r90['z'] = float(spi3)    # exactly the SPI-3 the score was made from
        signals.append(_signal('rain_90', r90, -1, 'mm', in_score=True, source='stations', window_days=90))
    r30 = _rain(rain, end, 30)
    if r30 is not None:
        signals.append(_signal('rain_30', r30, -1, 'mm', source='stations', window_days=30))
    t = window_anomaly(_daily(region, 'temperature_mean_c'), end, 30, 'mean')
    if t is not None:
        signals.append(_signal('temperature', t, +1, '°C', source='stations', window_days=30))
    e = window_anomaly(_daily_fao56_et0(region), end, 30, 'sum')
    if e is not None:
        signals.append(_signal('et0', e, +1, 'mm', source='stations', window_days=30))

    sat = _satellite() if satellite else None
    if sat:
        if sat.get('soil_z') is not None:
            signals.append(_signal('soil', {'value': None, 'normal': None, 'z': sat['soil_z']}, -1, '',
                                   source='ERA5-Land', window_days=30))
        if sat.get('veg_z') is not None:
            signals.append(_signal('vegetation', {'value': None, 'normal': None, 'z': sat['veg_z']}, -1, '',
                                   source='MODIS NDVI', window_days=32))

    score_spi = spi3 if spi3 is not None else (r90['z'] if r90 else None)
    return {
        'version': 2,
        'measured_to': end.date().isoformat(),
        'risk': risk_today if risk_today is not None else _score_from_spei(score_spi),
        'spi3': round(float(score_spi), 2) if score_spi is not None else None,
        'signals': signals,
    }


def legacy_drivers(breakdown):
    """The old `drivers` keys still read by the LLM explainer and the PDF: the
    rainfall deficit is the real 90-day shortfall in % of normal (0 if wetter)."""
    rain = next((s for s in breakdown['signals'] if s['key'] == 'rain_90'), None)
    deficit = max(0, 100 - rain['pct_of_normal']) if rain and rain.get('pct_of_normal') is not None else 0
    temp = next((s for s in breakdown['signals'] if s['key'] == 'temperature'), None)
    return {'rainfall_deficit': deficit,
            'high_temperature': temp['diff'] if temp and temp.get('diff') is not None else 0,
            'breakdown': breakdown}


LABELS = {
    'rain_90': 'Rainfall, last 90 days', 'rain_30': 'Rainfall, last 30 days',
    'temperature': 'Temperature, last 30 days', 'et0': 'Evaporative demand (ET0), 30 days',
    'soil': 'Soil moisture 0-28 cm', 'vegetation': 'Vegetation (NDVI)',
}


def strength(stress):
    """Words for a standard anomaly that points toward (+) or away from (-) drought."""
    a = abs(stress)
    if a < 0.5:
        return 'near normal'
    side = 'drier' if stress > 0 else 'wetter'
    return ('slightly ' if a < 1 else 'clearly ' if a < 2 else 'strongly ') + side


def signal_rows(breakdown):
    """(label, now vs normal, effect) rows for reports."""
    rows = []
    for s in breakdown.get('signals', []):
        if s['key'] in ('rain_90', 'rain_30'):
            now = f"{s['value']:.0f} mm vs {s['normal']:.0f} mm ({s.get('pct_of_normal', 0)}%)"
        elif s['key'] == 'temperature':
            now = f"{s['value']:.1f} vs {s['normal']:.1f} C ({s['diff']:+.1f} C)"
        elif s['key'] == 'et0':
            now = f"{s['value']:.0f} vs {s['normal']:.0f} mm ({s.get('diff_pct', 0):+d}%)"
        else:
            now = f"anomaly {s['z']:+.2f} sd"
        effect = ('sets the score: ' if s['in_score'] else '') + strength(s['stress'])
        rows.append((LABELS[s['key']], now, effect))
    return rows
