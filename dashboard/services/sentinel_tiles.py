"""Map layers over the Ichkeul catchment (analysis page), computed in Earth Engine.

  ndvi  Sentinel-2 L2A, (B8 - B4) / (B8 + B4): green vegetation. Least-cloud
        mosaic of the last 30 days, land pixels only (SCL 4, 5, 7: cloud,
        shadow and open water are left transparent). 10 m.
  ndwi  Same, (B8 - B11) / (B8 + B11), Gao's form: water held in vegetation
        and topsoil, which falls ahead of NDVI as a drought sets in. 20 m.
  temp  ERA5-Land (Copernicus), mean daily 2 m temperature over the last 30
        days available (~1 week behind real time), downscaled to the 90 m
        SRTM terrain with a lapse rate: T = T_era5 + LAPSE * (z_90m - z_cell),
        z_cell = mean SRTM height of the ERA5-Land cell. The 0.1° field is
        interpolated bilinearly first, so cell edges do not show.
  rain  ERA5-Land total precipitation summed over the same last 30 days,
        interpolated bilinearly between the 0.1° (~9 km) cell centres. No
        finer rain exists: the smoothing is display only, not extra detail.
  spi   SPI-3 from ERA5-Land rain: the last 90 days ranked against the same
        90 days in each of the 30 previous years (Gringorten plotting position
        -> standard normal), the non-parametric SPI. Same rain and window as
        the drought layer's SPI-3 input. Smoothed like rain.
  drought  Combined Drought Indicator, after the European Drought Observatory:
        0 none, 1 watch (SPI-3 < -1), 2 warning (+ root-zone soil moisture
        anomaly < -1), 3 alert (+ vegetation anomaly < -1). Rain and soil
        moisture from ERA5-Land (fresher than CHIRPS; same drought verdict at
        the stations 93-94 % of days), each against the same window in the 30
        previous years; vegetation from MODIS NDVI (250 m) against 2001 on.
        Open water (JRC occurrence > 50 %) is left out.

Each 256 px web-mercator tile is clipped to the catchment outline and coloured
here on the layer's ramp. The service account may not create Earth Engine map
ids, so pixels are pulled with computePixels and the float values are cached on
disk per day; clicks on the map read the value from the same cache.
"""
import datetime as dt
import io
import json
import logging
import math
import os
import shutil
import threading
from functools import lru_cache

import numpy as np
from django.conf import settings

logger = logging.getLogger(__name__)

MIN_ZOOM, MAX_ZOOM = 8, 16
TILE = 256
NO_VALUE = -9999
_R = 20037508.342789244
S2_DAYS, CLIMATE_DAYS, SPI_DAYS, SPI_YEARS = 30, 30, 90, 30
MODIS_FIRST_YEAR = 2001
LAPSE_C_PER_M = -0.0065   # standard environmental lapse rate, -6.5 °C per km
DROUGHT_CLASSES = ('none', 'watch', 'warning', 'alert')
META_VERSION = 4   # bump when day_meta() or a layer changes: a cached day (meta + tiles) is recomputed

# Colour ramps (low -> high), scales and display. A domain of None is stretched
# each day over the basin's 2nd-98th percentile (rain from 0).
LAYERS = {
    'ndvi': {'ramp': ['#A0522D', '#D9B26F', '#F2E8A0', '#9ACD6B', '#3E9B4F', '#1F6B35'],
             'domain': (0.0, 0.8), 'ends': ('Bare', 'Dense'), 'unit': '', 'decimals': 2, 'max_zoom': 16,
             'source': 'Sentinel-2 L2A · least-cloud mosaic'},
    'ndwi': {'ramp': ['#B5651D', '#E3C27A', '#F3EFD2', '#8CC7D9', '#3A8FC4', '#1F4E9E'],
             'domain': (-0.3, 0.4), 'ends': ('Dry', 'Moist'), 'unit': '', 'decimals': 2, 'max_zoom': 16,
             'source': 'Sentinel-2 L2A · least-cloud mosaic'},
    'temp': {'ramp': ['#FFF3B0', '#FDC46B', '#F98C4A', '#E0663F', '#B8282E'],
             'domain': None, 'ends': ('Cooler', 'Hotter'), 'unit': '°C', 'decimals': 1, 'max_zoom': 12,
             'source': 'ERA5-Land (Copernicus) · mean daily temperature · terrain-corrected 90 m'},
    'rain': {'ramp': ['#F7FBFF', '#C6DBEF', '#6BAED6', '#2F7FD1', '#08306B'],
             'domain': None, 'ends': ('Less', 'More'), 'unit': 'mm', 'decimals': 0, 'max_zoom': 12,
             'source': 'ERA5-Land (Copernicus) · total rainfall · smoothed from 9 km'},
    'spi':  {'ramp': ['#B2182B', '#EF8A62', '#F7F7F7', '#67A9CF', '#2166AC'],
             'domain': (-2.0, 2.0), 'ends': ('Drier', 'Wetter'), 'unit': '', 'decimals': 2, 'max_zoom': 12,
             'source': 'SPI-3 · ERA5-Land rainfall vs 30 previous years · smoothed from 9 km'},
    'drought': {'ramp': ['#38A88A', '#E7A83B', '#EE8434', '#D96565'],
                'domain': (0, 3), 'ends': ('No drought', 'Alert'), 'unit': '', 'decimals': 0, 'max_zoom': 13,
                'source': 'Combined Drought Indicator · ERA5-Land + MODIS'},
}
INDICES = LAYERS  # older name, kept for callers

BASIN_GEOJSON = os.path.join(settings.BASE_DIR, 'static', 'dashboard', 'data', 'ichkeul_basin.geojson')
CACHE_DIR = os.getenv('S2_TILE_CACHE_DIR') or os.path.join(settings.BASE_DIR, 'tilecache', 's2')


class SentinelUnavailable(Exception):
    pass


# ── Geometry ────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def basin_outline():
    with open(BASIN_GEOJSON, encoding='utf-8') as f:
        gj = json.load(f)
    return next(ft['geometry'] for ft in gj['features'] if ft['properties'].get('kind') == 'outline')


@lru_cache(maxsize=1)
def basin_bounds():
    """[west, south, east, north] of the outline, with a small margin."""
    pts = [p for ring in basin_outline()['coordinates'] for p in ring]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs) - 0.02, min(ys) - 0.02, max(xs) + 0.02, max(ys) + 0.02


def lonlat_to_tile(lon, lat, z):
    n = 2 ** z
    r = math.radians(lat)
    return (lon + 180) / 360 * n, (1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * n


def tile_in_basin(z, x, y, layer=None):
    top = LAYERS[layer]['max_zoom'] if layer in LAYERS else MAX_ZOOM
    if not (MIN_ZOOM <= z <= top):
        return False
    w, s, e, n = basin_bounds()
    x0, y0 = lonlat_to_tile(w, n, z)
    x1, y1 = lonlat_to_tile(e, s, z)
    return math.floor(x0) <= x <= math.floor(x1) and math.floor(y0) <= y <= math.floor(y1)


# ── Earth Engine ────────────────────────────────────────────────────────

_ee_lock = threading.Lock()
_meta_lock = threading.Lock()
_ee_ready = False


def _ee():
    global _ee_ready
    try:
        import ee
    except ImportError as exc:
        raise SentinelUnavailable('earthengine-api is not installed') from exc
    with _ee_lock:
        if not _ee_ready:
            creds_file = os.getenv('GEE_CREDENTIALS_FILE') or os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
            if not creds_file or not os.path.exists(creds_file):
                raise SentinelUnavailable('GEE_CREDENTIALS_FILE is not set')
            from google.oauth2 import service_account
            project = os.getenv('GEE_PROJECT')
            if not project:
                with open(creds_file) as f:
                    project = json.load(f).get('project_id')
            cred = service_account.Credentials.from_service_account_file(
                creds_file, scopes=['https://www.googleapis.com/auth/earthengine.readonly'])
            ee.Initialize(cred, project=project)
            _ee_ready = True
    return ee


def today():
    return dt.datetime.now(dt.timezone.utc).date()


def window(to=None):
    """The Sentinel-2 window (NDVI / NDWI): the last 30 days up to today."""
    to = to or today()
    return to - dt.timedelta(days=S2_DAYS), to


def _latest_day(ee, collection, since):
    ms = ee.ImageCollection(collection).filterDate(since.isoformat(), (today() + dt.timedelta(days=1)).isoformat()) \
        .aggregate_max('system:time_start').getInfo()
    if ms is None:
        raise SentinelUnavailable(f'{collection} has no recent data')
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).date()


# Builders: each returns a single-band image 'v' for the layer's window.

def _s2(ee, geom, bands, frm, to):
    a, b = bands

    def prep(img):
        scl = img.select('SCL')
        land = scl.eq(4).Or(scl.eq(5)).Or(scl.eq(7))
        return img.normalizedDifference([a, b]).rename('v').updateMask(land)

    col = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
           .filterBounds(geom).filterDate(frm.isoformat(), (to + dt.timedelta(days=1)).isoformat()))
    # Clearest scene last, so it lies on top of the mosaic.
    return col.sort('CLOUDY_PIXEL_PERCENTAGE', False).map(prep).mosaic()


def _past(ee, coll, start, end, years, reduce):
    """reduce() of `coll` over [start, end] in each of the `years` previous years."""
    s, e = ee.Date(start), ee.Date(end)
    return ee.ImageCollection(ee.List.sequence(1, years).map(
        lambda k: reduce(coll.filterDate(s.advance(ee.Number(k).multiply(-1), 'year'),
                                         e.advance(ee.Number(k).multiply(-1), 'year')))))


def _rank_p(current, past, years):
    """Gringorten position of `current` among the years + 1 windows (ties take the mid rank)."""
    below = past.map(lambda h: h.lt(current)).sum()
    equal = past.map(lambda h: h.eq(current)).sum()
    return below.add(equal.multiply(0.5)).add(1 - 0.44).divide(years + 1 + 0.12)


def _zscore(ee, current, past):
    return current.subtract(past.mean()).divide(past.reduce(ee.Reducer.stdDev()))


def drought_components(ee, windows):
    """The three CDI inputs: SPI-3 rank position, soil-moisture z, vegetation z; and the water mask."""
    def span(key):
        a, b = windows[key]
        return a, (dt.date.fromisoformat(b) + dt.timedelta(days=1)).isoformat()

    era = ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR')
    a, b = span('drought')
    rain = era.select('total_precipitation_sum')
    spi_p = _rank_p(rain.filterDate(a, b).sum(), _past(ee, rain, a, b, SPI_YEARS, lambda c: c.sum()), SPI_YEARS)

    def root_zone(c):  # 0-28 cm: layer 1 (0-7 cm) and layer 2 (7-28 cm), thickness-weighted
        return c.map(lambda i: i.select('volumetric_soil_water_layer_1').multiply(7)
                     .add(i.select('volumetric_soil_water_layer_2').multiply(21)).divide(28)).mean()
    a, b = span('drought_soil')
    sm_z = _zscore(ee, root_zone(era.filterDate(a, b)), _past(ee, era, a, b, SPI_YEARS, root_zone))

    a, b = span('drought_veg')
    ndvi = ee.ImageCollection('MODIS/061/MOD13Q1').select('NDVI')
    years = dt.date.fromisoformat(windows['drought_veg'][1]).year - MODIS_FIRST_YEAR
    veg_z = _zscore(ee, ndvi.filterDate(a, b).mean(), _past(ee, ndvi, a, b, years, lambda c: c.mean()))

    water = ee.Image('JRC/GSW1_4/GlobalSurfaceWater').select('occurrence').unmask(0).gt(50)
    return spi_p, sm_z, veg_z, water


def _drought_class(ee, windows):
    spi_p, sm_z, veg_z, water = drought_components(ee, windows)
    watch = spi_p.lt(0.1587)                     # SPI-3 < -1
    return (ee.Image(0).where(watch, 1).where(watch.And(sm_z.lt(-1)), 2).where(watch.And(veg_z.lt(-1)), 3)
            .updateMask(water.Not()).rename('v'))


def _build(ee, layer, windows):
    geom = ee.Geometry(basin_outline())
    if layer == 'drought':
        return _drought_class(ee, windows)
    frm, to = (dt.date.fromisoformat(d) for d in windows[layer])
    end = (to + dt.timedelta(days=1)).isoformat()
    if layer == 'ndvi':
        return _s2(ee, geom, ('B8', 'B4'), frm, to)
    if layer == 'ndwi':
        return _s2(ee, geom, ('B8', 'B11'), frm, to)
    era = ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR')
    # A composite (mean/sum) forgets the 0.1° grid; pin it back on before
    # bilinear resampling, or Earth Engine would interpolate on a 1° grid.
    grid = era.first().select('temperature_2m').projection()

    def smooth(img):
        return img.setDefaultProjection(grid).resample('bilinear')

    if layer == 'temp':
        t = smooth(era.filterDate(frm.isoformat(), end).select('temperature_2m').mean().subtract(273.15))
        dem = ee.Image('CGIAR/SRTM90_V4').select('elevation')
        cell_z = dem.reduceResolution(ee.Reducer.mean(), maxPixels=65535).reproject(grid)
        # Terrain height above / below the cell's mean, times the lapse rate.
        return t.add(dem.subtract(smooth(cell_z)).multiply(LAPSE_C_PER_M)).rename('v')
    if layer == 'rain':
        # daily total in metres -> mm, summed over the window
        return smooth(era.filterDate(frm.isoformat(), end).select('total_precipitation_sum')
                      .sum().multiply(1000)).rename('v')
    if layer == 'spi':
        rain = era.select('total_precipitation_sum')
        a, b = frm.isoformat(), end
        # Gringorten position among the n+1 windows; inverse normal in _finish().
        return smooth(_rank_p(rain.filterDate(a, b).sum(), _past(ee, rain, a, b, SPI_YEARS, lambda c: c.sum()),
                              SPI_YEARS)).rename('v')
    raise ValueError(layer)


def _finish(layer, vals):
    """Float values -> the layer's units; NaN where there is no value."""
    vals = np.where(vals > NO_VALUE / 2, vals, np.nan)
    if layer in ('ndvi', 'ndwi'):
        vals = np.where((vals >= -1) & (vals <= 1), vals, np.nan)
    elif layer == 'spi':
        from scipy.special import ndtri
        vals = ndtri(np.clip(vals, 1e-4, 1 - 1e-4))
    elif layer == 'drought':
        vals = np.where((vals >= 0) & (vals <= 3), np.round(vals), np.nan)
    return vals.astype('float32')


# ── Daily metadata: each layer's window and the stretched scales ────────

def _day_key(day):
    return f'{day.isoformat()}_v{META_VERSION}'


def _day_dir(day):
    return os.path.join(CACHE_DIR, _day_key(day))


def _drop_old_days(day):
    """Each day's tiles get their own folder; earlier days are deleted."""
    if not os.path.isdir(CACHE_DIR):
        return
    for name in os.listdir(CACHE_DIR):
        if name != _day_key(day):
            shutil.rmtree(os.path.join(CACHE_DIR, name), ignore_errors=True)


def day_meta(day=None):
    """Windows and scales for today, worked out once a day and kept on disk."""
    day = day or today()
    path = os.path.join(_day_dir(day), 'meta.json')

    def cached():
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                meta = json.load(f)
            if meta.get('version') == META_VERSION:
                return meta
        return None

    meta = cached()
    if meta:
        return meta
    with _meta_lock:
        meta = cached()
        if meta:
            return meta
        ee = _ee()
        try:
            since = day - dt.timedelta(days=120)
            era = _latest_day(ee, 'ECMWF/ERA5_LAND/DAILY_AGGR', since)
            modis = _latest_day(ee, 'MODIS/061/MOD13Q1', since)   # start of the newest 16-day composite
            s2_from, s2_to = window(day)
            windows = {
                'ndvi': (s2_from, s2_to), 'ndwi': (s2_from, s2_to),
                'temp': (era - dt.timedelta(days=CLIMATE_DAYS - 1), era),
                'rain': (era - dt.timedelta(days=CLIMATE_DAYS - 1), era),
                'spi': (era - dt.timedelta(days=SPI_DAYS - 1), era),
                'drought': (era - dt.timedelta(days=SPI_DAYS - 1), era),
                'drought_soil': (era - dt.timedelta(days=CLIMATE_DAYS - 1), era),
                'drought_veg': (modis - dt.timedelta(days=16), modis),   # the two newest composites
            }
            windows = {k: [a.isoformat(), b.isoformat()] for k, (a, b) in windows.items()}
            geom = ee.Geometry(basin_outline())
            domains = {}
            for layer in ('temp', 'rain'):
                p = _build(ee, layer, windows).reduceRegion(
                    ee.Reducer.percentile([2, 98]), geom, 2000, maxPixels=1e9).getInfo()
                lo, hi = p['v_p2'], p['v_p98']
                if layer == 'rain':
                    lo = 0.0
                if hi - lo < 1:  # a near-uniform field still gets a readable scale
                    lo, hi = lo - 0.5, hi + 0.5
                domains[layer] = [round(lo, 1), round(hi, 1)]
            areas = ee.Image.pixelArea().divide(1e6).addBands(_build(ee, 'drought', windows)).reduceRegion(
                ee.Reducer.sum().group(groupField=1, groupName='c'), geom, 250, maxPixels=1e10).getInfo()
            drought_km2 = {name: 0.0 for name in DROUGHT_CLASSES}
            for g in areas['groups']:
                drought_km2[DROUGHT_CLASSES[int(g['c'])]] = round(g['sum'], 1)
        except SentinelUnavailable:
            raise
        except Exception as exc:
            raise SentinelUnavailable(f'Earth Engine: {str(exc)[:200]}') from exc
        meta = {'version': META_VERSION, 'windows': windows, 'domains': domains, 'drought_km2': drought_km2}
        _drop_old_days(day)
        os.makedirs(_day_dir(day), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(meta, f)
        return meta


def layer_domain(layer, meta=None):
    d = LAYERS[layer]['domain']
    return tuple(d) if d is not None else tuple((meta or day_meta())['domains'][layer])


# ── Tiles ───────────────────────────────────────────────────────────────

def _tile_path(layer, day, z, x, y):
    return os.path.join(_day_dir(day), layer, str(z), str(x), f'{y}.npy')


def tile_values(index, z, x, y, to=None):
    """Float32 256x256 array of the layer (NaN = no value) for one tile."""
    day = to or today()
    path = _tile_path(index, day, z, x, y)
    if os.path.exists(path):
        return np.load(path)
    meta = day_meta(day)
    ee = _ee()
    size = 2 * _R / 2 ** z
    image = _build(ee, index, meta['windows']).clip(ee.Geometry(basin_outline()))
    req = {
        # Masked pixels (cloud, water, outside the basin) are filled with
        # NO_VALUE: computePixels would otherwise return them as 0.
        'expression': image.unmask(NO_VALUE, False),
        'fileFormat': 'NPY',
        'grid': {
            'dimensions': {'width': TILE, 'height': TILE},
            'affineTransform': {'scaleX': size / TILE, 'shearX': 0, 'translateX': -_R + x * size,
                                'shearY': 0, 'scaleY': -size / TILE, 'translateY': _R - y * size},
            'crsCode': 'EPSG:3857',
        },
    }
    try:
        data = ee.data.computePixels(req)
    except Exception as exc:  # EE errors are plain exceptions with useful text
        raise SentinelUnavailable(f'Earth Engine: {str(exc)[:200]}') from exc
    arr = data if isinstance(data, np.ndarray) else np.load(io.BytesIO(data), allow_pickle=False)
    vals = _finish(index, np.asarray(arr['v'] if arr.dtype.names else arr, dtype='float32'))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f'{path}.{threading.get_ident()}.tmp'
    with open(tmp, 'wb') as f:
        np.save(f, vals)
    os.replace(tmp, path)
    return vals


@lru_cache(maxsize=8)
def _lut(index):
    stops = np.array([[int(h[i:i + 2], 16) for i in (1, 3, 5)] for h in LAYERS[index]['ramp']], dtype=float)
    t = np.linspace(0, 1, 256) * (len(stops) - 1)
    i = np.minimum(len(stops) - 2, np.floor(t).astype(int))
    f = (t - i)[:, None]
    return np.round(stops[i] + (stops[i + 1] - stops[i]) * f).astype('uint8')


def tile_png(index, z, x, y):
    from PIL import Image
    vals = tile_values(index, z, x, y)
    lo, hi = layer_domain(index)
    ok = np.isfinite(vals)
    k = np.clip(np.nan_to_num((vals - lo) / (hi - lo)), 0, 1)
    rgba = np.zeros((TILE, TILE, 4), dtype='uint8')
    rgba[..., :3] = _lut(index)[np.round(k * 255).astype(int)]
    rgba[..., 3] = np.where(ok, 255, 0)
    buf = io.BytesIO()
    Image.fromarray(rgba, 'RGBA').save(buf, 'PNG', optimize=True)
    return buf.getvalue()


def value_at(index, lat, lon, z):
    """The layer's value at a point, read from that zoom's tile (computed if needed)."""
    z = max(MIN_ZOOM, min(LAYERS[index]['max_zoom'], int(z)))
    tx, ty = lonlat_to_tile(lon, lat, z)
    x, y = int(tx), int(ty)
    if not tile_in_basin(z, x, y, index):
        return None
    vals = tile_values(index, z, x, y)
    v = vals[min(TILE - 1, int((ty - y) * TILE)), min(TILE - 1, int((tx - x) * TILE))]
    return None if not np.isfinite(v) else round(float(v), 3)


@lru_cache(maxsize=256)
def _drought_detail(day, lat, lon):
    ee = _ee()
    meta = day_meta(day)
    spi_p, sm_z, veg_z, water = drought_components(ee, meta['windows'])
    try:
        v = ee.Image.cat([spi_p.rename('spi_p'), sm_z.rename('soil'), veg_z.rename('veg'), water.rename('water')]) \
            .reduceRegion(ee.Reducer.first(), ee.Geometry.Point(lon, lat), 250).getInfo()
    except Exception as exc:
        raise SentinelUnavailable(f'Earth Engine: {str(exc)[:200]}') from exc
    if v.get('spi_p') is None:
        return None
    from scipy.special import ndtri
    return {'spi': round(float(ndtri(min(max(v['spi_p'], 1e-4), 1 - 1e-4))), 2),
            'soil': None if v.get('soil') is None else round(v['soil'], 2),
            'vegetation': None if v.get('veg') is None else round(v['veg'], 2),
            'water': bool(v.get('water'))}


def basin_anomalies(day=None):
    """Basin-mean root-zone soil water and vegetation anomalies (z) of the
    drought layer's windows, worked out once a day and kept with the tiles."""
    day = day or today()
    path = os.path.join(_day_dir(day), 'anomalies.json')
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    meta = day_meta(day)
    ee = _ee()
    _, sm_z, veg_z, water = drought_components(ee, meta['windows'])
    try:
        v = ee.Image.cat([sm_z.rename('soil'), veg_z.rename('veg')]).updateMask(water.Not()).reduceRegion(
            ee.Reducer.mean(), ee.Geometry(basin_outline()), 1000, maxPixels=1e9).getInfo()
    except Exception as exc:
        raise SentinelUnavailable(f'Earth Engine: {str(exc)[:200]}') from exc
    out = {'soil_z': None if v.get('soil') is None else round(v['soil'], 2),
           'veg_z': None if v.get('veg') is None else round(v['veg'], 2),
           'soil_window': meta['windows']['drought_soil'], 'veg_window': meta['windows']['drought_veg']}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(out, f)
    return out


def drought_detail(lat, lon):
    """Why a point has its drought level: SPI-3 and the soil / vegetation anomalies (z)."""
    return _drought_detail(today(), round(lat, 3), round(lon, 3))


def legend():
    """Ramps, scales, units and data windows for the page. The Earth Engine
    parts (windows, stretched scales) are left out if it cannot be reached."""
    try:
        meta = day_meta()
    except SentinelUnavailable as exc:
        logger.warning('Map layer metadata unavailable: %s', exc)
        meta = None
    layers = {}
    for k, v in LAYERS.items():
        entry = {'ramp': v['ramp'], 'ends': list(v['ends']), 'unit': v['unit'], 'decimals': v['decimals'],
                 'max_zoom': v['max_zoom'], 'source': v['source']}
        if v['domain'] is not None:
            entry['domain'] = list(v['domain'])
        elif meta:
            entry['domain'] = meta['domains'][k]
        if meta:
            entry['window'] = {'from': meta['windows'][k][0], 'to': meta['windows'][k][1]}
        layers[k] = entry
    if meta:
        layers['drought']['areas_km2'] = meta.get('drought_km2')
        layers['drought']['vegetation_window'] = dict(zip(('from', 'to'), meta['windows']['drought_veg']))
    frm, to = window()
    return layers | {'window': {'from': frm.isoformat(), 'to': to.isoformat(), 'days': S2_DAYS},
                     'bounds': [round(b, 5) for b in basin_bounds()],
                     'source': 'Google Earth Engine'}
