"""SmartFarm (my.smartfarm.com.tn) client for the capacitive soil probe.

The probe reports soil moisture at three depths (20, 40 and 60 cm by default)
and a soil temperature, roughly once a day. SmartFarm calibrates each channel
from the raw 12-bit ADC reading (`niv1..3`) between a dry point (4095) and a
wet point (~1500) and returns the result as a percentage (`mv1..3`).

SmartFarm has no public API keys: we sign in the way its web app does.
Credentials come from the environment and are never committed. Either

    SMARTFARM_EMAIL=...
    SMARTFARM_PASSWORD=...       POST /login, as the web app's login form

or, without storing the password,

    SMARTFARM_EMAIL=...
    SMARTFARM_UID=...            user id from the SmartFarm login payload
    SMARTFARM_REFRESH_TOKEN=...  long-lived; 24 h access tokens are minted from it

plus, optionally, SMARTFARM_SENSOR=88:57:21:D2:1C:08 (default: the account's
first probe). Without credentials `configured()` is False and nothing calls out.
"""
import base64
import datetime as dt
import json
import logging
import os
import re
import time

import requests
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

API = 'https://my.smartfarm.com.tn/api'
SOURCE = 'smartfarm'
TIMEOUT = 20
TOKEN_CACHE_KEY = 'smartfarm:access_token'
SYNC_LOCK_KEY = 'smartfarm:sync_lock'
# The probe's clock runs on Tunisian wall time (UTC+1, no DST), but SmartFarm
# stores `timestamp_arduino` as if it were UTC; the hour is taken back out.
PROBE_UTC_OFFSET = dt.timedelta(hours=1)


class SmartFarmError(Exception):
    pass


def _env(name):
    """An env value as pasted into a hosting dashboard: trimmed, quotes removed,
    and a pasted {"token": "..."} object unwrapped. SmartFarm answers any of
    those with a bare "Invalid token"."""
    v = (os.getenv(name) or '').strip()
    if v.startswith('{'):
        try:
            o = json.loads(v)
            v = o.get('refreshToken') or o.get('token') or v
        except ValueError:
            pass
    return re.sub(r'^(["\'])(.*)\1$', r'\2', v).strip()


def credentials():
    return {k: _env(f'SMARTFARM_{k.upper()}')
            for k in ('email', 'password', 'uid', 'refresh_token', 'sensor')}


def missing_settings(creds=None):
    """Env names still needed; empty when SmartFarm can be called."""
    c = creds or credentials()
    if not c['email']:
        return ['SMARTFARM_EMAIL', 'SMARTFARM_PASSWORD']
    if c['password'] or (c['uid'] and c['refresh_token']):
        return []
    return ['SMARTFARM_PASSWORD']


def configured():
    return not missing_settings()


# ── Auth ────────────────────────────────────────────────────────────────

def _jwt_payload(token):
    try:
        part = token.split('.')[1]
        return json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))
    except (IndexError, ValueError):
        return None


def credential_problem(creds):
    """Why SmartFarm would reject these credentials, worked out locally from the
    refresh token's own payload, so the cause can be named without a request.
    A password login can only be judged by SmartFarm itself."""
    if creds.get('password'):
        return None
    p = _jwt_payload(creds['refresh_token'])
    if not p:
        return 'SMARTFARM_REFRESH_TOKEN is not a token (check it was pasted whole)'
    if p.get('exp') and p.get('iat') and p['exp'] - p['iat'] <= 2 * 86400:
        return 'SMARTFARM_REFRESH_TOKEN holds the short-lived access token, not the refresh token'
    if p.get('exp') and p['exp'] < time.time():
        return 'SMARTFARM_REFRESH_TOKEN has expired; log in to SmartFarm for a new one'
    if p.get('email') and p['email'] != creds['email']:
        return 'SMARTFARM_EMAIL does not match the refresh token (it is case-sensitive)'
    if p.get('id') and p['id'] != creds['uid']:
        return 'SMARTFARM_UID does not match the refresh token'
    return None


def _access_token(force=False):
    if not force:
        token = cache.get(TOKEN_CACHE_KEY)
        if token:
            return token
    creds = credentials()
    token = _login(creds) if creds['password'] else _refresh(creds)
    # Tokens live 24 h; renew 5 min before expiry.
    exp = (_jwt_payload(token) or {}).get('exp')
    ttl = int(exp - time.time() - 300) if exp else 3600
    cache.set(TOKEN_CACHE_KEY, token, max(60, ttl))
    return token


def _json(res):
    try:
        body = res.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _login(creds):
    """Email + password, as SmartFarm's own login form posts them."""
    res = requests.post(f'{API}/login', timeout=TIMEOUT,
                        json={'email': creds['email'], 'password': creds['password']})
    body = _json(res)
    if body.get('errors'):
        raise SmartFarmError(f"SmartFarm login failed: {body['errors'][0].get('msg', 'rejected')}")
    if body.get('type') == 'danger' or not body.get('token'):
        reason = {'400': 'wrong password', '404': 'unknown email'}.get(str(body.get('status')))
        raise SmartFarmError('SmartFarm login failed: ' + (reason or body.get('message') or str(res.status_code)))
    return body['token']


def _refresh(creds):
    problem = credential_problem(creds)
    if problem:
        raise SmartFarmError(f'SmartFarm credentials: {problem}')
    res = requests.post(f'{API}/refresh', timeout=TIMEOUT, json={
        'email': creds['email'], 'role': 'ROLE_USER',
        'uid': creds['uid'], 'refreshToken': creds['refresh_token'],
    })
    body = _json(res)
    if not res.ok or not body.get('token'):
        msg = body.get('message')
        raise SmartFarmError(f'SmartFarm auth failed: {res.status_code}' + (f' ({msg})' if msg else ''))
    return body['token']


def _get(path):
    """GET against the SmartFarm API, retrying once with a fresh token on 401/403."""
    for attempt in range(2):
        token = _access_token(force=attempt > 0)
        res = requests.get(f'{API}{path}', timeout=TIMEOUT,
                           headers={'Authorization': f'Bearer {token}'})
        if res.status_code in (401, 403) and attempt == 0:
            continue
        if not res.ok:
            raise SmartFarmError(f"SmartFarm {path.split('?')[0]}: {res.status_code}")
        return res.json()
    raise SmartFarmError('SmartFarm: unauthorised after token refresh')


# ── Parsing ─────────────────────────────────────────────────────────────

def _moisture(pct, raw):
    """A raw ADC value of 4095 is the top of the 12-bit range: the channel reads
    open circuit, as a probe does in air before it is buried. SmartFarm turns
    that into 0 %, which would read as bone-dry soil, so it is dropped."""
    if pct is None:
        return None
    try:
        if raw is not None and float(raw) >= 4095:
            return None
        return float(pct)
    except (TypeError, ValueError):
        return None


def _temperature(ts):
    """-127 °C is the temperature sensor's "not connected" code."""
    try:
        t = float(ts)
    except (TypeError, ValueError):
        return None
    return t if t > -100 else None


def _parse_time(stamp, probe_clock):
    if not stamp or stamp == 'null':
        return None
    s = str(stamp).strip()
    if probe_clock:
        s = re.sub(r'(Z|[+-]\d{2}:?\d{2})$', '', s)
    try:
        t = dt.datetime.fromisoformat(s.replace('Z', '+00:00').replace(' ', 'T'))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t - PROBE_UTC_OFFSET if probe_clock else t


def parse_reading(raw):
    when = _parse_time(raw.get('timestamp_arduino'), True) or _parse_time(raw.get('time'), False)
    if when is None:
        return None
    return {
        'measured_at': when,
        'moisture_1': _moisture(raw.get('mv1'), raw.get('niv1')),
        'moisture_2': _moisture(raw.get('mv2'), raw.get('niv2')),
        'moisture_3': _moisture(raw.get('mv3'), raw.get('niv3')),
        'soil_temp_c': _temperature(raw.get('ts')),
    }


def _float_or_none(v):
    try:
        return float(v) if v not in (None, '') else None
    except (TypeError, ValueError):
        return None


# ── Fetch + store ───────────────────────────────────────────────────────

def fetch_probe(days):
    """The configured probe's metadata and readings over the last `days` days."""
    code = credentials()['sensor']
    sensors = _get('/sensor/sensors') or []
    if not code:
        if not sensors:
            raise SmartFarmError('SmartFarm: this account has no sensor')
        code = sensors[0].get('code')
    sensor = next((s for s in sensors if s.get('code') == code), None)
    if not sensor:
        raise SmartFarmError(f'SmartFarm: sensor {code} is not on this account')

    end = timezone.now().date() + dt.timedelta(days=1)   # tomorrow, so no time-zone edge drops today
    start = timezone.now().date() - dt.timedelta(days=days)
    base = f"/sensor/sensor-history/{requests.utils.quote(code, safe='')}/{start}/{end}"
    raw, page, pages = [], 0, 1
    while page < pages and page < 20:
        body = _get(f'{base}?pageNum={page}&limit=500') or {}
        raw.extend(body.get('history') or [])
        pages = body.get('totalPages') or 1
        page += 1

    fields = sensor.get('fields') or {}
    return {
        'code': code,
        'field': fields.get('name'),
        'lat': _float_or_none(fields.get('Latitude')),
        'lon': _float_or_none(fields.get('Longitude')),
        'status': sensor.get('etat'),
        'depths': [sensor.get('mv1') or 20, sensor.get('mv2') or 40, sensor.get('mv3') or 60],
        'readings': [r for r in (parse_reading(x) for x in raw) if r],
    }


def _nearest_region(lat, lon):
    from ..models import Region
    from ..views.utils import _haversine_distance
    best = None
    for r in Region.objects.exclude(latitude=None).exclude(longitude=None):
        d = _haversine_distance(lat, lon, float(r.latitude), float(r.longitude))
        if best is None or d < best[0]:
            best = (d, r)
    return best[1] if best else None


def sync(days=120):
    """Pull the probe's readings into Sensor + SoilProbeReading. Idempotent:
    readings are keyed by (sensor, measured_at). Returns a summary dict."""
    from ..models import Sensor, SoilProbeReading

    probe = fetch_probe(days)
    with transaction.atomic():
        sensor = Sensor.objects.filter(external_source=SOURCE, external_id=probe['code']).first()
        if sensor is None:
            # Without coordinates on SmartFarm, pin it to the basin centre until edited.
            lat = probe['lat'] if probe['lat'] is not None else 36.9
            lon = probe['lon'] if probe['lon'] is not None else 9.4
            sensor = Sensor.objects.create(
                name=f"S.Sensor · {probe['field'] or probe['code']}",
                sensor_type='soil', latitude=lat, longitude=lon, coverage_radius_km=0,
                region=_nearest_region(lat, lon),
                description='SmartFarm capacitive soil probe: moisture at three depths and soil '
                            'temperature, about one reading a day.',
                external_source=SOURCE, external_id=probe['code'],
            )
        elif probe['lat'] is not None and probe['lon'] is not None:
            sensor.latitude, sensor.longitude = probe['lat'], probe['lon']
        sensor.external_meta = {'depths': probe['depths'], 'field': probe['field'], 'status': probe['status']}
        sensor.last_synced_at = timezone.now()
        sensor.is_active = True
        sensor.save()

        known = set(SoilProbeReading.objects.filter(sensor=sensor).values_list('measured_at', flat=True))
        new, seen = [], set()
        for r in probe['readings']:
            if r['measured_at'] in known or r['measured_at'] in seen:
                continue
            seen.add(r['measured_at'])
            new.append(SoilProbeReading(sensor=sensor, **r))
        SoilProbeReading.objects.bulk_create(new, ignore_conflicts=True)

    return {'sensor_id': sensor.id, 'fetched': len(probe['readings']), 'added': len(new)}


def sync_if_stale(max_age_minutes=60, days=120):
    """Sync when the last pull is older than `max_age_minutes`, so pages stay
    fresh even where no scheduler runs. Never raises; returns the error text."""
    from ..models import Sensor

    if not configured():
        return None
    last = (Sensor.objects.filter(external_source=SOURCE).order_by('-last_synced_at')
            .values_list('last_synced_at', flat=True).first())
    if last and timezone.now() - last < dt.timedelta(minutes=max_age_minutes):
        return None
    # One sync at a time, and back off for 10 min after a failure.
    if not cache.add(SYNC_LOCK_KEY, 1, 600):
        return cache.get('smartfarm:last_error')
    try:
        sync(days)
        cache.delete('smartfarm:last_error')
        cache.delete(SYNC_LOCK_KEY)
        return None
    except (SmartFarmError, requests.RequestException) as exc:
        logger.warning('SmartFarm sync failed: %s', exc)
        cache.set('smartfarm:last_error', str(exc), 600)
        return str(exc)
