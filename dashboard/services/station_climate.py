"""Daily climate for the two Ichkeul stations, continued from open data.

The station dataset (1996-2025, one row per day per station in ClimateMetrics)
was built from open reanalysis data. Comparing it with the sources shows:

  rainfall        = CHIRPS daily (UCSB-CHG/CHIRPS/DAILY), identical
  solar radiation = ERA5-Land daily (ECMWF/ERA5_LAND/DAILY_AGGR), identical
  temperatures, relative humidity, wind at 2 m
                  = ERA5-Land with a steady per-station offset

so new days are built the same way: CHIRPS rain, ERA5-Land solar, and
ERA5-Land temperature / humidity / wind corrected with per-station, per-month
offsets (ratios for wind) fitted on the overlap with the dataset (see
calibrate()). ET0 is FAO-56 Penman-Monteith from those values, which
reproduces the dataset's ET0 at the 37.010 N station within 0.05 mm/day.

CHIRPS is published ~5-6 weeks late. Until it is, rain is filled from NASA
GPM IMERG (rainfall_source='IMERG') and replaced by CHIRPS on a later run.
Rows up to DATASET_END belong to the original dataset and are never changed.

Monthly SPEI-3 (DroughtIndices) is continued too, with the dataset's own
method (scripts in the APWRS repo, "indice spei"): monthly rain - ET0, summed
over 3 months, a 3-parameter log-logistic fitted per calendar month by
probability-weighted moments, then the normal quantile. The fit uses the
1996-2025 reference, so stored values are unchanged; ET0 is FAO-56 recomputed
from each day's weather over the whole series, because the stored ET0 of the
37.117 N station is about a third of FAO-56 and would make every new month
look like a drought.
"""
import datetime as dt
import json
import logging
import math
import os

import numpy as np
import pandas as pd
from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)

# The dataset's own station sheet ("coordonnées"): latitude, longitude, altitude (m).
STATIONS = [
    {'key': 'st1', 'lat': 37.010, 'lon': 9.731, 'alt': 20, 'subregion': 'v8_st_sub_humide'},
    {'key': 'st2', 'lat': 37.117, 'lon': 9.318, 'alt': 108, 'subregion': 'v8_st_humide_inf'},
]
# The basin's SPEI row is the mean of the two stations, at the basin centre.
MERGED = {'lat': 37.0635, 'lon': 9.5245, 'subregion': 'merged'}
REGION_NAME = 'Ichkeul'
DATASET_END = dt.date(2025, 12, 31)
CALIBRATION_FILE = os.path.join(settings.BASE_DIR, 'data', 'station_climate_calibration.json')

U10_TO_U2 = 4.87 / math.log(67.8 * 10 - 5.42)   # FAO-56 Eq. 47
ADDITIVE = ('tmean', 'tmin', 'tmax', 'rh')       # monthly offsets
RATIO = ('ws2',)                                 # monthly ratios
FIELD = {
    'rain': 'rainfall_mm', 'tmean': 'temperature_mean_c', 'tmin': 'temperature_min_c',
    'tmax': 'temperature_max_c', 'rh': 'relative_humidity_percent', 'ws2': 'wind_speed_ms',
    'solar': 'solar_radiation_mjm2day', 'et0': 'evapotranspiration_et0_mmday',
}


class StationClimateError(Exception):
    pass


def _ee():
    from .sentinel_tiles import SentinelUnavailable, _ee as init
    try:
        return init()
    except SentinelUnavailable as exc:
        raise StationClimateError(str(exc)) from exc


def _chunks(start, end):
    """[start, end] as calendar-year pieces (getRegion caps the values per call)."""
    while start <= end:
        stop = min(end, dt.date(start.year, 12, 31))
        yield start, stop
        start = stop + dt.timedelta(days=1)


def _region_rows(ee, collection, point, scale):
    try:
        data = collection.getRegion(point, scale).getInfo()
    except ee.EEException as exc:
        # A period the product has not reached yet is an empty collection, not a failure.
        if 'No bands in collection' in str(exc):
            return []
        raise StationClimateError(f'Earth Engine: {str(exc)[:200]}') from exc
    head = data[0]
    return [dict(zip(head, row)) for row in data[1:]]


def _day(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).date()


# ── Download ────────────────────────────────────────────────────────────

def pull_era5(ee, st, start, end):
    """Raw ERA5-Land daily values at a station, one row per available day."""
    pt = ee.Geometry.Point(st['lon'], st['lat'])
    out = []
    for a, b in _chunks(start, end):
        col = (ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR')
               .filterDate(a.isoformat(), (b + dt.timedelta(days=1)).isoformat())
               .select(['temperature_2m', 'temperature_2m_min', 'temperature_2m_max', 'dewpoint_temperature_2m',
                        'u_component_of_wind_10m', 'v_component_of_wind_10m',
                        'surface_solar_radiation_downwards_sum']))
        out += _region_rows(ee, col, pt, 11132)
    if not out:
        return pd.DataFrame(columns=['tmean', 'tmin', 'tmax', 'rh', 'ws2', 'solar'])
    df = pd.DataFrame(out)
    df = df.dropna(subset=['temperature_2m'])
    df['date'] = [_day(t) for t in df['time']]
    df = df.groupby('date').first()
    tc = df['temperature_2m'] - 273.15
    td = df['dewpoint_temperature_2m'] - 273.15
    es = 0.6108 * np.exp(17.27 * tc / (tc + 237.3))
    ea = 0.6108 * np.exp(17.27 * td / (td + 237.3))
    return pd.DataFrame({
        'tmean': tc,
        'tmin': df['temperature_2m_min'] - 273.15,
        'tmax': df['temperature_2m_max'] - 273.15,
        'rh': (100 * ea / es).clip(0, 100),
        # Daily-mean wind vector, as the dataset does, brought from 10 m to 2 m.
        'ws2': np.hypot(df['u_component_of_wind_10m'], df['v_component_of_wind_10m']) * U10_TO_U2,
        'solar': df['surface_solar_radiation_downwards_sum'] / 1e6,
    })


def pull_chirps(ee, st, start, end):
    pt = ee.Geometry.Point(st['lon'], st['lat'])
    vals = {}
    for a, b in _chunks(start, end):
        col = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate(a.isoformat(), (b + dt.timedelta(days=1)).isoformat())
        for r in _region_rows(ee, col, pt, 5566):
            if r.get('precipitation') is not None:
                vals[_day(r['time'])] = float(r['precipitation'])
    return pd.Series(vals, dtype=float)


def pull_imerg(ee, st, start, end):
    """Daily IMERG totals: the half-hourly rate (mm/h) summed over the day x 0.5 h."""
    pt = ee.Geometry.Point(st['lon'], st['lat'])
    n = (end - start).days + 1
    if n <= 0:
        return pd.Series(dtype=float)
    base = ee.Date(start.isoformat())

    def daily(i):
        d0 = base.advance(i, 'day')
        imgs = ee.ImageCollection('NASA/GPM_L3/IMERG_V07').filterDate(d0, d0.advance(1, 'day')).select('precipitation')
        return (imgs.sum().multiply(0.5).rename('p')
                .set('system:time_start', d0.millis()).set('n', imgs.size()))

    col = ee.ImageCollection(ee.List.sequence(0, n - 1).map(daily)).filter(ee.Filter.gte('n', 40))
    vals = {_day(r['time']): float(r['p']) for r in _region_rows(ee, col, pt, 10000) if r.get('p') is not None}
    return pd.Series(vals, dtype=float)


# ── Calibration ─────────────────────────────────────────────────────────

def _dataset_frame(region, st, start, end):
    from ..models import ClimateMetrics
    rows = ClimateMetrics.objects.filter(region=region, latitude=st['lat'], longitude=st['lon'],
                                         measurement_date__gte=start, measurement_date__lte=end)
    df = pd.DataFrame.from_records(rows.values('measurement_date', *FIELD.values()))
    if df.empty:
        return df
    df['date'] = [d.date() if hasattr(d, 'date') else d for d in pd.to_datetime(df['measurement_date'])]
    df = df.drop(columns='measurement_date').set_index('date').astype(float)
    return df.rename(columns={v: k for k, v in FIELD.items()})


def _fit(raw, ds):
    j = raw.join(ds, how='inner', rsuffix='_ds')
    months = pd.Series([d.month for d in j.index], index=j.index)
    cal = {'add': {}, 'ratio': {}}
    for k in ADDITIVE:
        diff = (j[f'{k}_ds'] - j[k]).groupby(months).mean()
        cal['add'][k] = {str(m): round(float(v), 4) for m, v in diff.items()}
    for k in RATIO:
        g = j[[k, f'{k}_ds']].groupby(months).sum()
        cal['ratio'][k] = {str(m): round(float(r[f'{k}_ds'] / r[k]), 4) for m, r in g.iterrows() if r[k] > 0}
    return cal


def apply_calibration(raw, cal):
    """Corrected daily values; tmin <= tmean <= tmax and RH within 0-100 are kept."""
    out = raw.copy()
    months = [str(d.month) for d in out.index]
    for k in ADDITIVE:
        out[k] = out[k] + [cal['add'][k].get(m, 0.0) for m in months]
    for k in RATIO:
        out[k] = out[k] * [cal['ratio'][k].get(m, 1.0) for m in months]
    out['rh'] = out['rh'].clip(0, 100)
    out['tmin'] = out[['tmin', 'tmean']].min(axis=1)
    out['tmax'] = out[['tmax', 'tmean']].max(axis=1)
    return out


def calibrate(first_year=2016, test_from=2024):
    """Fit the per-station corrections on the dataset overlap and save them.

    The reported test errors come from a fit on first_year..test_from-1,
    scored on test_from..DATASET_END; the saved corrections use all years.
    """
    from ..models import Region
    ee = _ee()
    region = Region.objects.get(name=REGION_NAME)
    start = dt.date(first_year, 1, 1)
    result = {'fitted_on': [start.isoformat(), DATASET_END.isoformat()],
              'created': dt.date.today().isoformat(), 'stations': {}}
    for st in STATIONS:
        raw = pull_era5(ee, st, start, DATASET_END)
        ds = _dataset_frame(region, st, start, DATASET_END)
        if raw.empty or ds.empty:
            raise StationClimateError(f"no overlap for station {st['key']}")
        split = dt.date(test_from, 1, 1)
        train_cal = _fit(raw[raw.index < split], ds[ds.index < split])
        test = apply_calibration(raw[raw.index >= split], train_cal).join(ds, how='inner', rsuffix='_ds')
        errors = {k: {'raw': round(float((raw.loc[test.index, k] - test[f'{k}_ds']).abs().mean()), 3),
                      'corrected': round(float((test[k] - test[f'{k}_ds']).abs().mean()), 3)}
                  for k in ADDITIVE + RATIO + ('solar',)}
        result['stations'][st['key']] = {**st, **_fit(raw, ds), 'test_mae': errors,
                                         'test_period': [split.isoformat(), DATASET_END.isoformat()]}
    os.makedirs(os.path.dirname(CALIBRATION_FILE), exist_ok=True)
    with open(CALIBRATION_FILE, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=1)
    return result


def load_calibration():
    if not os.path.exists(CALIBRATION_FILE):
        raise StationClimateError('No calibration yet: run "python manage.py update_station_climate --calibrate" first')
    with open(CALIBRATION_FILE, encoding='utf-8') as f:
        return json.load(f)


# ── Build and store ─────────────────────────────────────────────────────

def build_days(raw, rain_chirps, rain_imerg, cal, st):
    from ..prediction_engine.physical_helpers import fao56_et0
    days = apply_calibration(raw, cal)
    rows = []
    for d, r in days.iterrows():
        if d in rain_chirps.index:
            rain, src = rain_chirps[d], 'CHIRPS'
        elif d in rain_imerg.index:
            rain, src = rain_imerg[d], 'IMERG'
        else:
            rain, src = None, None
        et0 = fao56_et0(r['tmax'], r['tmin'], r['solar'], r['rh'], r['ws2'], st['lat'],
                        d.timetuple().tm_yday, elevation_m=st['alt'], wind_height_m=2)
        rows.append({
            'date': d, 'rain': None if rain is None else round(max(0.0, float(rain)), 1), 'rain_source': src,
            'tmean': round(float(r['tmean']), 1), 'tmin': round(float(r['tmin']), 1), 'tmax': round(float(r['tmax']), 1),
            'rh': int(round(float(r['rh']))), 'ws2': round(float(r['ws2']), 2), 'solar': round(float(r['solar']), 2),
            'et0': round(max(0.0, float(et0)), 2),
        })
    return rows


def _pending_start(region, st):
    """First day after the dataset that is missing or still holds provisional rain."""
    from ..models import ClimateMetrics
    qs = ClimateMetrics.objects.filter(region=region, latitude=st['lat'], longitude=st['lon'],
                                       measurement_date__gt=DATASET_END)
    have = {d.date() if hasattr(d, 'date') else d
            for d in qs.exclude(rainfall_source='IMERG').exclude(rainfall_mm=None).values_list('measurement_date', flat=True)}
    day = DATASET_END + dt.timedelta(days=1)
    while day in have:
        day += dt.timedelta(days=1)
    return day


def update(start=None, end=None, dry_run=False, log=None):
    """Download, correct and store new days for both stations. Returns a summary per station."""
    from ..models import ClimateMetrics, ObservationYear, Region
    log = log or (lambda *_: None)
    cal = load_calibration()
    region = Region.objects.get(name=REGION_NAME)
    ee = _ee()
    end = end or dt.date.today()
    summary = {}
    for st in STATIONS:
        s = max(start or _pending_start(region, st), DATASET_END + dt.timedelta(days=1))
        if s > end:
            summary[st['key']] = {'from': None, 'created': 0, 'updated': 0, 'note': 'up to date'}
            continue
        log(f"Station {st['lat']}, {st['lon']}: {s} to {end}")
        raw = pull_era5(ee, st, s, end)
        if raw.empty:
            summary[st['key']] = {'from': s.isoformat(), 'created': 0, 'updated': 0,
                                  'note': 'ERA5-Land has no newer days yet'}
            continue
        last = max(raw.index)
        chirps = pull_chirps(ee, st, s, last)
        missing = [d for d in raw.index if d not in chirps.index]
        imerg = pull_imerg(ee, st, min(missing), max(missing)) if missing else pd.Series(dtype=float)
        rows = build_days(raw, chirps, imerg, cal['stations'][st['key']], st)
        created = updated = 0
        if not dry_run:
            years = {}
            with transaction.atomic():
                for r in rows:
                    y = r['date'].year
                    if y not in years:
                        years[y], _ = ObservationYear.objects.get_or_create(label=str(y))
                    _, was_created = ClimateMetrics.objects.update_or_create(
                        region=region, year=years[y], measurement_date=r['date'],
                        latitude=st['lat'], longitude=st['lon'],
                        defaults={FIELD[k]: r[k] for k in FIELD} | {'rainfall_source': r['rain_source']})
                    created += was_created
                    updated += not was_created
        src = pd.Series([r['rain_source'] for r in rows]).value_counts().to_dict()
        summary[st['key']] = {'from': s.isoformat(), 'to': last.isoformat(), 'days': len(rows),
                              'created': created, 'updated': updated, 'rain_sources': src}
    if not dry_run:
        summary['spei'] = update_spei(log)
    return summary


# ── Monthly SPEI-3 ──────────────────────────────────────────────────────

SEVERITY = ((-2.0, 'Extreme Drought'), (-1.5, 'Severe Drought'), (-1.0, 'Moderate Drought'),
            (-0.5, 'Abnormally Dry'))


def severity_class(spei):
    for limit, name in SEVERITY:
        if spei <= limit:
            return name
    return 'None'


def _loglogistic(x):
    """3-parameter log-logistic fitted by probability-weighted moments (alpha, beta, gamma)."""
    from scipy.special import gamma as G
    x = np.sort(np.asarray(x, dtype=float))
    n = len(x)
    F = (np.arange(1, n + 1) - 0.35) / n
    w0, w1, w2 = x.mean(), np.mean((1 - F) * x), np.mean((1 - F) ** 2 * x)
    beta = (2 * w1 - w0) / (6 * w1 - w0 - 6 * w2)
    g = G(1 + 1 / beta) * G(1 - 1 / beta)
    alpha = (w0 - 2 * w1) * beta / g
    return alpha, beta, w0 - alpha * g


def spei_from_balance(balance, reference):
    """SPEI of a monthly (accumulated) water balance, fitted per calendar month on `reference`."""
    from scipy.stats import norm
    out = pd.Series(index=balance.index, dtype=float)
    for m in range(1, 13):
        alpha, beta, gamma = _loglogistic(reference[reference.index.month == m].dropna())
        x = balance[balance.index.month == m]
        d = (x - gamma).where(x > gamma)
        F = 1 / (1 + (alpha / d) ** beta)
        out[x.index] = norm.ppf(np.clip(F.astype(float), 1e-6, 1 - 1e-6))
    return out


def _monthly_balance(region, st):
    """Monthly rain - FAO-56 ET0 (mm) and the last day with data, from the stored daily series."""
    from ..models import ClimateMetrics
    from ..prediction_engine.physical_helpers import fao56_et0
    rows = ClimateMetrics.objects.filter(region=region, latitude=st['lat'], longitude=st['lon']).values(
        'measurement_date', *[FIELD[k] for k in ('rain', 'tmax', 'tmin', 'solar', 'rh', 'ws2')])
    df = pd.DataFrame.from_records(rows)
    df['d'] = pd.to_datetime(df.pop('measurement_date'), utc=True).dt.tz_localize(None).dt.normalize()
    df = df.set_index('d').sort_index().astype(float)
    et0 = [fao56_et0(r.temperature_max_c, r.temperature_min_c, r.solar_radiation_mjm2day,
                     r.relative_humidity_percent, r.wind_speed_ms, st['lat'], d.dayofyear,
                     elevation_m=st['alt'], wind_height_m=2) for d, r in df.iterrows()]
    daily = df['rainfall_mm'] - pd.Series(et0, index=df.index)
    complete = daily.dropna()
    return daily.resample('ME').sum(min_count=1), complete.index.max().date() if len(complete) else None


def update_spei(log=None):
    """Monthly SPEI-3 for the complete months after the dataset, per station and for the basin."""
    from ..models import DroughtIndices, ObservationYear, Region
    log = log or (lambda *_: None)
    region = Region.objects.get(name=REGION_NAME)
    per_station = {}
    for st in STATIONS:
        monthly, last_day = _monthly_balance(region, st)
        acc = monthly.rolling(3, min_periods=3).sum()
        reference = acc[acc.index <= pd.Timestamp(DATASET_END)]
        spei = spei_from_balance(acc, reference)
        # Only months after the dataset, and only complete ones.
        keep = [m for m in spei.index if m.date() > DATASET_END and last_day and m.date() <= last_day]
        per_station[st['key']] = spei[keep].dropna()
    written = 0
    with transaction.atomic():
        for point, series in [(st, per_station[st['key']]) for st in STATIONS] + [
                (MERGED, pd.concat(per_station.values(), axis=1).dropna().mean(axis=1))]:
            for month_end, value in series.items():
                year, _ = ObservationYear.objects.get_or_create(label=str(month_end.year))
                value = round(float(value), 2)
                DroughtIndices.objects.update_or_create(
                    region=region, year=year, measurement_date=month_end.date(),
                    latitude=point['lat'], longitude=point['lon'],
                    defaults={'subregion': point['subregion'], 'spei_3month': value,
                              'drought_severity_class': severity_class(value)})
                written += 1
    months = sorted({m.strftime('%Y-%m') for s in per_station.values() for m in s.index})
    log(f"SPEI-3: {written} monthly values ({months[0]} to {months[-1]})" if months else 'SPEI-3: no complete new month')
    return {'months': months, 'written': written}
