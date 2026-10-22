import json
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from ..models import Region, Sensor
from .utils import _haversine_distance


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
    """Return sensor details by ID (placeholder for future timeseries)."""
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
