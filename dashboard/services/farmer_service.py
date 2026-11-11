"""Farm parcels for the farmer role: geometry, soil, advice and weather.

A farm is a GeoJSON polygon drawn by the farmer. Everything shown to the
farmer is derived from it:
  * soil       SoilGrids 0-30 cm at the parcel centroid (fetched once, cached
               on the Farm row)
  * climate    monthly climatology of the nearest region that has climate
               history (the project only records data for a few regions)
  * advice     crop_suitability ranking + crop_management plan
  * weather    Open-Meteo forecast at the parcel centroid + field alerts
"""
import logging
import math
import threading
from types import SimpleNamespace

from django import db
from django.db import transaction

from dashboard.models import ClimateMetrics, Region
from dashboard.prediction_engine.physical_helpers import (
    calculate_field_capacity, calculate_wilting_point)

from . import crop_management, crop_suitability

logger = logging.getLogger(__name__)

EARTH_RADIUS_M = 6371008.8
MAX_VERTICES = 1000
MIN_AREA_HA = 0.01
MAX_AREA_HA = 10000.0
FAR_REGION_KM = 75.0


class FarmGeometryError(ValueError):
    pass


# ------------------------------------------------------------------ #
# Geometry
# ------------------------------------------------------------------ #

def clean_polygon(geojson):
    """Validate a GeoJSON Polygon (or a Feature holding one) drawn on the map.

    Returns a normalised {'type': 'Polygon', 'coordinates': [ring]} with a
    single closed outer ring of [lon, lat] floats. Holes are dropped: a farm
    boundary drawn with Leaflet.draw never has them.
    """
    if isinstance(geojson, dict) and geojson.get('type') == 'Feature':
        geojson = geojson.get('geometry')
    if not isinstance(geojson, dict) or geojson.get('type') != 'Polygon':
        raise FarmGeometryError('The boundary must be a polygon.')
    rings = geojson.get('coordinates')
    if not isinstance(rings, list) or not rings or not isinstance(rings[0], list):
        raise FarmGeometryError('The polygon has no coordinates.')

    ring = []
    for point in rings[0]:
        try:
            lon, lat = float(point[0]), float(point[1])
        except (TypeError, ValueError, IndexError):
            raise FarmGeometryError('Invalid coordinate in the polygon.')
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise FarmGeometryError('Coordinate out of range.')
        ring.append([round(lon, 7), round(lat, 7)])
    if ring and ring[0] != ring[-1]:
        ring.append(list(ring[0]))
    if len(ring) < 4:
        raise FarmGeometryError('Draw at least three corners.')
    if len(ring) > MAX_VERTICES:
        raise FarmGeometryError(f'Too many corners (max {MAX_VERTICES}).')
    return {'type': 'Polygon', 'coordinates': [ring]}


def _project(ring):
    """Local equirectangular projection in metres around the ring's mean
    latitude: accurate to well under 1% for parcels of a few km."""
    lat0 = math.radians(sum(p[1] for p in ring) / len(ring))
    return [(math.radians(lon) * EARTH_RADIUS_M * math.cos(lat0),
             math.radians(lat) * EARTH_RADIUS_M) for lon, lat in ring], lat0


def polygon_area_centroid(polygon):
    """(area_ha, centroid_lat, centroid_lon) of a cleaned polygon."""
    ring = polygon['coordinates'][0]
    pts, lat0 = _project(ring)
    a = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        cross = x0 * y1 - x1 * y0
        a += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    a /= 2.0
    if abs(a) < 1e-6:
        raise FarmGeometryError('The polygon has no area.')
    cx /= 6.0 * a
    cy /= 6.0 * a
    lat = math.degrees(cy / EARTH_RADIUS_M)
    lon = math.degrees(cx / (EARTH_RADIUS_M * math.cos(lat0)))
    return abs(a) / 10000.0, lat, lon


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def nearest_region(lat, lon):
    """(region, distance_km) of the closest region that has climate history."""
    with_data = set(ClimateMetrics.objects.values_list('region_id', flat=True).distinct())
    best = (None, None)
    for region in Region.objects.filter(id__in=with_data):
        if region.latitude is not None and region.longitude is not None:
            points = [(float(region.latitude), float(region.longitude))]
        elif region.sample_points:
            points = [(float(p['lat']), float(p['lon'])) for p in region.sample_points]
        else:
            continue
        d = min(haversine_km(lat, lon, plat, plon) for plat, plon in points)
        if best[1] is None or d < best[1]:
            best = (region, d)
    return best


def apply_boundary(farm, geojson):
    """Validate + store the boundary and every value derived from it."""
    polygon = clean_polygon(geojson)
    area_ha, lat, lon = polygon_area_centroid(polygon)
    if area_ha < MIN_AREA_HA:
        raise FarmGeometryError('The parcel is too small (under 100 m2).')
    if area_ha > MAX_AREA_HA:
        raise FarmGeometryError(f'The parcel is too large (over {MAX_AREA_HA:.0f} ha).')
    moved = farm.centroid_lat is None or haversine_km(
        float(farm.centroid_lat), float(farm.centroid_lon), lat, lon) > 0.25
    farm.boundary = polygon
    farm.area_ha = round(area_ha, 2)
    farm.centroid_lat = round(lat, 6)
    farm.centroid_lon = round(lon, 6)
    farm.region, _ = nearest_region(lat, lon)
    if moved:
        farm.soil = None  # refetched for the new location


# ------------------------------------------------------------------ #
# Soil
# ------------------------------------------------------------------ #

SOIL_PROBE_OFFSET_DEG = 0.02  # ~2 km: clears a small town


def ensure_soil(farm, timeout=15):
    """Fetch SoilGrids for the parcel once; never raises (soil is optional).

    SoilGrids masks urban and water pixels. When the centroid is masked, up
    to four points ~2 km around it are probed one at a time (SoilGrids allows
    ~5 requests/min, parallel calls get throttled) until one has data. A
    parcel with no soil data around it is remembered as unavailable so later
    page loads skip the slow lookups; if a request failed (network, throttling)
    nothing is remembered and the lookup is retried next time.
    """
    if farm.soil:
        return None if farm.soil.get('unavailable') else farm.soil
    from .soilgrids import fetch_point

    lat, lon = float(farm.centroid_lat), float(farm.centroid_lon)
    d = SOIL_PROBE_OFFSET_DEG
    points = [(lat, lon), (lat + d, lon), (lat, lon + d), (lat - d, lon), (lat, lon - d)]
    soil, failures = None, 0
    for i, (plat, plon) in enumerate(points):
        try:
            soil = fetch_point(plat, plon, timeout=timeout)
        except Exception as exc:  # network, HTTP, JSON
            logger.warning('SoilGrids failed for farm %s at (%s, %s): %s', farm.pk, plat, plon, exc)
            failures += 1
            if i == 0:
                return None  # service down: do not spend 4 more timeouts
            continue
        if soil:
            if i:
                soil['note'] = 'Parcel centre not mapped by SoilGrids; nearest data ~2 km away.'
            break
    if not soil and failures:
        return None

    farm.soil = soil or {'unavailable': True}
    if soil:
        soil['source'] = 'ISRIC SoilGrids 2.0 (modelled, 250 m)'
    if farm.pk:
        farm.save(update_fields=['soil', 'updated_at'])
    return soil


_soil_lookups_in_flight = set()
_soil_lock = threading.Lock()


def schedule_soil_lookup(farm_id):
    """Run ensure_soil in a background thread once the current transaction
    commits. SoilGrids answers in 10-25 s and throttles bursts, so page and
    API requests never wait for it; advice uses the region's soil until the
    parcel's own arrives. One lookup per farm at a time.
    """
    def start():
        with _soil_lock:
            if farm_id in _soil_lookups_in_flight:
                return
            _soil_lookups_in_flight.add(farm_id)
        threading.Thread(target=_soil_worker, args=(farm_id,), daemon=True).start()

    transaction.on_commit(start)


def _soil_worker(farm_id):
    from dashboard.models import Farm
    try:
        farm = Farm.objects.filter(pk=farm_id).first()
        if farm is not None and farm.soil is None:
            ensure_soil(farm)
    except Exception:
        logger.exception('Background soil lookup failed for farm %s', farm_id)
    finally:
        with _soil_lock:
            _soil_lookups_in_flight.discard(farm_id)
        db.connection.close()


def suitability_soil(soil):
    """Map a stored SoilGrids dict onto crop_suitability's soil input."""
    if not soil or soil.get('unavailable'):
        return None
    out = {'sand_pct': soil.get('sand'), 'clay_pct': soil.get('clay'),
           'ph': soil.get('ph'), 'ece_dsm': soil.get('ece')}
    if None not in (soil.get('sand'), soil.get('clay'), soil.get('silt')):
        fc = calculate_field_capacity(soil['sand'], soil['clay'], soil['silt'], soil.get('om') or 0)
        wp = calculate_wilting_point(soil['sand'], soil['clay'], soil['silt'])
        if fc > wp:
            out['awc_mm_per_m'] = (fc - wp) * 10.0
    out['texture_class'] = crop_suitability.texture_class(out['sand_pct'], out['clay_pct'])
    return out


# ------------------------------------------------------------------ #
# Advice and weather
# ------------------------------------------------------------------ #

def farm_advice(farm, month, today=None):
    """Ranked crop recommendations + plan for the farm's current crop."""
    if farm.region is None:
        return {'error': 'No region with climate data is available near this farm.'}
    clim = crop_suitability.region_climatology(farm.region)
    if clim is None:
        return {'error': f'Not enough climate history for {farm.region.name}.'}

    soil_raw = farm.soil if farm.soil and not farm.soil.get('unavailable') else None
    if farm.soil is None:
        schedule_soil_lookup(farm.pk)  # retry a lookup that failed earlier
    soil = suitability_soil(soil_raw)
    soil_note = None
    if soil is None:
        soil = crop_suitability.region_soil(farm.region)
        if soil:
            pending = ' (the parcel soil is still loading)' if farm.soil is None else ''
            soil_note = (f'Soil of this parcel is not available{pending}: the average soil of '
                         f'{farm.region.name} was used instead.')
    scenario, outlook = crop_suitability.drought_scenario(farm.region)
    mode = 'irrigated' if farm.irrigated else 'rainfed'
    water = float(farm.water_supply_mm) if farm.water_supply_mm is not None else None
    ranking = crop_suitability.rank_crops(clim, soil, month=month, mode=mode,
                                          scenario=scenario, water_supply_mm=water)

    distance = haversine_km(float(farm.centroid_lat), float(farm.centroid_lon),
                            *_region_point(farm.region))
    notes = []
    if distance > FAR_REGION_KM:
        notes.append(f'Climate is taken from {farm.region.name}, {distance:.0f} km away: '
                     'treat the water figures as approximate.')
    if soil_note:
        notes.append(soil_note)
    elif not soil:
        notes.append('Soil data could not be loaded: pH and texture were not scored.')
    if soil_raw and soil_raw.get('note'):
        notes.append(soil_raw['note'])
    if scenario == 'dry':
        notes.append('The 1-month drought outlook warns of dry conditions: rainfall was '
                     'set to a dry year (25th percentile).')

    return {
        'month': month,
        'mode': mode,
        'scenario': scenario,
        'drought_outlook_t1': outlook,
        'climate_region': farm.region.name,
        'climate_region_km': round(distance, 1),
        'climate_period': clim['_meta']['years'],
        'soil': soil_raw,
        'texture_class': soil.get('texture_class') if soil else None,
        'notes': notes,
        'plant_now': [r for r in ranking if r['plantable_now'] and r['class'] in ('S1', 'S2')],
        'ranking': ranking,
        'current_crop_plan': crop_management.crop_plan(
            farm.crop, farm.sowing_date, today) if farm.crop else None,
    }


def _region_point(region):
    if region.latitude is not None and region.longitude is not None:
        return float(region.latitude), float(region.longitude)
    p = region.sample_points[0]
    return float(p['lat']), float(p['lon'])


def farm_weather(farm, days=16):
    """Open-Meteo forecast at the parcel centroid plus field alerts."""
    from .weather_forecast import get_region_forecast

    # The forecast service only needs a point, a name and an id; the id is the
    # nearest region's, so the "normal" reference line uses observed history.
    point = SimpleNamespace(id=farm.region_id or 0, name=farm.name,
                            latitude=farm.centroid_lat, longitude=farm.centroid_lon)
    payload = get_region_forecast(point, days=days)
    alerts = crop_management.weather_alerts(payload.get('days') or [], farm.crop or None) \
        if payload and not payload.get('error') else []
    return {'forecast': payload, 'alerts': alerts}


def serialize_farm(farm):
    return {
        'id': farm.pk,
        'name': farm.name,
        'owner': farm.owner.username if farm.owner else None,
        'boundary': farm.boundary,
        'area_ha': float(farm.area_ha),
        'centroid': [float(farm.centroid_lat), float(farm.centroid_lon)],
        'region': farm.region.name if farm.region else None,
        'region_id': farm.region_id,
        'crop': farm.crop or None,
        'crop_name': crop_suitability.CROPS[farm.crop]['names']['en'] if farm.crop in crop_suitability.CROPS else None,
        'sowing_date': farm.sowing_date.isoformat() if farm.sowing_date else None,
        'irrigated': farm.irrigated,
        'water_supply_mm': float(farm.water_supply_mm) if farm.water_supply_mm is not None else None,
        'soil': farm.soil,
    }
