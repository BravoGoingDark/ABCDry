"""GFS rainfall forecasts (via the free Open-Meteo API) blended with local
climatology. Used to make the +7 / +30 day SPI-3 drought-risk forecasts
responsive to the actual weather that is coming, instead of assuming the
future will look like the recent past.

Open-Meteo's /v1/forecast endpoint serves GFS-based daily precipitation
(optionally ECMWF/IFS via /v1/ecmwf) for up to 16 days. Beyond that we fall
back to the region's own climatology, so a 30-day rainfall scenario is a
transparent blend of "forecast where available, normal thereafter".
"""
import logging

import pandas as pd
import requests

logger = logging.getLogger(__name__)

OPEN_METEO_URL = 'https://api.open-meteo.com/v1/forecast'
ECMWF_URL = 'https://api.open-meteo.com/v1/ecmwf'
MAX_FORECAST_DAYS = 16
REQUEST_TIMEOUT = 20


def fetch_daily_rain_forecast(lat, lon, forecast_days=MAX_FORECAST_DAYS, model='gfs'):
    """Return {date_iso: rainfall_mm} from Open-Meteo for the next forecast_days.

    model: 'gfs' (default /v1/forecast) or 'ecmwf' (/v1/ecmwf, ~10 days).
    Returns None if the request fails or returns no data.
    """
    url = ECMWF_URL if model == 'ecmwf' else OPEN_METEO_URL
    params = {
        'latitude': lat,
        'longitude': lon,
        'daily': 'precipitation_sum',
        'timezone': 'UTC',
        'forecast_days': min(int(forecast_days), MAX_FORECAST_DAYS),
    }
    try:
        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        daily = resp.json().get('daily') or {}
        times = daily.get('time') or []
        rain = daily.get('precipitation_sum') or []
        if not times:
            return None
        return {date_str: float(mm or 0.0) for date_str, mm in zip(times, rain)}
    except Exception as exc:
        logger.warning('Open-Meteo %s forecast failed for (%s, %s): %s', model, lat, lon, exc)
        return None


def climatological_daily_rain(region, start_date, days):
    """Expected daily rainfall (mm) for each of the next `days` dates, based on
    the region's own history (mean rainfall for that calendar day-of-year).

    Returns pd.Series indexed by the target dates.
    """
    from dashboard.models import ClimateMetrics

    import numpy as np

    dates = pd.date_range(start=start_date, periods=days, freq='D')
    stats = {}
    for obj in ClimateMetrics.objects.filter(
        region=region, rainfall_mm__isnull=False
    ).values('measurement_date', 'rainfall_mm'):
        stats.setdefault(obj['measurement_date'].timetuple().tm_yday, []).append(float(obj['rainfall_mm']))
    if not stats:
        return pd.Series(0.0, index=dates)

    values = []
    for d in dates:
        pool = stats.get(d.timetuple().tm_yday, [])
        values.append(float(np.mean(pool)) if pool else 0.0)
    return pd.Series(values, index=dates, dtype='float64')


def build_next_days_rain(region, start_date, days, lat=None, lon=None, model='gfs'):
    """Rainfall scenario (mm/day) for the next `days` dates.

    Uses the GFS/ECMWF forecast where available, then fills the remainder with
    the region's climatology. Returns (pd.Series indexed by date, meta dict).
    """
    scenario = climatological_daily_rain(region, start_date, days)
    meta = {
        'source': 'climatology',
        'n_forecast_days': 0,
        'model': None,
        'rain_7d_mm': round(float(scenario.iloc[:7].sum()), 1),
        'rain_30d_mm': round(float(scenario.sum()), 1),
    }

    if lat is None or lon is None:
        return scenario, meta

    forecast = fetch_daily_rain_forecast(lat, lon, forecast_days=days, model=model)
    if forecast:
        for date_str, mm in forecast.items():
            date = pd.Timestamp(date_str)
            if date in scenario.index:
                scenario.loc[date] = mm
        meta.update({
            'source': f'{model}_forecast_and_climatology',
            'n_forecast_days': len([d for d in forecast if d in scenario.index.strftime('%Y-%m-%d')]),
            'model': model,
        })

    meta['rain_7d_mm'] = round(float(scenario.iloc[:7].sum()), 1)
    meta['rain_30d_mm'] = round(float(scenario.sum()), 1)
    return scenario, meta
