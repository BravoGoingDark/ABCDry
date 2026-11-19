"""Weather when Open-Meteo refuses us.

Open-Meteo's free API limits requests per network address. On shared hosting
(Render's free plan) that address is shared with many other apps, so the
server can get "429 Too Many Requests" without having asked much itself.
These sources take over in that case, in the same shape as Open-Meteo so the
rest of the code does not change:

* Forecast (about 10 days): MET Norway Locationforecast 2.0 (free,
  CC BY 4.0; it asks for a User-Agent that identifies the application).
* Past days for the watering balance: NASA POWER daily point data (free,
  public domain; the last 2-4 days are not published yet).

Neither gives reference evapotranspiration, so ET0 is computed with the
FAO-56 Penman-Monteith equation (eq. 6), the method Open-Meteo uses, from
daily Tmax/Tmin, humidity, wind and solar radiation: measured radiation from
NASA POWER, or radiation estimated from cloud cover (MET) or from the daily
temperature range (FAO-56 eq. 50) where none is published yet.
"""
from __future__ import annotations

import datetime as dt
import logging
import math
from collections import Counter, defaultdict
from statistics import mean

import requests

logger = logging.getLogger(__name__)

MET_URL = "https://api.met.no/weatherapi/locationforecast/2.0/complete"
POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
# MET Norway refuses anonymous clients: name the application and its site.
USER_AGENT = "APWRS-farmer/1.0 (+https://abcdry-1.onrender.com)"
TIMEOUT = (10, 30)
MISSING = -999.0

MET_SOURCE = {
    "source": "met-norway",
    "attribution": "Weather data by MET Norway (CC BY 4.0)",
    "attribution_url": "https://api.met.no/",
}

# MET Norway symbol (without _day/_night/_polartwilight) -> WMO weather code,
# the codes Open-Meteo uses and the rest of the app understands.
_SYMBOL_WMO = {
    "clearsky": 0, "fair": 1, "partlycloudy": 2, "cloudy": 3, "fog": 45,
    "lightrain": 61, "rain": 63, "heavyrain": 65,
    "lightrainshowers": 80, "rainshowers": 81, "heavyrainshowers": 82,
    "lightsleet": 66, "sleet": 67, "heavysleet": 67,
    "lightsleetshowers": 85, "sleetshowers": 85, "heavysleetshowers": 86,
    "lightsnow": 71, "snow": 73, "heavysnow": 75,
    "lightsnowshowers": 85, "snowshowers": 85, "heavysnowshowers": 86,
}


def symbol_to_wmo(symbol):
    if not symbol:
        return None
    base = symbol.split("_")[0]
    if "thunder" in base:
        return 95
    return _SYMBOL_WMO.get(base)


ELEVATION_M = 50.0  # the Ichkeul plain; ET0 hardly depends on it here


def extraterrestrial_radiation(lat, day):
    """Ra (MJ m-2 day-1), FAO-56 eq. 21-25."""
    j = day.timetuple().tm_yday
    phi = math.radians(lat)
    dr = 1 + 0.033 * math.cos(2 * math.pi * j / 365)
    delta = 0.409 * math.sin(2 * math.pi * j / 365 - 1.39)
    ws = math.acos(max(-1.0, min(1.0, -math.tan(phi) * math.tan(delta))))
    return (24 * 60 / math.pi) * 0.0820 * dr * (
        ws * math.sin(phi) * math.sin(delta) + math.cos(phi) * math.cos(delta) * math.sin(ws))


def _svp(t):
    """Saturation vapour pressure (kPa), FAO-56 eq. 11."""
    return 0.6108 * math.exp(17.27 * t / (t + 237.3))


def penman_monteith_et0(tmax, tmin, lat, day, *, rh_mean=None, ea=None, u2=None, rs=None):
    """FAO-56 Penman-Monteith reference ET (mm/day), eq. 6.

    Humidity as actual vapour pressure `ea` (kPa) or mean RH (%); wind `u2`
    (m/s at 2 m, default 2 m/s as FAO-56 advises when unknown); solar
    radiation `rs` (MJ m-2 day-1), estimated from the temperature range
    (eq. 50, coastal krs 0.19) when unknown."""
    if tmax is None or tmin is None:
        return None
    tmax, tmin = float(tmax), float(tmin)
    if tmax < tmin:
        tmax, tmin = tmin, tmax
    tmean = (tmax + tmin) / 2
    ra = extraterrestrial_radiation(lat, day)
    if rs is None:
        rs = 0.19 * math.sqrt(max(tmax - tmin, 0.0)) * ra
    rso = (0.75 + 2e-5 * ELEVATION_M) * ra
    rs = min(rs, rso)
    es = (_svp(tmax) + _svp(tmin)) / 2
    if ea is None:
        ea = es * (rh_mean / 100) if rh_mean is not None else _svp(tmin)  # eq. 48: Tdew ~ Tmin
    ea = min(ea, es)
    u2 = 2.0 if u2 is None else max(float(u2), 0.5)
    pressure = 101.3 * ((293 - 0.0065 * ELEVATION_M) / 293) ** 5.26
    gamma = 0.000665 * pressure
    delta = 4098 * _svp(tmean) / (tmean + 237.3) ** 2
    rns = 0.77 * rs
    sigma = 4.903e-9
    rnl = sigma * ((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2 * (0.34 - 0.14 * math.sqrt(ea)) * (
        1.35 * (rs / rso if rso > 0 else 0.5) - 0.35)
    rn = rns - rnl
    et0 = (0.408 * delta * rn + gamma * 900 / (tmean + 273) * u2 * (es - ea)) / (delta + gamma * (1 + 0.34 * u2))
    return round(max(et0, 0.0), 2)


def _utc_offset(lon):
    """Whole-hour offset from the longitude: good enough to cut days
    (Tunisia is UTC+1 all year, which this gives)."""
    return dt.timedelta(hours=round(lon / 15))


def met_norway_days(lat, lon):
    """MET Norway forecast as daily rows (local dates), plus hourly humidity.

    Returns (days, hourly) where days is a list of dicts with date, tmax, tmin,
    tmean, precip, wind_kmh, weather_code, et0 and hourly is
    {"time": [...], "relative_humidity_2m": [...]} in local time.
    Raises on network / HTTP / format errors."""
    resp = requests.get(MET_URL, params={"lat": round(lat, 4), "lon": round(lon, 4)},
                        headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    resp.raise_for_status()
    series = resp.json()["properties"]["timeseries"]
    offset = _utc_offset(lon)

    temps, rain, wind, symbols = defaultdict(list), defaultdict(float), defaultdict(list), defaultdict(Counter)
    dew, wind_ms, cloud = defaultdict(list), defaultdict(list), defaultdict(list)
    hourly_time, hourly_rh = [], []
    for entry in series:
        when = dt.datetime.fromisoformat(entry["time"].replace("Z", "+00:00")) + offset
        day = when.date()
        data = entry.get("data") or {}
        now = (data.get("instant") or {}).get("details") or {}
        if now.get("air_temperature") is not None:
            temps[day].append(float(now["air_temperature"]))
        if now.get("wind_speed") is not None:
            wind[day].append(float(now["wind_speed"]) * 3.6)  # m/s -> km/h
            wind_ms[day].append(float(now["wind_speed"]))
        if now.get("dew_point_temperature") is not None:
            dew[day].append(float(now["dew_point_temperature"]))
        if now.get("cloud_area_fraction") is not None and 7 <= when.hour <= 17:
            cloud[day].append(float(now["cloud_area_fraction"]) / 100)
        if now.get("relative_humidity") is not None:
            hourly_time.append(when.strftime("%Y-%m-%dT%H:%M"))
            hourly_rh.append(float(now["relative_humidity"]))
        # Rain: hourly steps first, 6-hourly steps once the hourly ones end
        # (never both for the same entry, so nothing is counted twice).
        one, six = data.get("next_1_hours"), data.get("next_6_hours")
        block = one or six
        if block:
            amount = (block.get("details") or {}).get("precipitation_amount")
            if amount is not None:
                rain[day] += float(amount)
            symbol = (block.get("summary") or {}).get("symbol_code")
            if symbol and 6 <= when.hour <= 18:
                symbols[day][symbol] += 1
        if not one and six:
            d6 = six.get("details") or {}
            for key in ("air_temperature_max", "air_temperature_min"):
                if d6.get(key) is not None:
                    temps[day].append(float(d6[key]))

    days = []
    for day in sorted(temps):
        values = temps[day]
        if len(values) < 3:  # a day the forecast barely reaches
            continue
        tmax, tmin = max(values), min(values)
        symbol = symbols[day].most_common(1)[0][0] if symbols[day] else None
        # Wettest symbol of the day if it rained, else the most common one.
        wet = [s for s in symbols[day] if "rain" in s or "snow" in s or "sleet" in s or "thunder" in s]
        if rain[day] >= 1.0 and wet:
            symbol = max(wet, key=lambda s: symbols[day][s])
        days.append({
            "date": day,
            "tmax": round(tmax, 1),
            "tmin": round(tmin, 1),
            "tmean": round(mean(values), 1),
            "precip": round(rain[day], 1),
            "wind_kmh": round(max(wind[day]), 1) if wind[day] else None,
            "weather_code": symbol_to_wmo(symbol),
            "et0": penman_monteith_et0(
                tmax, tmin, lat, day,
                ea=_svp(mean(dew[day])) if dew[day] else None,
                u2=mean(wind_ms[day]) * 0.748 if wind_ms[day] else None,  # 10 m -> 2 m, eq. 47
                # Angstrom (eq. 35) with the clear share of the daytime sky for n/N.
                rs=(0.25 + 0.5 * (1 - mean(cloud[day]))) * extraterrestrial_radiation(lat, day)
                if cloud[day] else None),
        })
    if not days:
        raise ValueError("MET Norway returned no usable days")
    return days, {"time": hourly_time, "relative_humidity_2m": hourly_rh}


def met_norway_forecast(lat, lon, days):
    """The MET Norway forecast in Open-Meteo's response shape (the fields
    weather_forecast.fetch_region_forecast reads)."""
    rows, hourly = met_norway_days(lat, lon)
    rows = rows[:days]
    return {
        "timezone": None,
        "daily": {
            "time": [r["date"].isoformat() for r in rows],
            "weather_code": [r["weather_code"] for r in rows],
            "temperature_2m_max": [r["tmax"] for r in rows],
            "temperature_2m_min": [r["tmin"] for r in rows],
            "temperature_2m_mean": [r["tmean"] for r in rows],
            "precipitation_sum": [r["precip"] for r in rows],
            "precipitation_probability_max": [None for _ in rows],
            "et0_fao_evapotranspiration": [r["et0"] for r in rows],
            "wind_speed_10m_max": [r["wind_kmh"] for r in rows],
        },
        "hourly": hourly,
    }


def power_days(lat, lon, start, end):
    """NASA POWER daily rows between two dates (missing days left out).
    Raises on network / HTTP / format errors."""
    resp = requests.get(POWER_URL, params={
        "parameters": "PRECTOTCORR,T2M_MAX,T2M_MIN,WS2M,RH2M,ALLSKY_SFC_SW_DWN",
        "community": "AG",
        "latitude": round(lat, 4), "longitude": round(lon, 4),
        "start": start.strftime("%Y%m%d"), "end": end.strftime("%Y%m%d"),
        "format": "JSON",
    }, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    resp.raise_for_status()
    p = resp.json()["properties"]["parameter"]

    def val(name, key):
        v = (p.get(name) or {}).get(key)
        return None if v is None or float(v) <= MISSING else float(v)

    rows = []
    for key in sorted(p.get("T2M_MAX") or {}):
        day = dt.datetime.strptime(key, "%Y%m%d").date()
        tmax, tmin, rain = val("T2M_MAX", key), val("T2M_MIN", key), val("PRECTOTCORR", key)
        if tmax is None or tmin is None or rain is None:
            continue
        ws2 = val("WS2M", key)
        rows.append({
            "date": day,
            "precip": round(rain, 1),
            "et0": penman_monteith_et0(tmax, tmin, lat, day, rh_mean=val("RH2M", key), u2=ws2,
                                       rs=val("ALLSKY_SFC_SW_DWN", key)),
            "tmax": round(tmax, 1),
            # Daily mean at 2 m -> 10 m (FAO-56 eq. 47), in km/h.
            "wind": round(ws2 / 0.748 * 3.6, 1) if ws2 is not None else None,
            "precip_prob": None,
        })
    return rows


def daily_water(lat, lon, past_days, forecast_days, today=None):
    """Rows for the watering balance (irrigation_schedule.fetch_daily_water's
    shape): NASA POWER for the past, MET Norway for today on. Days neither
    covers yet (the few before POWER catches up) get no rain and the mean ET0
    of the last week, so the balance runs day by day without a hole.
    Raises if the forecast is unavailable (the plan needs today)."""
    today = today or dt.date.today()
    forecast, _ = met_norway_days(lat, lon)
    future = [{"date": r["date"], "precip": r["precip"], "et0": r["et0"], "tmax": r["tmax"],
               "wind": r["wind_kmh"], "precip_prob": None}
              for r in forecast if r["date"] >= today][:forecast_days]
    try:
        past = power_days(lat, lon, today - dt.timedelta(days=past_days), today - dt.timedelta(days=1))
    except Exception as exc:  # the forecast alone still gives a plan
        logger.warning("NASA POWER history failed at (%s, %s): %r", lat, lon, exc)
        past = []

    by_day = {r["date"]: r for r in past}
    if past:
        recent_et0 = [r["et0"] for r in past[-7:] if r["et0"] is not None]
        fill_et0 = round(mean(recent_et0), 2) if recent_et0 else None
        day = past[0]["date"]
        while day < today:
            if day not in by_day and fill_et0 is not None:
                by_day[day] = {"date": day, "precip": 0.0, "et0": fill_et0, "tmax": None,
                               "wind": None, "precip_prob": None}
            day += dt.timedelta(days=1)
    rows = [by_day[d] for d in sorted(by_day)] + future
    if not future:
        raise ValueError("MET Norway gave no days from today on")
    return rows
