"""Farmer role: the farmer's own parcels, advice, weather and assistant.

Every query is scoped to request.user, so a farmer can never read or modify
another farmer's farm (unknown and foreign ids both answer 404).
"""
import datetime as dt
import json
from decimal import Decimal, InvalidOperation

from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from ..models import Farm, FarmActivity
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
    return JsonResponse({'error': _('Farmer account required.')}, status=403)


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
    if 'irrigation_method' in data:
        method = data.get('irrigation_method') or ''
        if method and method not in dict(Farm.IRRIGATION_METHODS):
            return 'Unknown irrigation method.'
        farm.irrigation_method = method
    if 'irrigation_flow_m3h' in data:
        value = data.get('irrigation_flow_m3h')
        try:
            farm.irrigation_flow_m3h = Decimal(str(value)) if value not in (None, '') else None
        except InvalidOperation:
            return 'Flow rate must be a number (m³/h).'
        if farm.irrigation_flow_m3h is not None and not 0 < farm.irrigation_flow_m3h <= 10000:
            return 'Flow rate must be between 0 and 10 000 m³/h.'
    if 'last_irrigation_date' in data:
        value = data.get('last_irrigation_date')
        try:
            when = dt.date.fromisoformat(value) if value else None
        except (TypeError, ValueError):
            return 'Last irrigation date must be YYYY-MM-DD.'
        if when and when > dt.date.today():
            return 'Last irrigation date cannot be in the future.'
        farm.last_irrigation_date = when
    if 'boundary' in data:
        try:
            fs.apply_boundary(farm, data.get('boundary'))
        except fs.FarmGeometryError as exc:
            return str(exc)  # translated by the caller
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
# Installable app (PWA): manifest and offline service worker
# ------------------------------------------------------------------ #

APP_THEME = '#012d1d'
APP_BACKGROUND = '#f9f9ff'


def _app_assets():
    """Static files the app needs to open without a connection."""
    from django.templatetags.static import static
    return [static(p) for p in (
        'dashboard/vendor/leaflet/leaflet.css', 'dashboard/vendor/leaflet/leaflet.js',
        'dashboard/vendor/leaflet-draw/leaflet.draw.css', 'dashboard/vendor/leaflet-draw/leaflet.draw.js',
        'dashboard/css/rtl.css', 'dashboard/img/apwrs-logo.png',
        'dashboard/pwa/icon-192.png', 'dashboard/pwa/icon-512.png')]


def farmer_manifest(request):
    """Web app manifest: name, icons, colours and shortcuts, in the user's language."""
    from django.templatetags.static import static
    from django.utils.translation import get_language, get_language_bidi
    from django.utils.translation import gettext as _
    icon = lambda path, size, purpose: {'src': static(path), 'sizes': f'{size}x{size}',   # noqa: E731
                                        'type': 'image/png', 'purpose': purpose}
    data = {
        'id': '/farmer/',
        'name': _('APWRS Farmer'),
        'short_name': 'APWRS',
        'description': _('When to water, what to plant, pests, weather and an assistant for your farm.'),
        'lang': get_language() or 'en',
        'dir': 'rtl' if get_language_bidi() else 'ltr',
        'start_url': '/farmer/?source=app',
        'scope': '/farmer/',
        'display': 'standalone',
        'orientation': 'portrait',
        'theme_color': APP_THEME,
        'background_color': APP_BACKGROUND,
        'categories': ['productivity', 'weather', 'utilities'],
        'icons': [icon('dashboard/pwa/icon-192.png', 192, 'any'),
                  icon('dashboard/pwa/icon-512.png', 512, 'any'),
                  icon('dashboard/pwa/icon-maskable-512.png', 512, 'maskable')],
        'shortcuts': [
            {'name': _('Today'), 'url': '/farmer/?tab=overview&source=app',
             'icons': [icon('dashboard/pwa/icon-192.png', 192, 'any')]},
            {'name': _('Water'), 'url': '/farmer/?tab=irrigation&source=app',
             'icons': [icon('dashboard/pwa/icon-192.png', 192, 'any')]},
            {'name': _('AI Agronomist'), 'url': '/farmer/?tab=chat&source=app',
             'icons': [icon('dashboard/pwa/icon-192.png', 192, 'any')]},
        ],
    }
    response = JsonResponse(data, json_dumps_params={'ensure_ascii': False})
    response['Content-Type'] = 'application/manifest+json; charset=utf-8'
    return response


def farmer_service_worker(request):
    """Offline support for the farmer app, served under /farmer/ so it may
    control the farmer pages and their API (not the rest of the site)."""
    import hashlib
    from pathlib import Path
    from django.template.loader import render_to_string
    assets = _app_assets()
    source = Path(__file__).resolve().parents[2] / 'templates' / 'dashboard' / 'farmer_sw.js'
    try:
        stamp = source.read_bytes()
    except OSError:
        stamp = b''
    version = hashlib.md5(stamp + '|'.join(assets).encode()).hexdigest()[:10]
    body = render_to_string('dashboard/farmer_sw.js', {'version': version, 'assets': assets}, request=request)
    response = HttpResponse(body, content_type='application/javascript; charset=utf-8')
    response['Service-Worker-Allowed'] = '/farmer/'
    response['Cache-Control'] = 'no-cache'
    return response


# ------------------------------------------------------------------ #
# Mobile app login (token; see agri_dashboard.middleware.ApiTokenMiddleware)
# ------------------------------------------------------------------ #

def _me(user):
    profile = getattr(user, 'profile', None)
    return {'username': user.username, 'name': user.get_full_name() or user.username,
            'role': getattr(profile, 'role', None)}


@csrf_exempt     # the app has no cookie to forge; it sends credentials, gets a token
@require_http_methods(['POST'])
def mobile_login_api(request):
    """POST {username, password} -> {token, user}. Farmer accounts only."""
    from django.contrib.auth import authenticate
    from django.utils.translation import gettext as _
    from rest_framework.authtoken.models import Token
    data = _json_body(request) or {}
    user = authenticate(request, username=(data.get('username') or '').strip(),
                        password=data.get('password') or '')
    if user is None:
        return JsonResponse({'error': _('Wrong username or password.')}, status=401)
    if not _can_use_farmer_space(user):
        return JsonResponse({'error': _('Farmer account required.')}, status=403)
    token, _created = Token.objects.get_or_create(user=user)
    return JsonResponse({'token': token.key, 'user': _me(user)})


@csrf_exempt     # like login: no cookie to forge, and the account is new
@require_http_methods(['POST'])
def mobile_signup_api(request):
    """POST {username, email?, phone, password1, password2} -> 201 {token, user}.

    Same form and rules as the website's sign-up page (a farmer account,
    active at once); the app is signed in straight away. Refusals come back
    as 400 {error, errors: {field: message}} in the request's language.
    """
    from django.utils.translation import gettext as _
    from rest_framework.authtoken.models import Token
    from ..forms import FarmerSignupForm
    data = _json_body(request)
    if data is None:
        return JsonResponse({'error': _('Invalid JSON.')}, status=400)
    form = FarmerSignupForm({k: data.get(k) or '' for k in ('username', 'email', 'phone', 'password1', 'password2')})
    if not form.is_valid():
        errors = {field: [str(m) for m in msgs][0] for field, msgs in form.errors.items()}
        return JsonResponse({'error': next(iter(errors.values())), 'errors': errors}, status=400)
    # Reload: the form sets the role on its own copy of the profile, not the
    # one cached on this user when the account was created.
    user = type(form.save()).objects.select_related('profile').get(username=form.cleaned_data['username'])
    token, _created = Token.objects.get_or_create(user=user)
    return JsonResponse({'token': token.key, 'user': _me(user)}, status=201)


@require_http_methods(['POST'])
def mobile_logout_api(request):
    """Revoke the app's token (every phone signed in with it is logged out)."""
    from rest_framework.authtoken.models import Token
    if request.user.is_authenticated:
        Token.objects.filter(user=request.user).delete()
    return JsonResponse({'ok': True})


@require_http_methods(['GET'])
def mobile_me_api(request):
    if not _can_use_farmer_space(request.user):
        return _forbidden()
    return JsonResponse({'user': _me(request.user)})


@require_http_methods(['GET'])
def crops_api(request):
    """Crop list with names in the three languages (the web page embeds it)."""
    if not _can_use_farmer_space(request.user):
        return _forbidden()
    return JsonResponse({'crops': [
        {'key': k, 'names': v['names'], 'perennial': v['perennial'], 'planting_months': v['planting_months']}
        for k, v in CROPS.items()]})


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
        return JsonResponse({'error': _('Invalid JSON.')}, status=400)
    if not data.get('boundary'):
        return JsonResponse({'error': _('Draw the farm boundary on the map first.')}, status=400)
    if Farm.objects.filter(owner=request.user).count() >= 50:
        return JsonResponse({'error': _('Farm limit reached (50).')}, status=400)
    farm = Farm(owner=request.user, name='')
    data.setdefault('name', '')
    error = _apply_fields(farm, data)
    if error:
        return JsonResponse({'error': _(error)}, status=400)
    farm.save()
    fs.schedule_soil_lookup(farm.pk)
    return JsonResponse({'farm': fs.serialize_farm(farm)}, status=201)


@require_http_methods(['GET', 'PATCH', 'DELETE'])
def farm_detail_api(request, farm_id):
    if not _can_use_farmer_space(request.user):
        return _forbidden()
    farm = _get_farm(request, farm_id)
    if farm is None:
        return JsonResponse({'error': _('Farm not found.')}, status=404)
    if request.method == 'DELETE':
        farm.delete()
        return JsonResponse({'deleted': farm_id})
    if request.method == 'PATCH':
        data = _json_body(request)
        if data is None:
            return JsonResponse({'error': _('Invalid JSON.')}, status=400)
        error = _apply_fields(farm, data)
        if error:
            return JsonResponse({'error': _(error)}, status=400)
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
        return JsonResponse({'error': _('Farm not found.')}, status=404)
    try:
        month = int(request.GET.get('month') or dt.date.today().month)
    except ValueError:
        month = 0
    if not 1 <= month <= 12:
        return JsonResponse({'error': _('month must be 1-12')}, status=400)
    advice = fs.farm_advice(farm, month)
    return JsonResponse(advice, status=404 if 'error' in advice else 200)


@require_http_methods(['GET'])
def farm_crop_plan_api(request, farm_id):
    """GET ?crop=<key>[&sowing_date=YYYY-MM-DD]: plan for any crop on this farm."""
    if not _can_use_farmer_space(request.user):
        return _forbidden()
    farm = _get_farm(request, farm_id)
    if farm is None:
        return JsonResponse({'error': _('Farm not found.')}, status=404)
    from ..services.crop_management import crop_plan
    crop = request.GET.get('crop') or farm.crop
    if crop not in CROPS:
        return JsonResponse({'error': _('Choose a crop.')}, status=400)
    sowing = None
    if request.GET.get('sowing_date'):
        try:
            sowing = dt.date.fromisoformat(request.GET['sowing_date'])
        except ValueError:
            return JsonResponse({'error': _('sowing_date must be YYYY-MM-DD')}, status=400)
    elif crop == farm.crop:
        sowing = farm.sowing_date
    return JsonResponse(crop_plan(crop, sowing, area_ha=float(farm.area_ha)))


@require_http_methods(['GET'])
def farm_irrigation_api(request, farm_id):
    """When to irrigate and how much: FAO-56 daily soil-water balance from
    the parcel's soil, crop stage, method and observed + forecast weather."""
    if not _can_use_farmer_space(request.user):
        return _forbidden()
    farm = _get_farm(request, farm_id)
    if farm is None:
        return JsonResponse({'error': _('Farm not found.')}, status=404)
    from ..services.irrigation_schedule import farm_irrigation
    from ..services.task_text_msgids import TEXTS
    data = farm_irrigation(farm)
    # Tips also come written out in the user's language (for the mobile app).
    for event in data.get('events') or []:
        event['tips_text'] = [_(TEXTS['tip_' + t]) for t in event.get('tips') or [] if 'tip_' + t in TEXTS]
    if data.get('next'):
        data['next'] = (data.get('events') or [data['next']])[0]
    return JsonResponse(data)


@require_http_methods(['GET'])
def farm_tasks_api(request, farm_id):
    """Reminders (what to do, when, how much, why) and questions about what
    the farmer did, from live soil-water, forecast and crop-stage data."""
    if not _can_use_farmer_space(request.user):
        return _forbidden()
    farm = _get_farm(request, farm_id)
    if farm is None:
        return JsonResponse({'error': _('Farm not found.')}, status=404)
    from ..services.farm_tasks import farm_tasks
    return JsonResponse(farm_tasks(farm))


ACTIVITY_KINDS = dict(FarmActivity.KINDS)
ACTIVITY_STATUSES = dict(FarmActivity.STATUSES)
MAX_ACTIVITY_AGE_DAYS = 366


def _sync_last_irrigation(farm, removed_date=None):
    """Keep farm.last_irrigation_date (also settable directly, before the log
    existed) equal to the latest watering we know of."""
    last = farm.activities.filter(kind='irrigation', status='done').order_by('-date').first()
    known = farm.last_irrigation_date if farm.last_irrigation_date != removed_date else None
    candidates = [d for d in (known, last.date if last else None) if d]
    farm.last_irrigation_date = max(candidates) if candidates else None
    farm.save(update_fields=['last_irrigation_date', 'updated_at'])


def _parse_activity(data):
    """Validated FarmActivity fields from a JSON payload, or an error string."""
    kind = data.get('kind')
    if kind not in ACTIVITY_KINDS:
        return None, 'Unknown activity.'
    status = data.get('status') or 'done'
    if status not in ACTIVITY_STATUSES:
        return None, 'Status must be done or skipped.'
    today = dt.date.today()
    try:
        when = dt.date.fromisoformat(data.get('date') or today.isoformat())
    except (TypeError, ValueError):
        return None, 'Date must be YYYY-MM-DD.'
    if when > today:
        return None, 'The date cannot be in the future.'
    if when < today - dt.timedelta(days=MAX_ACTIVITY_AGE_DAYS):
        return None, 'The date is more than a year ago.'
    amount = data.get('amount_mm')
    if amount in (None, ''):
        amount = None
    else:
        try:
            amount = Decimal(str(amount))
        except InvalidOperation:
            return None, 'Amount must be a number (mm).'
        if kind != 'irrigation' or not 0 < amount <= 500:
            return None, 'Water amount must be between 0 and 500 mm.'
    return {
        'kind': kind, 'status': status, 'date': when, 'amount_mm': amount,
        'task_key': str(data.get('task_key') or '')[:80],
        'note': str(data.get('note') or '')[:200],
    }, None


@require_http_methods(['GET', 'POST'])
def farm_activities_api(request, farm_id):
    """GET: the farm's log. POST {kind, status?, date?, amount_mm?, task_key?, note?}:
    record what the farmer did (or did not do). The plan is recomputed from it."""
    if not _can_use_farmer_space(request.user):
        return _forbidden()
    farm = _get_farm(request, farm_id)
    if farm is None:
        return JsonResponse({'error': _('Farm not found.')}, status=404)
    from ..services.farm_tasks import serialize_activity
    if request.method == 'GET':
        return JsonResponse({'activities': [serialize_activity(a) for a in farm.activities.all()[:100]]})

    data = _json_body(request)
    if data is None:
        return JsonResponse({'error': _('Invalid JSON.')}, status=400)
    fields, error = _parse_activity(data)
    if error:
        return JsonResponse({'error': _(error)}, status=400)
    if farm.activities.count() >= 5000:
        return JsonResponse({'error': _('Activity log is full.')}, status=400)
    activity = FarmActivity.objects.create(farm=farm, **fields)
    _sync_farm(farm, None, activity)
    return JsonResponse({'activity': serialize_activity(activity), 'farm': fs.serialize_farm(farm)},
                        status=201)


def _sync_farm(farm, before, after):
    """Keep the farm's summary fields (last watering, sowing date) in line with
    a log entry that was added (before=None), corrected, or deleted (after=None).
    `before` is (kind, status, date) of the entry as it was."""
    was = before or (None, None, None)
    now = (after.kind, after.status, after.date) if after else (None, None, None)
    if 'irrigation' in (was[0], now[0]):
        _sync_last_irrigation(farm, removed_date=was[2] if was[:2] == ('irrigation', 'done') else None)
    if 'sowing' in (was[0], now[0]):
        if now[:2] == ('sowing', 'done'):
            farm.sowing_date = now[2]
        elif was[:2] == ('sowing', 'done') and farm.sowing_date == was[2]:
            other = farm.activities.filter(kind='sowing', status='done').order_by('-date').first()
            farm.sowing_date = other.date if other else None
        farm.save(update_fields=['sowing_date', 'updated_at'])


@require_http_methods(['PATCH', 'DELETE'])
def farm_activity_detail_api(request, farm_id, activity_id):
    """PATCH {kind?, status?, date?, amount_mm?, note?}: correct a log entry
    (wrong date, wrong amount, "not done" that was in fact done...).
    DELETE: remove it. Either way the plan is recomputed from the log."""
    if not _can_use_farmer_space(request.user):
        return _forbidden()
    farm = _get_farm(request, farm_id)
    activity = farm and farm.activities.filter(pk=activity_id).first()
    if not activity:
        return JsonResponse({'error': _('Not found.')}, status=404)
    from ..services.farm_tasks import serialize_activity
    before = (activity.kind, activity.status, activity.date)
    if request.method == 'DELETE':
        activity.delete()
        _sync_farm(farm, before, None)
        return JsonResponse({'deleted': activity_id, 'farm': fs.serialize_farm(farm)})

    data = _json_body(request)
    if data is None:
        return JsonResponse({'error': _('Invalid JSON.')}, status=400)
    merged = {
        'kind': data.get('kind', activity.kind),
        'status': data.get('status', activity.status),
        'date': data.get('date', activity.date.isoformat()),
        'amount_mm': data['amount_mm'] if 'amount_mm' in data else activity.amount_mm,
        'note': data.get('note', activity.note),
        'task_key': activity.task_key,
    }
    if merged['status'] == 'skipped' or merged['kind'] != 'irrigation':
        merged['amount_mm'] = None   # nothing was applied
    fields, error = _parse_activity(merged)
    if error:
        return JsonResponse({'error': _(error)}, status=400)
    for k, v in fields.items():
        setattr(activity, k, v)
    activity.save()
    _sync_farm(farm, before, activity)
    return JsonResponse({'activity': serialize_activity(activity), 'farm': fs.serialize_farm(farm)})


@require_http_methods(['GET'])
def farm_weather_api(request, farm_id):
    if not _can_use_farmer_space(request.user):
        return _forbidden()
    farm = _get_farm(request, farm_id)
    if farm is None:
        return JsonResponse({'error': _('Farm not found.')}, status=404)
    return JsonResponse(fs.farm_weather(farm))
