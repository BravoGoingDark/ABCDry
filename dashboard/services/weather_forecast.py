"""Live weather forecasts for the forecast page.

Fetches daily temperature + rainfall from Open-Meteo (GFS / ECMWF IFS /
ICON via ``best_match``), normalises the response, and caches it for
30 minutes so page loads and API calls never hammer the upstream service.

The request is made server-side on purpose: the browser never talks to a
third-party weather API directly, so we keep one code path, one cache, and
a single place to add an API key if the deployment ever needs a commercial
Open-Meteo plan.

Docs:     https://open-meteo.com/en/docs
Licence:  CC BY 4.0 — the UI must credit "Weather data by Open-Meteo.com".
"""
from __future__ import annotations

import calendar
import logging
from datetime import date, datetime, timezone as dt_timezone
from statistics import mean

import requests
from django.core.cache import cache

from dashboard.models import ClimateMetrics, Region

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
DEFAULT_FORECAST_DAYS = 16
MAX_FORECAST_DAYS = 16
REQUEST_TIMEOUT = 8
CACHE_TTL = 60 * 30          # 30 min: models refresh hourly at best
ERROR_CACHE_TTL = 60 * 2     # avoid hammering upstream during an outage
NORMALS_CACHE_TTL = 60 * 60 * 12

DAILY_VARIABLES = (
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "temperature_2m_mean",
    "precipitation_sum",
    "precipitation_probability_max",
    "et0_fao_evapotranspiration",
    "wind_speed_10m_max",
)

# Approximate regional centroids, used only when a Region row has no
# latitude/longitude. Replace with surveyed coordinates when available.
FALLBACK_COORDS = {
    "ichkeul": (37.0635, 9.5245),
    "tunisia": (36.8065, 10.1815),
    "bizerte": (37.2744, 9.8739),
    "kairouan": (35.6781, 10.0963),
    "skhira": (34.2833, 9.7500),
    "meknes": (33.8935, -5.5473),
    "morocco": (31.7917, -7.0926),
    "algeria": (36.7538, 3.0588),
}

# WMO weather interpretation codes -> (label, Material Symbols icon, colour, bg)
_WMO_CONDITIONS = {
    0: ("Clear sky", "wb_sunny", "#f59e0b", "#fef3c7"),
    1: ("Mainly clear", "partly_cloudy_day", "#0ea5e9", "#e0f2fe"),
    2: ("Partly cloudy", "partly_cloudy_day", "#0ea5e9", "#e0f2fe"),
    3: ("Overcast", "cloud", "#6b7280", "#f3f4f6"),
    45: ("Fog", "foggy", "#6b7280", "#f3f4f6"),
    48: ("Rime fog", "foggy", "#6b7280", "#f3f4f6"),
    51: ("Light drizzle", "rainy", "#3b82f6", "#dbeafe"),
    53: ("Drizzle", "rainy", "#3b82f6", "#dbeafe"),
    55: ("Dense drizzle", "rainy", "#2563eb", "#dbeafe"),
    56: ("Freezing drizzle", "rainy", "#3b82f6", "#dbeafe"),
    57: ("Freezing drizzle", "rainy", "#3b82f6", "#dbeafe"),
    61: ("Light rain", "rainy", "#3b82f6", "#dbeafe"),
    63: ("Rain", "rainy", "#3b82f6", "#dbeafe"),
    65: ("Heavy rain", "rainy", "#2563eb", "#dbeafe"),
    66: ("Freezing rain", "rainy", "#3b82f6", "#dbeafe"),
    67: ("Freezing rain", "rainy", "#3b82f6", "#dbeafe"),
    71: ("Light snow", "weather_snowy", "#0ea5e9", "#e0f2fe"),
    73: ("Snow", "weather_snowy", "#0ea5e9", "#e0f2fe"),
    75: ("Heavy snow", "weather_snowy", "#0284c7", "#e0f2fe"),
    77: ("Snow grains", "weather_snowy", "#0ea5e9", "#e0f2fe"),
    80: ("Rain showers", "rainy", "#3b82f6", "#dbeafe"),
    81: ("Rain showers", "rainy", "#3b82f6", "#dbeafe"),
    82: ("Violent showers", "rainy", "#2563eb", "#dbeafe"),
    85: ("Snow showers", "weather_snowy", "#0ea5e9", "#e0f2fe"),
    86: ("Snow showers", "weather_snowy", "#0284c7", "#e0f2fe"),
    95: ("Thunderstorm", "thunderstorm", "#7c3aed", "#ede9fe"),
    96: ("Thunderstorm", "thunderstorm", "#7c3aed", "#ede9fe"),
    99: ("Thunderstorm", "thunderstorm", "#7c3aed", "#ede9fe"),
}


def _condition(code):
    label, icon, color, bg = _WMO_CONDITIONS.get(
        int(code or 0), ("Unknown", "cloud", "#6b7280", "#f3f4f6")
    )
    return {"label": label, "icon": icon, "color": color, "bg": bg}


def region_point(region):
    """Return (lat, lon) for a region, falling back to a known centroid."""
    if region is None:
        return None
    if region.latitude is not None and region.longitude is not None:
        return float(region.latitude), float(region.longitude)
    key = (region.name or "").strip().lower()
    return FALLBACK_COORDS.get(key)


def regions_with_coordinates():
    """Regions the weather panel can forecast for.

    Regions with real latitude/longitude come first (they also have observed
    climatology for the reference line); known fallback centroids follow.
    """
    regions = list(Region.objects.order_by("name"))
    exact = [r for r in regions if region_point(r) and r.latitude is not None]
    fallback = [r for r in regions if r.latitude is None and region_point(r)]
    return exact + fallback


def _num(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _daily_humidity(hourly):
    """Average hourly relative humidity into {date_iso: percent}."""
    times = hourly.get("time") or []
    values = hourly.get("relative_humidity_2m") or []
    buckets = {}
    for ts, value in zip(times, values):
        if value is None:
            continue
        day = str(ts)[:10]
        buckets.setdefault(day, []).append(float(value))
    return {day: round(mean(vals), 1) for day, vals in buckets.items() if vals}


def _monthly_normals(region_id):
    """10-year-ish monthly normals from our own observations, cached."""
    key = f"weather:normals:{region_id}"
    hit = cache.get(key)
    if hit is not None:
        return hit

    from django.db.models import Avg
    from django.db.models.functions import TruncMonth

    rows = (
        ClimateMetrics.objects.filter(region_id=region_id)
        .annotate(month=TruncMonth("measurement_date"))
        .values("month")
        .annotate(
            rain=Avg("rainfall_mm"),
            tmax=Avg("temperature_max_c"),
            tmin=Avg("temperature_min_c"),
        )
        .order_by("month")
    )

    buckets = {}
    for row in rows:
        month = row.get("month")
        if month is None:
            continue
        bucket = buckets.setdefault(month.month, {"rain": [], "tmax": [], "tmin": []})
        for field, target in (("rain", "rain"), ("tmax", "tmax"), ("tmin", "tmin")):
            value = _num(row.get(field))
            if value is not None:
                bucket[target].append(value)

    normals = {}
    for month, bucket in buckets.items():
        normals[month] = {
            "rain_mm_month": round(mean(bucket["rain"]), 2) if bucket["rain"] else None,
            "tmax_c": round(mean(bucket["tmax"]), 1) if bucket["tmax"] else None,
            "tmin_c": round(mean(bucket["tmin"]), 1) if bucket["tmin"] else None,
        }

    cache.set(key, normals, NORMALS_CACHE_TTL)
    return normals


def _climatology(region_id, dates):
    """Daily normal rain / tmax / tmin for each forecast date."""
    normals = _monthly_normals(region_id)
    rain, tmax, tmin = [], [], []
    for day in dates:
        normal = normals.get(day.month)
        if not normal:
            rain.append(None)
            tmax.append(None)
            tmin.append(None)
            continue
        days_in_month = calendar.monthrange(day.year, day.month)[1]
        monthly_rain = normal.get("rain_mm_month")
        rain.append(
            round(monthly_rain / days_in_month, 2)
            if monthly_rain is not None else None
        )
        tmax.append(normal.get("tmax_c"))
        tmin.append(normal.get("tmin_c"))

    if all(value is None for value in rain + tmax + tmin):
        return None
    return {"rain_mm": rain, "tmax_c": tmax, "tmin_c": tmin}


def _error_payload(region, point, message):
    return {
        "region": {
            "id": region.id,
            "name": region.name,
            "latitude": round(point[0], 4) if point else None,
            "longitude": round(point[1], 4) if point else None,
        },
        "source": "open-meteo",
        "model": "best_match",
        "attribution": "Weather data by Open-Meteo.com",
        "attribution_url": "https://open-meteo.com/",
        "issued_at": datetime.now(dt_timezone.utc).isoformat(),
        "timezone": None,
        "days": [],
        "climatology": None,
        "summary": None,
        "error": message,
    }


def fetch_region_forecast(region, days=DEFAULT_FORECAST_DAYS):
    """Call Open-Meteo and return the normalised payload, or None on failure."""
    point = region_point(region)
    if point is None:
        return None

    lat, lon = point
    days = max(1, min(int(days or DEFAULT_FORECAST_DAYS), MAX_FORECAST_DAYS))
    params = {
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "daily": ",".join(DAILY_VARIABLES),
        "hourly": "relative_humidity_2m",
        "timezone": "auto",
        "forecast_days": days,
    }

    try:
        response = requests.get(OPEN_METEO_URL, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:  # network, HTTP, JSON — all fall back to the UI message
        logger.warning(
            "Open-Meteo forecast failed for %s (%s, %s): %s",
            region.name, lat, lon, exc,
        )
        return None

    daily = payload.get("daily") or {}
    times = daily.get("time") or []
    if not times:
        logger.warning("Open-Meteo returned no daily data for %s", region.name)
        return None

    humidity = _daily_humidity(payload.get("hourly") or {})

    def series(name):
        return daily.get(name) or []

    weather_codes = series("weather_code")
    tmax_values = series("temperature_2m_max")
    tmin_values = series("temperature_2m_min")
    tmean_values = series("temperature_2m_mean")
    rain_values = series("precipitation_sum")
    prob_values = series("precipitation_probability_max")
    et0_values = series("et0_fao_evapotranspiration")
    wind_values = series("wind_speed_10m_max")

    rows = []
    for index, iso_date in enumerate(times[:days]):
        try:
            day = date.fromisoformat(iso_date)
        except ValueError:
            continue
        tmax = _num(tmax_values[index]) if index < len(tmax_values) else None
        tmin = _num(tmin_values[index]) if index < len(tmin_values) else None
        tmean = _num(tmean_values[index]) if index < len(tmean_values) else None
        precip = _num(rain_values[index]) if index < len(rain_values) else None
        probability = _num(prob_values[index]) if index < len(prob_values) else None
        et0 = _num(et0_values[index]) if index < len(et0_values) else None
        wind = _num(wind_values[index]) if index < len(wind_values) else None

        rows.append({
            "date": iso_date,
            "weekday": day.strftime("%a"),
            "label": day.strftime("%a %d"),
            "weather_code": (
                int(weather_codes[index])
                if index < len(weather_codes) and weather_codes[index] is not None
                else None
            ),
            "condition": _condition(
                weather_codes[index] if index < len(weather_codes) else None
            ),
            "tmax": round(tmax, 1) if tmax is not None else None,
            "tmin": round(tmin, 1) if tmin is not None else None,
            "tmean": (
                round(tmean, 1) if tmean is not None
                else round((tmax + tmin) / 2, 1) if tmax is not None and tmin is not None
                else None
            ),
            "precip": round(precip, 1) if precip is not None else None,
            "precip_prob": round(probability) if probability is not None else None,
            "et0": round(et0, 2) if et0 is not None else None,
            "wind": round(wind, 1) if wind is not None else None,
            "humidity": humidity.get(iso_date),
        })

    if not rows:
        return None

    week = rows[:7]
    week_rain = [d["precip"] for d in week if d["precip"] is not None]
    week_tmax = [d["tmax"] for d in week if d["tmax"] is not None]
    week_tmin = [d["tmin"] for d in week if d["tmin"] is not None]
    week_tmean = [d["tmean"] for d in week if d["tmean"] is not None]
    week_humidity = [d["humidity"] for d in week if d["humidity"] is not None]

    summary = {
        "total_rain_mm": round(sum(week_rain), 1),
        "total_rain_16d_mm": round(sum(
            d["precip"] for d in rows if d["precip"] is not None
        ), 1),
        "max_temp_c": round(max(week_tmax), 1) if week_tmax else None,
        "min_temp_c": round(min(week_tmin), 1) if week_tmin else None,
        "avg_temp_c": round(mean(week_tmean), 1) if week_tmean else None,
        "avg_humidity": round(mean(week_humidity)) if week_humidity else None,
        "rain_days": sum(1 for value in week_rain if value >= 1.0),
        "forecast_days": len(rows),
    }

    return {
        "region": {
            "id": region.id,
            "name": region.name,
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
        },
        "source": "open-meteo",
        "model": "best_match",
        "attribution": "Weather data by Open-Meteo.com",
        "attribution_url": "https://open-meteo.com/",
        "issued_at": datetime.now(dt_timezone.utc).isoformat(),
        "timezone": payload.get("timezone"),
        "days": rows,
        "climatology": _climatology(
            region.id, [date.fromisoformat(row["date"]) for row in rows]
        ),
        "summary": summary,
        "error": None,
    }


def get_region_forecast(region, days=DEFAULT_FORECAST_DAYS, use_cache=True):
    """Cached forecast payload for a region. Never raises for upstream errors."""
    if region is None:
        return None

    point = region_point(region)
    if point is None:
        return _error_payload(
            region, None,
            "This region has no coordinates. Add latitude/longitude to enable forecasts.",
        )

    days = max(1, min(int(days or DEFAULT_FORECAST_DAYS), MAX_FORECAST_DAYS))
    cache_key = (
        f"weather:forecast:{region.id}:{point[0]:.3f}:{point[1]:.3f}:{days}"
    )

    if use_cache:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    payload = fetch_region_forecast(region, days=days)
    if payload is None:
        payload = _error_payload(
            region, point,
            "The weather service is temporarily unavailable. Please try again shortly.",
        )
        if use_cache:
            cache.set(cache_key, payload, ERROR_CACHE_TTL)
        return payload

    cache.set(cache_key, payload, CACHE_TTL)
    return payload
