import datetime
import json
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.utils import timezone

from ..models import Region, Sensor, SoilProbeReading
from ..services import smartfarm
from zoneinfo import ZoneInfo
from .utils import _haversine_distance


def sensor_network_view(request):
    """Render the dedicated Sensor Network dashboard page."""

    sensors_qs = Sensor.objects.filter(is_active=True).select_related("region").order_by("id")
    
    type_meta = {
        'aws': {
            'label': 'Weather Station (AWS)',
            'short': 'AWS',
            'icon': 'air',
            'color': '#00677d',
            'bg': 'bg-cyan-500/10 text-cyan-600 dark:text-cyan-400 border-cyan-500/20',
            'badge_bg': '#00677d',
            'metrics_measured': 'Temp, Rain, Humidity, Wind, Solar'
        },
        'soil': {
            'label': 'Soil Moisture Probe',
            'short': 'Soil Probe',
            'icon': 'eco',
            'color': '#16a34a',
            'bg': 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20',
            'badge_bg': '#16a34a',
            'metrics_measured': 'Moisture (10/30/60cm), Soil Temp, Salinity, pH'
        },
        'water': {
            'label': 'Hydrology / Water Gauge',
            'short': 'Water Gauge',
            'icon': 'water_drop',
            'color': '#2563eb',
            'bg': 'bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/20',
            'badge_bg': '#2563eb',
            'metrics_measured': 'Water Level (m), Discharge, Salinity, Volume'
        },
        'custom': {
            'label': 'Ground Truth Tower',
            'short': 'Ground Tower',
            'icon': 'radar',
            'color': '#d97706',
            'bg': 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20',
            'badge_bg': '#d97706',
            'metrics_measured': 'Satellite Flux, NDVI ground truth, Heat'
        },
    }

    sensor_list = []
    online_count = 0
    aws_count = 0
    soil_count = 0
    water_count = 0
    custom_count = 0

    for s in sensors_qs:
        stype = s.sensor_type if s.sensor_type in type_meta else 'custom'
        meta = type_meta[stype]
        
        if stype == 'aws':
            aws_count += 1
        elif stype == 'soil':
            soil_count += 1
        elif stype == 'water':
            water_count += 1
        else:
            custom_count += 1

        is_real = s.external_source == smartfarm.SOURCE
        last = s.soil_readings.order_by('-measured_at').values_list('measured_at', flat=True).first()
        online = bool(last and timezone.now() - last < datetime.timedelta(hours=48))
        online_count += online
        if is_real:
            meta = dict(meta, short='S.Sensor', label='SmartFarm Soil Probe (live)',
                        metrics_measured='Moisture at {} cm, Soil Temp'.format(
                            '/'.join(str(d) for d in (s.external_meta or {}).get('depths', [20, 40, 60]))))
        
        sensor_list.append({
            'id': s.id,
            'name': s.name,
            'sensor_type': stype,
            'type_label': meta['label'],
            'type_short': meta['short'],
            'type_icon': meta['icon'],
            'type_color': meta['color'],
            'type_bg': meta['bg'],
            'type_badge_bg': meta['badge_bg'],
            'metrics_measured': meta['metrics_measured'],
            'latitude': float(s.latitude),
            'longitude': float(s.longitude),
            'coverage_radius_km': float(s.coverage_radius_km),
            'region_id': s.region_id,
            'region_name': s.region.name if s.region else 'Northern Basin',
            'description': s.description or '',
            'installed_at': s.installed_at.strftime('%Y-%m-%d') if s.installed_at else '',
            'status_online': online,
            'last_reading': timezone.localtime(last).strftime('%Y-%m-%d %H:%M') if last else None,
            'is_real': is_real,
        })

    total_count = len(sensor_list)

    stats = {
        'total_sensors': total_count,
        'aws_count': aws_count,
        'soil_count': soil_count,
        'water_count': water_count,
        'custom_count': custom_count,
        'online_count': online_count,
        'readings_total': SoilProbeReading.objects.filter(sensor__is_active=True).count(),
    }

    context = {
        'sensors': sensor_list,
        'sensors_json': json.dumps(sensor_list),
        'stats': stats,
        'smartfarm_configured': smartfarm.configured(),
        'active_page': 'sensors',
    }
    return render(request, 'dashboard/sensors.html', context)


@require_http_methods(["GET"])
def sensor_telemetry_api(request, pk=None):
    """Graph data for a sensor: its stored real readings, one point per day.
    Without a sensor id, the first real probe. Sensors with no data source
    return `no_data` rather than invented values."""
    time_range = request.GET.get('range', '7d')
    if pk:
        sensor = Sensor.objects.filter(pk=pk, is_active=True).first()
        if sensor is None:
            return JsonResponse({"error": "Sensor not found"}, status=404)
    else:
        sensor = (Sensor.objects.filter(is_active=True, external_source=smartfarm.SOURCE)
                  .order_by('id').first())
    if sensor is not None and sensor.external_source == smartfarm.SOURCE:
        return JsonResponse(_smartfarm_telemetry(sensor, time_range))
    return JsonResponse({
        "sensor_id": sensor.id if sensor else None,
        "sensor_name": sensor.name if sensor else None,
        "sensor_type": sensor.sensor_type if sensor else None,
        "time_range": time_range,
        "no_data": True,
        "timestamps": [],
        "series": {},
        "charts": [],
    })


@require_http_methods(["POST"])
def sensor_ingest_api(request):
    """Register a new sensor pin."""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    lat = data.get("latitude")
    lng = data.get("longitude")
    name = data.get("name", "").strip()
    sensor_type = data.get("sensor_type", "custom")
    radius = data.get("coverage_radius_km", 10)
    description = data.get("description", "")
    if not name:
        return JsonResponse({"error": "name is required"}, status=400)
    if lat is None or lng is None:
        return JsonResponse({"error": "latitude and longitude are required"}, status=400)
    
    # assign nearest region
    regions = Region.objects.exclude(latitude__isnull=True, longitude__isnull=True)
    nearest = None
    nearest_dist = float('inf')
    for region in regions:
        dist = _haversine_distance(lat, lng, float(region.latitude), float(region.longitude))
        if dist < nearest_dist:
            nearest_dist = dist
            nearest = region
    
    sensor = Sensor.objects.create(
        name=name,
        sensor_type=sensor_type,
        latitude=lat,
        longitude=lng,
        coverage_radius_km=radius,
        region=nearest,
        description=description,
        created_by=request.user if request.user.is_authenticated else None,
    )
    return JsonResponse({
        "id": sensor.id,
        "name": sensor.name,
        "sensor_type": sensor.sensor_type,
        "latitude": float(sensor.latitude),
        "longitude": float(sensor.longitude),
        "coverage_radius_km": float(sensor.coverage_radius_km),
        "region_id": sensor.region_id,
        "region_name": sensor.region.name if sensor.region else None,
    }, status=201)


@require_http_methods(["GET"])
def sensor_list_api(request):
    """Return all active sensors."""
    sensors = Sensor.objects.filter(is_active=True).select_related("region")
    data = []
    for s in sensors:
        data.append({
            "id": s.id,
            "name": s.name,
            "sensor_type": s.sensor_type,
            "latitude": float(s.latitude),
            "longitude": float(s.longitude),
            "coverage_radius_km": float(s.coverage_radius_km),
            "region_id": s.region_id,
            "region_name": s.region.name if s.region else None,
            "installed_at": s.installed_at.isoformat(),
        })
    return JsonResponse({"sensors": data})


@require_http_methods(["GET"])
def sensor_history_api(request, pk):
    """Return sensor details by ID."""
    try:
        s = Sensor.objects.get(pk=pk, is_active=True)
    except Sensor.DoesNotExist:
        return JsonResponse({"error": "Sensor not found"}, status=404)
    return JsonResponse({
        "id": s.id,
        "name": s.name,
        "sensor_type": s.sensor_type,
        "latitude": float(s.latitude),
        "longitude": float(s.longitude),
        "coverage_radius_km": float(s.coverage_radius_km),
        "region_id": s.region_id,
        "region_name": s.region.name if s.region else None,
        "installed_at": s.installed_at.isoformat(),
        "description": s.description or "",
    })


@require_http_methods(["PUT"])
def sensor_edit_api(request, pk):
    """Update an existing sensor."""
    try:
        s = Sensor.objects.get(pk=pk)
    except Sensor.DoesNotExist:
        return JsonResponse({"error": "Sensor not found"}, status=404)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    if "name" in data:
        name = data["name"].strip()
        if name:
            s.name = name
    if "sensor_type" in data:
        s.sensor_type = data["sensor_type"]
    if "latitude" in data and data["latitude"] is not None:
        s.latitude = data["latitude"]
    if "longitude" in data and data["longitude"] is not None:
        s.longitude = data["longitude"]
    if "coverage_radius_km" in data:
        s.coverage_radius_km = data["coverage_radius_km"]
    if "description" in data:
        s.description = data["description"]
    s.save()
    return JsonResponse({
        "id": s.id,
        "name": s.name,
        "sensor_type": s.sensor_type,
        "latitude": float(s.latitude),
        "longitude": float(s.longitude),
        "coverage_radius_km": float(s.coverage_radius_km),
        "description": s.description or "",
    })


@require_http_methods(["DELETE"])
def sensor_delete_api(request, pk):
    """Soft-delete a sensor (set is_active=False)."""
    try:
        s = Sensor.objects.get(pk=pk)
    except Sensor.DoesNotExist:
        return JsonResponse({"error": "Sensor not found"}, status=404)
    s.is_active = False
    s.save()
    return JsonResponse({"success": True})


# ---------------------------------------------------------------------------
# SmartFarm soil probe (real hardware)
# ---------------------------------------------------------------------------

# The probe reports once a day, so even the "24h" button shows a week of days.
_RANGE_DAYS = {'24h': 7, '7d': 7, '30d': 30}
_PROBE_TZ = ZoneInfo('Africa/Tunis')


def _probe_rows(sensor, days, min_points=8):
    """Readings in the window, in soil only. The probe reports about once a day,
    so a short window is widened to the last `min_points` readings."""
    qs = SoilProbeReading.objects.filter(sensor=sensor, moisture_1__isnull=False,
                                         moisture_2__isnull=False, moisture_3__isnull=False)
    rows = list(qs.filter(measured_at__gte=timezone.now() - datetime.timedelta(days=days)))
    if len(rows) < min_points:
        rows = list(qs.order_by('-measured_at')[:min_points])[::-1]
    return rows


def _probe_daily(sensor, days):
    """One entry per calendar day (Tunis time) from the first reading in the
    window to today. Several readings on a day are averaged; a day without any
    has None values, so charts show the gap instead of joining across it."""
    today = timezone.localtime(timezone.now(), _PROBE_TZ).date()
    start = today - datetime.timedelta(days=days - 1)
    rows = SoilProbeReading.objects.filter(
        sensor=sensor, moisture_1__isnull=False, moisture_2__isnull=False, moisture_3__isnull=False,
        measured_at__gte=datetime.datetime.combine(start, datetime.time.min, tzinfo=_PROBE_TZ))
    by_day = {}
    for r in rows:
        by_day.setdefault(timezone.localtime(r.measured_at, _PROBE_TZ).date(), []).append(r)
    if not by_day:
        return []

    def mean(vals):
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    out, day = [], min(by_day)
    while day <= today:
        rs = by_day.get(day, [])
        out.append({
            "date": day.isoformat(),
            "m": [mean(getattr(r, f) for r in rs) for f in ('moisture_1', 'moisture_2', 'moisture_3')],
            "soil_temp": mean(r.soil_temp_c for r in rs),
            "n": len(rs),
        })
        day += datetime.timedelta(days=1)
    return out


def _probe_depths(sensor):
    d = (sensor.external_meta or {}).get('depths') or [20, 40, 60]
    return [int(x) for x in d[:3]]


def _smartfarm_telemetry(sensor, time_range):
    days = _probe_daily(sensor, _RANGE_DAYS.get(time_range, 7))
    d1, d2, d3 = _probe_depths(sensor)
    return {
        "sensor_id": sensor.id,
        "sensor_name": sensor.name,
        "sensor_type": "smartfarm",
        "sensor_label": "SmartFarm Soil Probe (live)",
        "metrics_measured": [f"Moisture {d1} cm (%)", f"Moisture {d2} cm (%)",
                             f"Moisture {d3} cm (%)", "Soil Temp (°C)"],
        "depths": [d1, d2, d3],
        "time_range": time_range,
        "real": True,
        "timestamps": [datetime.date.fromisoformat(d["date"]).strftime('%b %d') for d in days],
        "series": {
            "probe_moisture_1": [d["m"][0] for d in days],
            "probe_moisture_2": [d["m"][1] for d in days],
            "probe_moisture_3": [d["m"][2] for d in days],
            "soil_temperature": [d["soil_temp"] for d in days],
        },
        "charts": [],
    }


def _moisture_level(pct):
    if pct is None:
        return None
    if pct < 30:
        return 'dry'
    if pct < 60:
        return 'good'
    return 'wet'


@require_http_methods(["GET", "POST"])
def smartfarm_probe_api(request):
    """Latest state of the SmartFarm probe. GET syncs first when the last pull is
    over an hour old; POST forces a pull now (rate-limited inside the service)."""
    if not smartfarm.configured():
        return JsonResponse({"configured": False})

    if request.method == "POST":
        error = smartfarm.sync_if_stale(max_age_minutes=0)
    else:
        error = smartfarm.sync_if_stale(max_age_minutes=60)

    sensor = Sensor.objects.filter(external_source=smartfarm.SOURCE).order_by('-last_synced_at').first()
    if sensor is None:
        return JsonResponse({"configured": True, "error": error or "No data yet", "sensor": None})

    rows = _probe_rows(sensor, 120, min_points=1)
    latest = rows[-1] if rows else None
    depths = _probe_depths(sensor)
    total = SoilProbeReading.objects.filter(sensor=sensor).count()

    def pack(r):
        return {
            "time": r.measured_at.isoformat(),
            "m": [r.moisture_1, r.moisture_2, r.moisture_3],
            "soil_temp": r.soil_temp_c,
        }

    root = latest.root_zone if latest else None
    return JsonResponse({
        "configured": True,
        "error": error,
        "sensor": {
            "id": sensor.id,
            "name": sensor.name,
            "field": (sensor.external_meta or {}).get('field'),
            "status": (sensor.external_meta or {}).get('status'),
            "code": sensor.external_id,
            "last_synced_at": sensor.last_synced_at.isoformat() if sensor.last_synced_at else None,
        },
        "depths": depths,
        "latest": pack(latest) if latest else None,
        "levels": [_moisture_level(v) for v in (pack(latest)["m"] if latest else [None] * 3)],
        "root_zone": round(root, 1) if root is not None else None,
        "root_level": _moisture_level(root),
        "readings_total": total,
        "readings": [pack(r) for r in rows],
        "daily": _probe_daily(sensor, 365),
    })
