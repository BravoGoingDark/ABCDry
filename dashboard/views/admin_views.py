from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.views.decorators.http import require_http_methods
from django.utils.translation import gettext as _
from django.core.serializers.json import DjangoJSONEncoder
from django.conf import settings
from django.contrib.staticfiles.finders import find
import json
import os

from ..forms import UserCreateForm
from ..models import Farm, Region, UserProfile
from .utils import _is_admin_user, _deny_admin_access, _region_map_config, _lakes_by_region, _dashboard_js_i18n, _get_region_stations
from ..services import farmer_service as fs


# ---------------------------------------------------------------------------
# Geo-based region: a farm's displayed region is "Ichkeul" only when its
# centroid falls inside the Ichkeul basin borders. No GDAL/shapely dependency
# is available, so this uses a small pure-Python ray-casting point-in-polygon.
# ---------------------------------------------------------------------------
_ICHKEUL_POLYS = None


def _load_ichkeul_polys():
    """Return the Ichkeul basin as a list of [outer_ring, [hole, ...]] polygons.

    Cached in memory after the first load so every farm on the page shares it.
    """
    global _ICHKEUL_POLYS
    if _ICHKEUL_POLYS is not None:
        return _ICHKEUL_POLYS

    path = find('dashboard/data/ichkeul_basin.geojson')
    if not path:
        path = os.path.join(settings.BASE_DIR, 'static', 'dashboard', 'data', 'ichkeul_basin.geojson')

    polys = []
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
        for feat in data.get('features', []):
            geom = feat.get('geometry') or {}
            gtype = geom.get('type')
            coords = geom.get('coordinates') or []
            if gtype == 'Polygon':
                polys.append(coords)
            elif gtype == 'MultiPolygon':
                for poly in coords:
                    polys.append(poly)
    except (OSError, ValueError):
        polys = []

    _ICHKEUL_POLYS = polys
    return polys


def _point_in_ring(lon, lat, ring):
    """Ray casting test for a single ring (no hole handling)."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat):
            xint = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < xint:
                inside = not inside
        j = i
    return inside


def _point_in_polygon(lon, lat, coords):
    """True if the point is inside a GeoJSON Polygon (outer ring minus holes)."""
    if not coords or len(coords[0]) < 4:
        return False
    if not _point_in_ring(lon, lat, coords[0]):
        return False
    for hole in coords[1:]:
        if len(hole) >= 4 and _point_in_ring(lon, lat, hole):
            return False
    return True


def _farm_in_ichkeul(farm, polys):
    lat = getattr(farm, 'centroid_lat', None)
    lon = getattr(farm, 'centroid_lon', None)
    if lat is None or lon is None or not polys:
        return False
    return any(_point_in_polygon(float(lon), float(lat), poly) for poly in polys)



@login_required(login_url='dashboard:login')
def admin_panel(request):
    """Admin user management panel"""
    if not _is_admin_user(request.user):
        return _deny_admin_access(request)

    users = User.objects.all().select_related('profile').order_by('-date_joined')

    if request.method == 'POST':
        form = UserCreateForm(request.POST, user=request.user)
        if form.is_valid():
            user = form.save()
            messages.success(request, _('User "{}" created successfully!').format(user.username))
            return redirect('dashboard:admin_panel')
    else:
        form = UserCreateForm(user=request.user)

    context = {
        'form': form,
        'users': users,
    }
    return render(request, 'dashboard/admin_panel.html', context)


@login_required(login_url='dashboard:login')
def admin_edit_user(request, user_id):
    """Edit user role and region assignment"""
    if not _is_admin_user(request.user):
        return _deny_admin_access(request)

    target_user = get_object_or_404(User, pk=user_id)
    # Accounts created before the profile signal existed may have no profile.
    profile, _created = UserProfile.objects.get_or_create(
        user=target_user,
        defaults={'role': 'superadmin' if target_user.is_superuser else 'viewer'},
    )

    if request.method == 'POST':
        role = request.POST.get('role')
        region_id = request.POST.get('region')

        if role in dict(UserProfile.ROLE_CHOICES) and role != profile.role and role != 'superadmin':
            # Demoting yourself would lock you out of this page; demoting a
            # Django superuser has no effect since they stay admins regardless.
            if target_user == request.user:
                messages.error(request, _('You cannot remove your own superadmin role.'))
                return redirect('dashboard:admin_edit_user', user_id=target_user.pk)
            if target_user.is_superuser:
                messages.error(request, _('This account is a Django superuser and always keeps the superadmin role.'))
                return redirect('dashboard:admin_edit_user', user_id=target_user.pk)

        if role in dict(UserProfile.ROLE_CHOICES):
            profile.role = role
        if region_id and region_id.isdigit() and Region.objects.filter(pk=region_id).exists():
            profile.region_id = region_id
        else:
            profile.region = None
        profile.save()

        messages.success(request, _('User profile updated!'))
        return redirect('dashboard:admin_panel')

    context = {
        'target_user': target_user,
        'regions': Region.objects.all(),
        'role_choices': UserProfile.ROLE_CHOICES,
    }
    return render(request, 'dashboard/admin_edit_user.html', context)


@login_required(login_url='dashboard:login')
@require_http_methods(["POST"])
def admin_delete_user(request, user_id):
    """Delete a user (superadmin only)."""
    if not _is_admin_user(request.user):
        return _deny_admin_access(request)

    target_user = get_object_or_404(User, pk=user_id)
    if target_user == request.user:
        messages.error(request, _('You cannot delete your own account.'))
        return redirect('dashboard:admin_panel')

    target_user.delete()
    messages.success(request, _('User deleted successfully.'))
    return redirect('dashboard:admin_panel')


@login_required(login_url='dashboard:login')
@require_http_methods(["POST"])
def admin_confirm_user(request, user_id):
    """Confirm (activate) a pending farmer account (superadmin only)."""
    if not _is_admin_user(request.user):
        return _deny_admin_access(request)

    target_user = get_object_or_404(User, pk=user_id)
    if target_user.is_active:
        messages.info(request, _('"{}" is already confirmed.').format(target_user.username))
    else:
        target_user.is_active = True
        target_user.save(update_fields=['is_active'])
        messages.success(request, _('Account for "{}" confirmed — the user can now sign in.').format(target_user.username))
    return redirect('dashboard:admin_panel')


@login_required(login_url='dashboard:login')
def admin_farms(request):
    """Read-only overview of all farmer lands — who owns what, what is planted, where.

    Any signed-in analyst may open it (the sidebar advertises it under
    Administration and it has no mutating controls); farmer accounts are kept
    out by FarmerScopeMiddleware.
    """
    farms = Farm.objects.select_related('owner', 'owner__profile', 'region').order_by('-created_at')

    # Summary stats
    total_farms = farms.count()
    total_area = sum((f.area_ha for f in farms), 0)
    farmers_count = farms.values('owner').distinct().count()
    irrigated_count = farms.filter(irrigated=True).count()

    # Serialize farms for the map JavaScript
    ichkeul_polys = _load_ichkeul_polys()
    ichkeul_region = Region.objects.filter(name__icontains='ichkeul').first()
    ichkeul_region_name = ichkeul_region.name if ichkeul_region else 'Ichkeul'
    ichkeul_farm_ids = {f.pk for f in farms if _farm_in_ichkeul(f, ichkeul_polys)}

    farms_payload = []
    for f in farms:
        data = fs.serialize_farm(f)
        data['in_ichkeul'] = f.pk in ichkeul_farm_ids
        farms_payload.append(data)
    farms_json = json.dumps(farms_payload, cls=DjangoJSONEncoder)

    context = {
        'farms': farms,
        'total_farms': total_farms,
        'total_area': round(total_area, 2),
        'farmers_count': farmers_count,
        'irrigated_count': irrigated_count,
        'regions': Region.objects.all().order_by('name'),
        'region_map_config_json': json.dumps(_region_map_config()),
        'lakes_by_region_json': json.dumps(_lakes_by_region()),
        'dashboard_js_i18n_json': json.dumps(_dashboard_js_i18n()),
        'stations_json': json.dumps(_get_region_stations(None), cls=DjangoJSONEncoder),
        'farms_json': farms_json,
        'ichkeul_farm_ids': ichkeul_farm_ids,
        'ichkeul_region_name': ichkeul_region_name,
    }
    return render(request, 'dashboard/admin_farms.html', context)
