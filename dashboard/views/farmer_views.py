"""Farmer role: the farmer's own parcels, advice, weather and assistant.

Every query is scoped to request.user, so a farmer can never read or modify
another farmer's farm (unknown and foreign ids both answer 404).
"""
import datetime as dt
import json
from decimal import Decimal, InvalidOperation

from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from ..models import Farm
from ..services import farmer_service as fs
from ..services.crop_kb import CROP_KB
from ..services.crop_suitability import CROPS
from .utils import _is_admin_user


def _is_farmer(user):
    profile = getattr(user, 'profile', None)
    return bool(profile and profile.role == 'farmer')


def _can_use_farmer_space(user):
    # Superadmins may open it too, to support farmers and to test.
    return user.is_authenticated and (_is_farmer(user) or _is_admin_user(user))


def _forbidden():
    return JsonResponse({'error': 'Farmer account required.'}, status=403)


def _get_farm(request, farm_id):
    return Farm.objects.select_related('region').filter(owner=request.user, pk=farm_id).first()


def _apply_fields(farm, data):
    """Copy the editable fields from a JSON payload; returns an error or None."""
    if 'name' in data:
        name = (data.get('name') or '').strip()
        if not name:
            return 'The farm needs a name.'
        farm.name = name[:100]
    if 'crop' in data:
        crop = data.get('crop') or ''
        if crop and crop not in CROPS:
            return 'Unknown crop.'
        farm.crop = crop
    if 'sowing_date' in data:
        value = data.get('sowing_date')
        try:
            farm.sowing_date = dt.date.fromisoformat(value) if value else None
        except (TypeError, ValueError):
            return 'Sowing date must be YYYY-MM-DD.'
    if 'irrigated' in data:
        farm.irrigated = bool(data.get('irrigated'))
    if 'water_supply_mm' in data:
        value = data.get('water_supply_mm')
        try:
            farm.water_supply_mm = Decimal(str(value)) if value not in (None, '') else None
        except InvalidOperation:
            return 'Water supply must be a number (mm).'
        if farm.water_supply_mm is not None and not 0 <= farm.water_supply_mm <= 5000:
            return 'Water supply must be between 0 and 5000 mm.'
    if 'boundary' in data:
        try:
            fs.apply_boundary(farm, data.get('boundary'))
        except fs.FarmGeometryError as exc:
            return str(exc)
    return None


def _json_body(request):
    try:
        data = json.loads(request.body or b'{}')
    except (ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


# ------------------------------------------------------------------ #
# Page
# ------------------------------------------------------------------ #

def farmer_home(request):
    if not _can_use_farmer_space(request.user):
        return redirect('dashboard:dashboard')
    crops = [{'key': k, 'name': v['names']['en'], 'names': v['names'], 'perennial': v['perennial'],
              'planting_months': v['planting_months']} for k, v in CROPS.items()]
    return render(request, 'dashboard/farmer_home.html', {
        'crops_json': json.dumps(crops),
        'assistant_crops_json': json.dumps(sorted(CROP_KB)),
    })


# ------------------------------------------------------------------ #
# API
# ------------------------------------------------------------------ #

@require_http_methods(['GET', 'POST'])
def farms_api(request):
    """GET: the farmer's farms.  POST: create one
    {name, boundary (GeoJSON Polygon), crop?, sowing_date?, irrigated?, water_supply_mm?}."""
    if not _can_use_farmer_space(request.user):
        return _forbidden()
    if request.method == 'GET':
        farms = Farm.objects.select_related('region').filter(owner=request.user)
        return JsonResponse({'farms': [fs.serialize_farm(f) for f in farms]})

    data = _json_body(request)
    if data is None:
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)
    if not data.get('boundary'):
        return JsonResponse({'error': 'Draw the farm boundary on the map first.'}, status=400)
    if Farm.objects.filter(owner=request.user).count() >= 50:
        return JsonResponse({'error': 'Farm limit reached (50).'}, status=400)
    farm = Farm(owner=request.user, name='')
    data.setdefault('name', '')
    error = _apply_fields(farm, data)
    if error:
        return JsonResponse({'error': error}, status=400)
    farm.save()
    fs.schedule_soil_lookup(farm.pk)
    return JsonResponse({'farm': fs.serialize_farm(farm)}, status=201)


@require_http_methods(['GET', 'PATCH', 'DELETE'])
def farm_detail_api(request, farm_id):
    if not _can_use_farmer_space(request.user):
        return _forbidden()
    farm = _get_farm(request, farm_id)
    if farm is None:
        return JsonResponse({'error': 'Farm not found.'}, status=404)
    if request.method == 'DELETE':
        farm.delete()
        return JsonResponse({'deleted': farm_id})
    if request.method == 'PATCH':
        data = _json_body(request)
        if data is None:
            return JsonResponse({'error': 'Invalid JSON.'}, status=400)
        error = _apply_fields(farm, data)
        if error:
            return JsonResponse({'error': error}, status=400)
        farm.save()
        if farm.soil is None:  # new boundary moved the parcel
            fs.schedule_soil_lookup(farm.pk)
    return JsonResponse({'farm': fs.serialize_farm(farm)})


@require_http_methods(['GET'])
def farm_advice_api(request, farm_id):
    """GET ?month=1-12 (default: current month)."""
    if not _can_use_farmer_space(request.user):
        return _forbidden()
    farm = _get_farm(request, farm_id)
    if farm is None:
        return JsonResponse({'error': 'Farm not found.'}, status=404)
    try:
        month = int(request.GET.get('month') or dt.date.today().month)
    except ValueError:
        month = 0
    if not 1 <= month <= 12:
        return JsonResponse({'error': 'month must be 1-12'}, status=400)
    advice = fs.farm_advice(farm, month)
    return JsonResponse(advice, status=404 if 'error' in advice else 200)


@require_http_methods(['GET'])
def farm_crop_plan_api(request, farm_id):
    """GET ?crop=<key>[&sowing_date=YYYY-MM-DD]: plan for any crop on this farm."""
    if not _can_use_farmer_space(request.user):
        return _forbidden()
    farm = _get_farm(request, farm_id)
    if farm is None:
        return JsonResponse({'error': 'Farm not found.'}, status=404)
    from ..services.crop_management import crop_plan
    crop = request.GET.get('crop') or farm.crop
    if crop not in CROPS:
        return JsonResponse({'error': 'Choose a crop.'}, status=400)
    sowing = None
    if request.GET.get('sowing_date'):
        try:
            sowing = dt.date.fromisoformat(request.GET['sowing_date'])
        except ValueError:
            return JsonResponse({'error': 'sowing_date must be YYYY-MM-DD'}, status=400)
    elif crop == farm.crop:
        sowing = farm.sowing_date
    return JsonResponse(crop_plan(crop, sowing))


@require_http_methods(['GET'])
def farm_weather_api(request, farm_id):
    if not _can_use_farmer_space(request.user):
        return _forbidden()
    farm = _get_farm(request, farm_id)
    if farm is None:
        return JsonResponse({'error': 'Farm not found.'}, status=404)
    return JsonResponse(fs.farm_weather(farm))
