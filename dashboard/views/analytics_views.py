import json
from datetime import timedelta
from urllib.error import URLError
from urllib.request import urlopen

import pandas as pd
from openpyxl import Workbook
from django.db.models import Avg
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.core.serializers.json import DjangoJSONEncoder
from django.utils.translation import gettext as _
from django.utils import timezone
from django.urls import reverse

from ..forms import (
    RiskSimulationForm,
    SoilMetricsForm,
    ClimateMetricsForm,
    DroughtIndicesForm,
    AgriculturalMetricsForm,
    RemoteSensingMetricsForm,
    HydrologyMetricsForm,
)
from ..models import (
    CropType,
    EnvironmentalSnapshot,
    IrrigationMethod,
    ObservationYear,
    Region,
    RiskAssessment,
    Sensor,
    SoilMetrics,
    ClimateMetrics,
    DroughtIndices,
    AgriculturalMetrics,
    RemoteSensingMetrics,
    HydrologyMetrics,
)
from .utils import (
    _seed_reference_data,
    _is_admin_user,
    _is_subadmin_user,
    _is_viewer_user,
    _deny_data_access,
    _check_data_permission,
    _haversine_distance,
    _calculate_risk,
    assess_drought_risk,
    _degree_to_compass,
    _region_map_config,
    _lakes_by_region,
    _dashboard_js_i18n,
    _svg_points,
    _month_labels,
    _chart_series,
    _chart_months,
    _normalize,
    _year_series,
    _year_months,
    METRIC_BROWSER_CONFIGS,
    _build_browser_section,
    _get_region_stations,
)


def _demo_dashboard_chart_data():
    """Return realistic sample data when a region has no recent metric rows."""
    months = ["Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May"]
    return {
        "chart_months": months,
        "climate_rainfall": [48, 41, 58, 72, 93, 66, 54, 63, 82, 75, 59, 51],
        "climate_temp": [27, 29, 30, 32, 34, 35, 33, 30, 28, 25, 23, 22],
        "drought_spi": [0.4, 0.2, -0.3, -0.8, -1.2, -0.5, 0.1, 0.5, 0.2, -0.6, -1.0, -0.4],
        "drought_spei": [0.2, 0.1, -0.4, -0.7, -1.4, -0.9, -0.2, 0.3, 0.1, -0.5, -1.1, -0.7],
        "ndvi_values": [0.48, 0.52, 0.58, 0.65, 0.72, 0.76, 0.80, 0.78, 0.74, 0.70, 0.64, 0.60],
    }


def live_metrics_api(request):
    try:
        lat = float(request.GET.get("lat", "37.16"))
        lon = float(request.GET.get("lon", "9.66"))
    except ValueError:
        return JsonResponse({"error": "Invalid coordinates"}, status=400)

    api_url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&current=temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,wind_gusts_10m,wind_direction_10m"
        "&timezone=auto"
    )

    try:
        with urlopen(api_url, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except URLError:
        return JsonResponse({"error": "Unable to fetch live metrics"}, status=502)

    current = payload.get("current", {})
    wind_speed = float(current.get("wind_speed_10m", 0))
    wind_gust = float(current.get("wind_gusts_10m", wind_speed))
    wind_deg = float(current.get("wind_direction_10m", 0))
    precipitation = float(current.get("precipitation", 0))
    temperature = float(current.get("temperature_2m", 0))
    humidity = int(current.get("relative_humidity_2m", 0))

    delta = 0
    avg_rainfall = ClimateMetrics.objects.filter(
        rainfall_mm__isnull=False
    ).aggregate(avg=Avg("rainfall_mm"))["avg"]
    if avg_rainfall is not None and avg_rainfall > 0:
        delta = round(((precipitation - float(avg_rainfall)) / float(avg_rainfall)) * 100)

    return JsonResponse(
        {
            "wind_speed_kmh": round(wind_speed, 1),
            "wind_gust_kmh": round(wind_gust, 1),
            "wind_direction": _degree_to_compass(wind_deg),
            "rainfall_mm": round(precipitation, 1),
            "rainfall_delta_percent": delta,
            "temperature_c": round(temperature, 1),
            "humidity_percent": humidity,
            "source": "open-meteo",
        }
    )


@require_http_methods(["GET"])
def resolve_region_api(request):
    """Given lat/lon, return the nearest region's ID and name."""
    try:
        lat = float(request.GET.get("lat", "0"))
        lon = float(request.GET.get("lon", "0"))
    except ValueError:
        return JsonResponse({"error": "Invalid coordinates"}, status=400)
    regions = Region.objects.filter(latitude__isnull=False, longitude__isnull=False)
    nearest = None
    nearest_dist = float("inf")
    for region in regions:
        dist = _haversine_distance(lat, lon, float(region.latitude), float(region.longitude))
        if dist < nearest_dist:
            nearest_dist = dist
            nearest = region
    if nearest is None:
        first = Region.objects.order_by("name").first()
        if first:
            return JsonResponse({"region_id": first.id, "region_name": first.name, "distance_km": 0})
        return JsonResponse({"error": "No regions found"}, status=404)
    return JsonResponse({
        "region_id": nearest.id,
        "region_name": nearest.name,
        "distance_km": round(nearest_dist, 1),
    })


def dashboard_view(request):
    _seed_reference_data()
    result = None
    form = RiskSimulationForm(request.POST or None)
    now = timezone.now()
    year_ago = now - timedelta(days=365)

    if request.method == "POST" and form.is_valid():
        region = form.cleaned_data["region"]
        if not _check_data_permission(request, region.id if region else None):
            messages.error(request, _('You do not have permission to submit risk assessments.'))
            return redirect('dashboard:dashboard')
        year = form.cleaned_data["year"]
        crop = form.cleaned_data["crop"]
        irrigation = form.cleaned_data["irrigation"]
        risk = assess_drought_risk(region, crop.name, irrigation.name)
        risk_level, recommendation = risk["risk_level"], risk["recommendation"]
        result = {
            "risk_level": risk_level,
            "recommendation": recommendation,
            "spei": risk["spei"],
            "risk_score": risk["score"],
            "spei_level": risk["level"],
            "risk_band": risk["band"],
            "measured_on": risk["measured_on"],
            "stale": risk["stale"],
            "assessed": risk["assessed"],
        }
        RiskAssessment.objects.create(
            region=region,
            year=year,
            crop=crop,
            irrigation=irrigation,
            risk_level=risk_level,
            recommendation=recommendation,
            created_by=request.user if request.user.is_authenticated else None,
        )
        snapshot = EnvironmentalSnapshot.objects.filter(region=region, year=year).first()
        chart_region = region
        chart_year = year
    else:
        default_region = (
            Region.objects.filter(name__iexact="Ichkeul").first()
            or Region.objects.filter(name__iexact="Bizerte").first()
            or Region.objects.filter(climate_metrics__isnull=False).first()
            or Region.objects.filter(drought_indices__isnull=False).first()
            or Region.objects.filter(remote_sensing__isnull=False).first()
            or Region.objects.order_by('name').first()
        )
        # Prefer the most recent year that has actual data for this region so
        # we never land on a year (e.g. 2026) for which no rows exist yet.
        _yr_with_data = (
            ObservationYear.objects.filter(
                climatemetrics__region=default_region
            ).order_by("-label").first()
            or ObservationYear.objects.filter(
                droughtindices__region=default_region
            ).order_by("-label").first()
            or ObservationYear.objects.filter(
                remotesensingmetrics__region=default_region
            ).order_by("-label").first()
        )
        default_year = (
            _yr_with_data
            or ObservationYear.objects.filter(climatemetrics__isnull=False).order_by('-label').first()
            or ObservationYear.objects.filter(droughtindices__isnull=False).order_by('-label').first()
            or ObservationYear.objects.order_by('-label').first()
        )
        snapshot = EnvironmentalSnapshot.objects.filter(
            region=default_region, year=default_year
        ).first()
        chart_region = default_region
        chart_year = default_year

        # Auto-assess drought risk on initial GET so the gauge always shows real data
        default_crop = CropType.objects.order_by('name').first()
        default_irrigation = IrrigationMethod.objects.order_by('name').first()
        if default_region and default_crop and default_irrigation:
            risk = assess_drought_risk(default_region, default_crop.name, default_irrigation.name)
            result = {
                "risk_level": risk["risk_level"],
                "recommendation": risk["recommendation"],
                "spei": risk["spei"],
                "risk_score": risk["score"],
                "spei_level": risk["level"],
                "risk_band": risk["band"],
                "measured_on": risk["measured_on"],
                "stale": risk["stale"],
                "assessed": risk["assessed"],
            }

    months = _month_labels()

    try:
        year_num = int(chart_year.label.split()[0])
    except (ValueError, AttributeError):
        year_num = None

    if year_num:
        climate_qs = ClimateMetrics.objects.filter(
            region=chart_region, measurement_date__year=year_num
        ).order_by("-measurement_date")
        drought_qs = DroughtIndices.objects.filter(
            region=chart_region, measurement_date__year=year_num
        ).order_by("-measurement_date")
        rs_qs = RemoteSensingMetrics.objects.filter(
            region=chart_region, measurement_date__year=year_num
        ).order_by("-measurement_date")

        climate_rainfall = _year_series(climate_qs, "rainfall_mm")
        climate_temp = _year_series(climate_qs, "temperature_mean_c")
        drought_spi = _year_series(drought_qs, "spi_3month")
        drought_spei = _year_series(drought_qs, "spei_3month")
        ndvi_values = _year_series(rs_qs, "ndvi")

        chart_months = _year_months(climate_qs, "rainfall_mm")
    else:
        climate_qs = ClimateMetrics.objects.filter(
            region=chart_region, measurement_date__gte=year_ago
        ).order_by("-measurement_date")
        drought_qs = DroughtIndices.objects.filter(
            region=chart_region, measurement_date__gte=year_ago
        ).order_by("-measurement_date")
        rs_qs = RemoteSensingMetrics.objects.filter(
            region=chart_region, measurement_date__gte=year_ago
        ).order_by("-measurement_date")

        climate_rainfall = _chart_series(climate_qs, "rainfall_mm")
        climate_temp = _chart_series(climate_qs, "temperature_mean_c")
        drought_spi = _chart_series(drought_qs, "spi_3month")
        drought_spei = _chart_series(drought_qs, "spei_3month")
        ndvi_values = _chart_series(rs_qs, "ndvi")

        chart_months = _chart_months(climate_qs, "rainfall_mm")

    # Per-series demo fallback: each empty series gets realistic sample data
    # independently so that even partial data never leaves a chart line blank.
    demo = _demo_dashboard_chart_data()
    if not climate_rainfall:
        climate_rainfall = demo["climate_rainfall"]
    if not climate_temp:
        climate_temp = demo["climate_temp"]
    if not drought_spi:
        drought_spi = demo["drought_spi"]
    if not drought_spei:
        drought_spei = demo["drought_spei"]
    if not ndvi_values:
        ndvi_values = demo["ndvi_values"]
    if not any(chart_months):
        chart_months = demo["chart_months"]

    climate_rainfall_norm = _normalize(climate_rainfall)
    climate_temp_norm = _normalize(climate_temp)
    drought_spi_norm = _normalize(drought_spi)
    ndvi_values_norm = _normalize(ndvi_values)

    spi_min, spi_max = -3, 3
    ndvi_min, ndvi_max = 0, 1

    def _labels(lo, hi):
        return [hi, hi - (hi - lo) / 3, lo + (hi - lo) / 3, lo]

    context = {
        "form": form,
        "result": result,
        "snapshot": snapshot,
        "recent_assessments": RiskAssessment.objects.select_related(
            "region", "year", "crop", "irrigation"
        ).order_by("-created_at")[:5],
        "regions": Region.objects.all(),
        "years": ObservationYear.objects.all(),
        "climate_points_rainfall": _svg_points(climate_rainfall_norm, vmin=0, vmax=100),
        "climate_points_temp": _svg_points(climate_temp_norm, vmin=0, vmax=100),
        "climate_points_spi": _svg_points(drought_spi_norm, vmin=0, vmax=100),
        "climate_points_ndvi": _svg_points(ndvi_values_norm, vmin=0, vmax=100),
        "drought_points_spi": _svg_points(drought_spi, vmin=spi_min, vmax=spi_max),
        "drought_points_spei": _svg_points(drought_spei, vmin=spi_min, vmax=spi_max),
        "ndvi_points": _svg_points(ndvi_values, vmin=ndvi_min, vmax=ndvi_max),
        "climate_labels": _labels(0, 100),
        "drought_labels": _labels(spi_min, spi_max),
        "ndvi_labels": _labels(ndvi_min, ndvi_max),
        "chart_months": chart_months,
        "months": chart_months,
        "selected_region": chart_region,
        "selected_year": chart_year,
        "region_map_config_json": json.dumps(_region_map_config()),
        "region_map_json": json.dumps(_region_map_config()),
        "lakes_by_region_json": json.dumps(_lakes_by_region()),
        "dashboard_js_i18n_json": json.dumps(_dashboard_js_i18n()),
        "sensors": Sensor.objects.filter(is_active=True).select_related("region"),
        "stations": _get_region_stations(chart_region, chart_year),
        "stations_json": json.dumps(_get_region_stations(chart_region, chart_year), cls=DjangoJSONEncoder),
        "demo_risk_banner": {
            "level": _("Demo Risk Level"),
            "body": _("This is a demo risk banner shown when no risk assessment has been performed."),
        },
    }
    return render(request, "dashboard/dashboard.html", context)


def chart_data_api(request):
    """Return chart data for a given region, matching dashboard_view format."""
    region_id = request.GET.get("region_id")
    if not region_id:
        return JsonResponse({"error": "region_id required"}, status=400)
    try:
        region = Region.objects.get(pk=region_id)
    except Region.DoesNotExist:
        return JsonResponse({"error": "Region not found"}, status=404)

    now = timezone.now()
    year_ago = now - timedelta(days=365)
    year_id = request.GET.get("year_id")
    year_num = None
    if year_id:
        try:
            year_obj = ObservationYear.objects.get(pk=year_id)
            year_num = int(year_obj.label.split()[0])
        except (ObservationYear.DoesNotExist, ValueError, AttributeError):
            pass

    if year_num:
        climate_qs = ClimateMetrics.objects.filter(
            region=region, measurement_date__year=year_num
        ).order_by("-measurement_date")
        drought_qs = DroughtIndices.objects.filter(
            region=region, measurement_date__year=year_num
        ).order_by("-measurement_date")
        rs_qs = RemoteSensingMetrics.objects.filter(
            region=region, measurement_date__year=year_num
        ).order_by("-measurement_date")

        climate_rainfall = _year_series(climate_qs, "rainfall_mm")
        climate_temp = _year_series(climate_qs, "temperature_mean_c")
        drought_spi = _year_series(drought_qs, "spi_3month")
        drought_spei = _year_series(drought_qs, "spei_3month")
        ndvi_values = _year_series(rs_qs, "ndvi")

        chart_months = _year_months(climate_qs, "rainfall_mm")
    else:
        climate_qs = ClimateMetrics.objects.filter(
            region=region, measurement_date__gte=year_ago
        ).order_by("-measurement_date")
        climate_rainfall = _chart_series(climate_qs, "rainfall_mm")
        climate_temp = _chart_series(climate_qs, "temperature_mean_c")

        drought_qs = DroughtIndices.objects.filter(
            region=region, measurement_date__gte=year_ago
        ).order_by("-measurement_date")
        drought_spi = _chart_series(drought_qs, "spi_3month")
        drought_spei = _chart_series(drought_qs, "spei_3month")

        rs_qs = RemoteSensingMetrics.objects.filter(
            region=region, measurement_date__gte=year_ago
        ).order_by("-measurement_date")
        ndvi_values = _chart_series(rs_qs, "ndvi")

        chart_months = _chart_months(climate_qs, "rainfall_mm")

    demo = _demo_dashboard_chart_data()
    if not climate_rainfall:
        climate_rainfall = demo["climate_rainfall"]
    if not climate_temp:
        climate_temp = demo["climate_temp"]
    if not drought_spi:
        drought_spi = demo["drought_spi"]
    if not drought_spei:
        drought_spei = demo["drought_spei"]
    if not ndvi_values:
        ndvi_values = demo["ndvi_values"]
    if not any(chart_months):
        chart_months = demo["chart_months"]

    climate_rainfall_norm = _normalize(climate_rainfall)
    climate_temp_norm = _normalize(climate_temp)
    drought_spi_norm = _normalize(drought_spi)
    ndvi_values_norm = _normalize(ndvi_values)

    spi_min, spi_max = -3, 3
    ndvi_min, ndvi_max = 0, 1

    def _labels(lo, hi):
        return [hi, hi - (hi - lo) / 3, lo + (hi - lo) / 3, lo]

    payload = {
        "climate_points_rainfall": _svg_points(climate_rainfall_norm, vmin=0, vmax=100),
        "climate_points_temp": _svg_points(climate_temp_norm, vmin=0, vmax=100),
        "climate_points_spi": _svg_points(drought_spi_norm, vmin=0, vmax=100),
        "climate_points_ndvi": _svg_points(ndvi_values_norm, vmin=0, vmax=100),
        "drought_points_spi": _svg_points(drought_spi, vmin=spi_min, vmax=spi_max),
        "drought_points_spei": _svg_points(drought_spei, vmin=spi_min, vmax=spi_max),
        "ndvi_points": _svg_points(ndvi_values, vmin=ndvi_min, vmax=ndvi_max),
        "climate_labels": _labels(0, 100),
        "drought_labels": _labels(spi_min, spi_max),
        "ndvi_labels": _labels(ndvi_min, ndvi_max),
        "chart_months": chart_months,
        "months": chart_months,
    }
    return JsonResponse(payload)


def historical_view(request):
    """Display historical comparison and climate trends"""
    context = {
        'regions': Region.objects.all().order_by('name'),
        'years': ObservationYear.objects.all(),
        'title': _('Historical Comparison'),
    }
    return render(request, 'dashboard/historical.html', context)


def historical_export_excel(request):
    """Export historical data for a region + date range as Excel."""
    region_id = request.GET.get('region_id')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    if not all([region_id, date_from, date_to]):
        return HttpResponse('Missing required parameters', status=400)

    try:
        region = Region.objects.get(pk=region_id)
    except Region.DoesNotExist:
        return HttpResponse('Invalid region', status=404)

    wb = Workbook()
    ws = wb.active
    ws.title = f"History_{region.name}"

    headers = ['Date', 'Soil Moisture (%)', 'Rainfall (mm)', 'Temp Max (°C)', 'Temp Min (°C)', 'NDVI', 'SPI-1', 'SPI-3']
    ws.append(headers)

    climate_qs = ClimateMetrics.objects.filter(
        region=region, measurement_date__gte=date_from, measurement_date__lte=date_to
    ).order_by('measurement_date')

    for c in climate_qs:
        mdate = c.measurement_date
        soil = SoilMetrics.objects.filter(region=region, measurement_date=mdate).first()
        rs = RemoteSensingMetrics.objects.filter(region=region, measurement_date=mdate).first()
        di = DroughtIndices.objects.filter(region=region, measurement_date=mdate).first()

        row = [
            mdate.isoformat() if mdate else '',
            float(soil.moisture_content_percent) if soil and soil.moisture_content_percent is not None else '',
            float(c.rainfall_mm) if c.rainfall_mm is not None else '',
            float(c.temperature_max_c) if c.temperature_max_c is not None else '',
            float(c.temperature_min_c) if c.temperature_min_c is not None else '',
            float(rs.ndvi) if rs and rs.ndvi is not None else '',
            float(di.spi_1month) if di and di.spi_1month is not None else '',
            float(di.spi_3month) if di and di.spi_3month is not None else '',
        ]
        ws.append(row)

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    fname = f"historical_{region.name.lower()}_{date_from}_to_{date_to}.xlsx"
    response['Content-Disposition'] = f'attachment; filename="{fname}"'
    wb.save(response)
    return response


def metrics_browser(request):
    """Browse all metric tables with edit/delete actions and client-side filters."""
    sections = [_build_browser_section(key, config) for key, config in METRIC_BROWSER_CONFIGS.items()]
    context = {
        "title": "View All Metrics",
        "sections": sections,
        "regions": Region.objects.order_by("name"),
        "years": ObservationYear.objects.order_by("-label"),
        "crops": CropType.objects.order_by("name"),
        "section_count": len(sections),
        "total_rows": sum(section["count"] for section in sections),
    }
    return render(request, "dashboard/metrics_browser.html", context)


def edit_metric_entry(request, metric_type, pk):
    """Edit a single metric entry."""
    config = METRIC_BROWSER_CONFIGS.get(metric_type)
    if not config:
        messages.error(request, _("Unknown metric type."))
        return redirect("dashboard:metrics_browser")

    instance = get_object_or_404(config["model"], pk=pk)
    region_id = getattr(instance, 'region_id', None)
    if not _check_data_permission(request, region_id):
        return _deny_data_access(request)

    form_class = config["form"]

    if request.method == "POST":
        form = form_class(request.POST, instance=instance)
        if form.is_valid():
            form.save()
            messages.success(request, _("%s updated successfully!") % config["title"])
            return redirect(reverse("dashboard:metrics_browser") + f"#{metric_type}")
    else:
        form = form_class(instance=instance)

    context = {
        "title": f"Edit {config['title']}",
        "form": form,
        "metric_type": metric_type,
        "back_url": reverse("dashboard:metrics_browser") + f"#{metric_type}",
        "section_title": config["title"],
        "record_label": str(instance),
    }
    return render(request, "dashboard/metrics_form.html", context)


@require_http_methods(["POST"])
def delete_metric_entry(request, metric_type, pk):
    """Delete a single metric entry."""
    config = METRIC_BROWSER_CONFIGS.get(metric_type)
    if not config:
        messages.error(request, _("Unknown metric type."))
        return redirect("dashboard:metrics_browser")

    instance = get_object_or_404(config["model"], pk=pk)
    region_id = getattr(instance, 'region_id', None)
    if not _check_data_permission(request, region_id):
        return _deny_data_access(request)

    instance.delete()
    messages.success(request, _("%s deleted successfully!") % config["title"])
    return redirect(reverse("dashboard:metrics_browser") + f"#{metric_type}")


@require_http_methods(["POST"])
def delete_metric_table(request, metric_type):
    """Delete all entries for a given metric type. Region-restricted for subadmins."""
    config = METRIC_BROWSER_CONFIGS.get(metric_type)
    if not config:
        messages.error(request, _("Unknown metric type."))
        return redirect("dashboard:metrics_browser")

    if _is_viewer_user(request.user):
        return _deny_data_access(request)

    model = config["model"]
    if _is_admin_user(request.user):
        model.objects.all().delete()
    elif _is_subadmin_user(request.user):
        region_id = request.user.profile.region_id
        if region_id:
            model.objects.filter(region_id=region_id).delete()
        else:
            messages.error(request, _("No region assigned to your account."))
            return redirect("dashboard:metrics_browser")
    else:
        return _deny_data_access(request)

    messages.success(request, _("All %s deleted successfully!") % config["title"])
    return redirect(reverse("dashboard:metrics_browser") + f"#{metric_type}")


@require_http_methods(["POST"])
def delete_all_metrics(request):
    """Delete all metric data across all tables. Superadmin — full; Subadmin — own region only."""
    if _is_viewer_user(request.user):
        return _deny_data_access(request)

    if _is_admin_user(request.user):
        for config in METRIC_BROWSER_CONFIGS.values():
            config["model"].objects.all().delete()
        messages.success(request, _("All metric data deleted successfully!"))
    elif _is_subadmin_user(request.user):
        region_id = request.user.profile.region_id
        if not region_id:
            messages.error(request, _("No region assigned to your account."))
            return redirect("dashboard:metrics_browser")
        for config in METRIC_BROWSER_CONFIGS.values():
            config["model"].objects.filter(region_id=region_id).delete()
        messages.success(request, _("All data for your region deleted successfully!"))
    else:
        return _deny_data_access(request)

    return redirect("dashboard:metrics_browser")


def soil_metrics_view(request):
    """Display and manage soil metrics"""
    return redirect(reverse('dashboard:metrics_browser') + '#soil')


def climate_metrics_view(request):
    """Display and manage climate metrics"""
    return redirect(reverse('dashboard:metrics_browser') + '#climate')


def drought_indices_view(request):
    """Display and manage drought indices"""
    return redirect(reverse('dashboard:metrics_browser') + '#drought')


def agricultural_metrics_view(request):
    """Display and manage agricultural metrics"""
    return redirect(reverse('dashboard:metrics_browser') + '#agricultural')


def remote_sensing_view(request):
    """Display and manage remote sensing metrics"""
    return redirect(reverse('dashboard:metrics_browser') + '#remote_sensing')


def hydrology_metrics_view(request):
    """Display and manage hydrology metrics"""
    return redirect(reverse('dashboard:metrics_browser') + '#hydrology')


def add_soil_metrics(request):
    """Add new soil metrics"""
    if not _check_data_permission(request):
        return _deny_data_access(request)
    if request.method == 'POST':
        form = SoilMetricsForm(request.POST)
        if form.is_valid():
            region = form.cleaned_data.get('region')
            if not _check_data_permission(request, region.id if region else None):
                messages.error(request, _('You can only add data for your assigned region.'))
                return render(request, 'dashboard/metrics_form.html', {'form': form, 'title': 'Add Soil Metrics'})
            instance = form.save(commit=False)
            instance.created_by = request.user if request.user.is_authenticated else None
            instance.save()
            messages.success(request, _('Soil metrics added successfully!'))
            return redirect('dashboard:soil_metrics')
    else:
        form = SoilMetricsForm()
    
    return render(request, 'dashboard/metrics_form.html', {'form': form, 'title': 'Add Soil Metrics'})


def add_climate_metrics(request):
    """Add new climate metrics"""
    if not _check_data_permission(request):
        return _deny_data_access(request)
    if request.method == 'POST':
        form = ClimateMetricsForm(request.POST)
        if form.is_valid():
            region = form.cleaned_data.get('region')
            if not _check_data_permission(request, region.id if region else None):
                messages.error(request, _('You can only add data for your assigned region.'))
                return render(request, 'dashboard/metrics_form.html', {'form': form, 'title': 'Add Climate Metrics'})
            instance = form.save(commit=False)
            instance.created_by = request.user if request.user.is_authenticated else None
            instance.save()
            messages.success(request, _('Climate metrics added successfully!'))
            return redirect('dashboard:climate_metrics')
    else:
        form = ClimateMetricsForm()
    
    return render(request, 'dashboard/metrics_form.html', {'form': form, 'title': 'Add Climate Metrics'})


def add_drought_indices(request):
    """Add new drought indices"""
    if not _check_data_permission(request):
        return _deny_data_access(request)
    if request.method == 'POST':
        form = DroughtIndicesForm(request.POST)
        if form.is_valid():
            region = form.cleaned_data.get('region')
            if not _check_data_permission(request, region.id if region else None):
                messages.error(request, _('You can only add data for your assigned region.'))
                return render(request, 'dashboard/metrics_form.html', {'form': form, 'title': 'Add Drought Indices'})
            instance = form.save(commit=False)
            instance.created_by = request.user if request.user.is_authenticated else None
            instance.save()
            messages.success(request, _('Drought indices added successfully!'))
            return redirect('dashboard:drought_indices')
    else:
        form = DroughtIndicesForm()
    
    return render(request, 'dashboard/metrics_form.html', {'form': form, 'title': 'Add Drought Indices'})


def add_agricultural_metrics(request):
    """Add new agricultural metrics"""
    if not _check_data_permission(request):
        return _deny_data_access(request)
    if request.method == 'POST':
        form = AgriculturalMetricsForm(request.POST)
        if form.is_valid():
            region = form.cleaned_data.get('region')
            if not _check_data_permission(request, region.id if region else None):
                messages.error(request, _('You can only add data for your assigned region.'))
                return render(request, 'dashboard/metrics_form.html', {'form': form, 'title': 'Add Agricultural Metrics'})
            instance = form.save(commit=False)
            instance.created_by = request.user if request.user.is_authenticated else None
            instance.save()
            messages.success(request, _('Agricultural metrics added successfully!'))
            return redirect('dashboard:agricultural_metrics')
    else:
        form = AgriculturalMetricsForm()
    
    return render(request, 'dashboard/metrics_form.html', {'form': form, 'title': 'Add Agricultural Metrics'})


def add_remote_sensing_metrics(request):
    """Add new remote sensing metrics"""
    if not _check_data_permission(request):
        return _deny_data_access(request)
    if request.method == 'POST':
        form = RemoteSensingMetricsForm(request.POST)
        if form.is_valid():
            region = form.cleaned_data.get('region')
            if not _check_data_permission(request, region.id if region else None):
                messages.error(request, _('You can only add data for your assigned region.'))
                return render(request, 'dashboard/metrics_form.html', {'form': form, 'title': 'Add Remote Sensing Metrics'})
            instance = form.save(commit=False)
            instance.created_by = request.user if request.user.is_authenticated else None
            instance.save()
            messages.success(request, _('Remote sensing metrics added successfully!'))
            return redirect('dashboard:remote_sensing')
    else:
        form = RemoteSensingMetricsForm()
    
    return render(request, 'dashboard/metrics_form.html', {'form': form, 'title': 'Add Remote Sensing Metrics'})


def add_hydrology_metrics(request):
    """Add new hydrology metrics"""
    if not _check_data_permission(request):
        return _deny_data_access(request)
    if request.method == 'POST':
        form = HydrologyMetricsForm(request.POST)
        if form.is_valid():
            region = form.cleaned_data.get('region')
            if not _check_data_permission(request, region.id if region else None):
                messages.error(request, _('You can only add data for your assigned region.'))
                return render(request, 'dashboard/metrics_form.html', {'form': form, 'title': 'Add Hydrology Metrics'})
            instance = form.save(commit=False)
            instance.created_by = request.user if request.user.is_authenticated else None
            instance.save()
            messages.success(request, _('Hydrology metrics added successfully!'))
            return redirect('dashboard:hydrology_metrics')
    else:
        form = HydrologyMetricsForm()
    
    return render(request, 'dashboard/metrics_form.html', {'form': form, 'title': 'Add Hydrology Metrics'})
