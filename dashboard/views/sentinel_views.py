"""Analysis-map layer tiles: NDVI, NDWI, temperature, rainfall, SPI-3 (see services/sentinel_tiles)."""
import logging

from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_GET

from ..services import sentinel_tiles as s2

logger = logging.getLogger(__name__)


@require_GET
def s2_tile(request, index, z, x, y):
    """One coloured 256 px tile. Only tiles over the catchment are served, so
    the route cannot spend the Earth Engine quota elsewhere."""
    if index not in s2.LAYERS:
        return HttpResponse('unknown index', status=400)
    if not s2.tile_in_basin(z, x, y, index):
        return HttpResponse('out of range', status=404)
    try:
        png = s2.tile_png(index, z, x, y)
    except s2.SentinelUnavailable as exc:
        logger.warning('S2 tile %s/%s/%s/%s: %s', index, z, x, y, exc)
        return HttpResponse(str(exc), status=503, content_type='text/plain')
    resp = HttpResponse(png, content_type='image/png')
    # One mosaic per day; Sentinel-2 revisits every ~5 days.
    resp['Cache-Control'] = 'private, max-age=21600'
    return resp


@require_GET
def s2_value_api(request, index):
    """The index at a clicked point, read from the tile at the map's zoom."""
    if index not in s2.LAYERS:
        return JsonResponse({'error': 'unknown index'}, status=400)
    try:
        lat, lon = float(request.GET['lat']), float(request.GET['lon'])
        z = int(float(request.GET.get('z', 13)))
    except (KeyError, ValueError):
        return JsonResponse({'error': 'lat, lon and z are required'}, status=400)
    try:
        value = s2.value_at(index, lat, lon, z)
        # For the drought level, the three signals behind it at that point.
        detail = s2.drought_detail(lat, lon) if index == 'drought' and value is not None else None
    except s2.SentinelUnavailable as exc:
        return JsonResponse({'error': str(exc)}, status=503)
    return JsonResponse({'index': index, 'value': value, 'detail': detail})


@require_GET
def s2_legend_api(request):
    return JsonResponse(s2.legend())
