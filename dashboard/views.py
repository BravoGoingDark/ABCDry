import json
from urllib.error import URLError
from urllib.request import urlopen
from io import BytesIO

import pandas as pd
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.utils.translation import gettext as _
from django.urls import reverse

from .forms import (
    RiskSimulationForm,
    SoilMetricsForm,
    ClimateMetricsForm,
    DroughtIndicesForm,
    AgriculturalMetricsForm,
    RemoteSensingMetricsForm,
    HydrologyMetricsForm,
    ExcelImportForm,
    BulkMetricsImportForm,
)
from .models import (
    CropType,
    EnvironmentalSnapshot,
    IrrigationMethod,
    ObservationYear,
    Region,
    RiskAssessment,
    DroughtPrediction,
    SoilMetrics,
    ClimateMetrics,
    DroughtIndices,
    AgriculturalMetrics,
    RemoteSensingMetrics,
    HydrologyMetrics,
    DataImportLog,
)
from .data_ingestion_utils import DataImporter, DataIngestionError, create_reference_data


def _seed_reference_data():
    CropType.objects.filter(name="Ble (Durum)").update(name="Blé (Durum)")
    IrrigationMethod.objects.filter(name="Irrigation au goutte-a-goutte").update(
        name="Irrigation au goutte-à-goutte"
    )
    IrrigationMethod.objects.filter(name="Alimente par la pluie").update(
        name="Alimenté par la pluie"
    )

    for region in ["Tunisia", "Morocco", "Algeria"]:
        Region.objects.get_or_create(name=region)
    for year in ["2024 (Current)", "2023", "2022", "2020 - 2024", "2015 - 2019"]:
        ObservationYear.objects.get_or_create(label=year)
    for crop in ["Blé (Durum)", "Olives", "Tomates", "Orge"]:
        CropType.objects.get_or_create(name=crop)
    for irrigation in [
        "Irrigation au goutte-à-goutte",
        "Asperseurs",
        "Alimenté par la pluie",
    ]:
        IrrigationMethod.objects.get_or_create(name=irrigation)

    region = Region.objects.get(name="Tunisia")
    year = ObservationYear.objects.get(label="2024 (Current)")
    EnvironmentalSnapshot.objects.get_or_create(
        region=region,
        year=year,
        defaults={
            "wind_speed_kmh": 24,
            "wind_gust_kmh": 32,
            "wind_direction": "NE",
            "rainfall_mm": 18.5,
            "rainfall_delta_percent": -12,
            "ph_level": 7.2,
            "npk_index": "Med-High",
            "temperature_c": 28,
            "humidity_percent": 64,
        },
    )


def _metric_browser_value(value):
    if value is None or value == "":
        return "—"
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)


METRIC_BROWSER_CONFIGS = {
    "soil": {
        "title": "Soil Metrics",
        "model": SoilMetrics,
        "form": SoilMetricsForm,
        "select_related": ("region", "year"),
        "add_url": "dashboard:add_soil_metrics",
        "export_type": "soil",
    },
    "climate": {
        "title": "Climate Metrics",
        "model": ClimateMetrics,
        "form": ClimateMetricsForm,
        "select_related": ("region", "year"),
        "add_url": "dashboard:add_climate_metrics",
        "export_type": "climate",
    },
    "drought": {
        "title": "Drought Indices",
        "model": DroughtIndices,
        "form": DroughtIndicesForm,
        "select_related": ("region", "year"),
        "add_url": "dashboard:add_drought_indices",
        "export_type": "drought",
    },
    "agricultural": {
        "title": "Agricultural Metrics",
        "model": AgriculturalMetrics,
        "form": AgriculturalMetricsForm,
        "select_related": ("region", "year", "crop", "irrigation_method"),
        "add_url": "dashboard:add_agricultural_metrics",
        "export_type": "agricultural",
    },
    "remote_sensing": {
        "title": "Remote Sensing Metrics",
        "model": RemoteSensingMetrics,
        "form": RemoteSensingMetricsForm,
        "select_related": ("region", "year"),
        "add_url": "dashboard:add_remote_sensing_metrics",
        "export_type": "remote_sensing",
    },
    "hydrology": {
        "title": "Hydrology Metrics",
        "model": HydrologyMetrics,
        "form": HydrologyMetricsForm,
        "select_related": ("region", "year"),
        "add_url": "dashboard:add_hydrology_metrics",
        "export_type": "hydrology",
    },
}


def _build_browser_row(obj):
    values = []
    search_bits = []
    for field in obj._meta.fields:
        display = _metric_browser_value(getattr(obj, field.name))
        values.append(display)
        search_bits.append(display.lower())

    return {
        "pk": obj.pk,
        "values": values,
        "search_text": " ".join(search_bits).lower(),
        "filters": {
            "region_id": getattr(obj, "region_id", ""),
            "year_id": getattr(obj, "year_id", ""),
            "crop_id": getattr(obj, "crop_id", ""),
        },
    }


def _build_browser_section(key, config):
    queryset = config["model"].objects.select_related(*config["select_related"]).order_by("-measurement_date")
    rows = [_build_browser_row(obj) for obj in queryset]
    return {
        "key": key,
        "title": config["title"],
        "model_name": config["model"].__name__,
        "headers": [field.verbose_name.title() for field in config["model"]._meta.fields],
        "rows": rows,
        "count": len(rows),
        "add_url": reverse(config["add_url"]),
        "export_url": reverse("dashboard:export_metrics", args=[config["export_type"]]),
    }


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
    instance.delete()
    messages.success(request, _("%s deleted successfully!") % config["title"])
    return redirect(reverse("dashboard:metrics_browser") + f"#{metric_type}")


def _calculate_risk(crop_name, irrigation_name):
    crop_lower = crop_name.lower()
    irr_lower = irrigation_name.lower()
    wheat_like = "blé" in crop_lower or "ble" in crop_lower or "durum" in crop_lower or "wheat" in crop_lower
    drip_like = "goutte" in irr_lower or "drip" in irr_lower
    if wheat_like and drip_like:
        return (
            _("High risk"),
            _(
                "Current soil salinity levels in sector 4 are incompatible with durum wheat under drip irrigation. "
                "Consider switching to highly salt-tolerant crops or scheduling intensive leaching protocols before sowing."
            ),
        )
    if "olive" in crop_lower or "oliv" in crop_lower:
        return (
            _("Moderate risk"),
            _("The crop is generally suitable. Monitor soil moisture and optimize water application."),
        )
    return (
        _("Low risk"),
        _("Current indicators are favorable. Continue weekly monitoring."),
    )


def _degree_to_compass(degree):
    directions = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]
    idx = int((degree % 360) / 45 + 0.5) % 8
    return directions[idx]


def _region_map_config():
    return {
        "tunisia": {
            "center": [37.13, 9.67],
            "zoom": 8,
            "label": _("Ichkeul National Park, Tunisia"),
        },
        "morocco": {
            "center": [34.02, -6.84],
            "zoom": 8,
            "label": _("Rabat area, Morocco"),
        },
        "algeria": {
            "center": [36.75, 3.06],
            "zoom": 8,
            "label": _("Algiers area, Algeria"),
        },
    }


def _lakes_by_region():
    return {
        "tunisia": [
            {"key": "ichkeul", "label": _("Lake Ichkeul"), "center": [37.16, 9.66], "zoom": 11},
            {"key": "ghezala", "label": _("Lake Ghezala"), "center": [37.03, 9.34], "zoom": 11},
            {"key": "bizerte", "label": _("Lake of Bizerte"), "center": [37.23, 9.89], "zoom": 11},
        ],
        "morocco": [
            {"key": "dayet-aoua", "label": _("Dayet Aoua"), "center": [33.53, -5.02], "zoom": 11},
            {"key": "afennourir", "label": _("Lake Afennourir"), "center": [33.28, -5.35], "zoom": 11},
            {"key": "bin-el-ouidane", "label": _("Bin el Ouidane"), "center": [32.11, -6.45], "zoom": 11},
        ],
        "algeria": [
            {"key": "oubeira", "label": _("Lake Oubeira"), "center": [36.86, 8.44], "zoom": 11},
            {"key": "fetzara", "label": _("Lake Fetzara"), "center": [36.82, 7.53], "zoom": 11},
            {"key": "melah", "label": _("Lake Mellah"), "center": [36.90, 8.33], "zoom": 11},
        ],
    }


def _dashboard_js_i18n():
    return {
        "map_centered_on": _("Map centered on __PLACE__."),
        "drawings_cleared": _("All drawings have been removed."),
        "select_mode": _("Selection mode: click a drawn area to see its details."),
        "draw_mode": _("Draw mode: trace a polygon to measure the area."),
        "measure_mode": _("Ruler mode: click two points on the map to measure distance."),
        "ping_mode": _("Ping mode: click a point for exact live metrics."),
        "ruler_cleared": _("Ruler measurement cleared."),
        "ping_no_live": _("Ping saved, but live metrics are unavailable for now."),
        "first_point_done": _("First point recorded. Click the second point."),
        "distance_line": _("Distance: __M__ m (__KM__ km)."),
        "polygon_line": _(
            "Area: __M2__ m² (__HA__ ha, __KM2__ km²) | Perimeter: __PM__ m | Center: __LAT__, __LNG__"
        ),
        "ping_line": _(
            "Ping: __LAT__, __LNG__ | Wind: __WS__ km/h | Temp: __T__°C | Humidity: __H__% | Rain: __R__ mm"
        ),
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

    return JsonResponse(
        {
            "wind_speed_kmh": round(wind_speed, 1),
            "wind_gust_kmh": round(wind_gust, 1),
            "wind_direction": _degree_to_compass(wind_deg),
            "rainfall_mm": round(precipitation, 1),
            "rainfall_delta_percent": 0,
            "temperature_c": round(temperature, 1),
            "humidity_percent": humidity,
            "source": "open-meteo",
        }
    )


def dashboard_view(request):
    _seed_reference_data()
    result = None
    form = RiskSimulationForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        region = form.cleaned_data["region"]
        year = form.cleaned_data["year"]
        crop = form.cleaned_data["crop"]
        irrigation = form.cleaned_data["irrigation"]
        risk_level, recommendation = _calculate_risk(crop.name, irrigation.name)
        result = {
            "risk_level": risk_level,
            "recommendation": recommendation,
        }
        RiskAssessment.objects.create(
            region=region,
            year=year,
            crop=crop,
            irrigation=irrigation,
            risk_level=risk_level,
            recommendation=recommendation,
        )
        snapshot = EnvironmentalSnapshot.objects.filter(region=region, year=year).first()
    else:
        default_region = Region.objects.get(name="Tunisia")
        default_year = ObservationYear.objects.get(label="2024 (Current)")
        snapshot = EnvironmentalSnapshot.objects.filter(
            region=default_region, year=default_year
        ).first()

    context = {
        "form": form,
        "result": result,
        "snapshot": snapshot,
        "region_map_config_json": json.dumps(_region_map_config()),
        "lakes_by_region_json": json.dumps(_lakes_by_region()),
        "dashboard_js_i18n_json": json.dumps(_dashboard_js_i18n()),
        "demo_risk_banner": {
            "level": _("High risk"),
            "body": _(
                "Current soil salinity levels in sector 4 are incompatible with durum wheat under drip irrigation. "
                "Consider switching to highly salt-tolerant crops or scheduling intensive leaching protocols before sowing."
            ),
        },
    }
    return render(request, "dashboard/dashboard.html", context)


# ============== METRICS MANAGEMENT VIEWS ==============

def data_ingestion(request):
    """Display data ingestion interface with drag-drop and manual entry options"""
    # Ensure reference data exists
    create_reference_data()
    
    context = {
        'regions': Region.objects.all(),
        'years': ObservationYear.objects.all(),
        'crops': CropType.objects.all(),
        'irrigation_methods': IrrigationMethod.objects.all(),
        'recent_imports': DataImportLog.objects.order_by('-import_date')[:5],
    }
    return render(request, 'dashboard/data_ingestion.html', context)


@require_http_methods(["POST"])
def api_submit_metrics(request):
    """API endpoint for manual data submission"""
    try:
        data = json.loads(request.body)
        metric_type = data.get('metric_type')
        
        # Get username
        username = request.user.username if request.user.is_authenticated else 'Anonymous'
        
        # Normalize common fields: accept names or ids
        # Region
        if data.get('region') and not data.get('region_id'):
            try:
                r = Region.objects.filter(name__iexact=data.get('region')).first()
                if r:
                    data['region_id'] = r.id
            except Exception:
                pass
        if data.get('region_id') and isinstance(data.get('region_id'), str) and data.get('region_id').isdigit():
            data['region_id'] = int(data['region_id'])

        # Year
        if data.get('year') and not data.get('year_id'):
            y = ObservationYear.objects.filter(label__iexact=data.get('year')).first()
            if y:
                data['year_id'] = y.id
        if data.get('year_id') and isinstance(data.get('year_id'), str) and data.get('year_id').isdigit():
            data['year_id'] = int(data['year_id'])

        # Crop
        if data.get('crop') and not data.get('crop_id'):
            c = CropType.objects.filter(name__iexact=data.get('crop')).first()
            if c:
                data['crop_id'] = c.id

        # Irrigation
        if data.get('irrigation') and not data.get('irrigation_id'):
            irr = IrrigationMethod.objects.filter(name__iexact=data.get('irrigation')).first()
            if irr:
                data['irrigation_id'] = irr.id

        # Timestamp alias
        if data.get('timestamp') and not data.get('measurement_date'):
            data['measurement_date'] = data.get('timestamp')

        # Create importer
        importer = DataImporter(source='Manual', username=username)

        # Submit the data
        result = importer.submit_form_data(metric_type, data)
        
        # Log the import
        import_log = importer.log_import(metric_type, notes=f'Manual entry via web form')
        action = getattr(importer, 'last_action', None)
        return JsonResponse({
            'success': True,
            'message': _('Data submitted successfully'),
            'records_imported': importer.imported_records,
            'log_id': import_log.id,
            'action': action,
        })
    
    except DataIngestionError as e:
        return JsonResponse({
            'success': False,
            'error': str(e),
        }, status=400)
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON format',
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Unexpected error: {str(e)}',
        }, status=500)


def parameter_review(request):
    """Display parameter review and manual entry interface with expandable categories"""
    context = {
        'regions': Region.objects.all(),
        'years': ObservationYear.objects.all(),
    }
    return render(request, 'dashboard/parameter_review.html', context)


def analysis_results(request):
    """Display analysis results and drought risk assessment"""
    context = {
        'regions': Region.objects.all(),
        'years': ObservationYear.objects.all(),
    }
    return render(request, 'dashboard/analysis.html', context)


def calculations_view(request):
    """Display a themed page listing calculated metrics and formulas."""
    # Prepare sections and sample values where possible
    latest_soil = SoilMetrics.objects.order_by('-measurement_date').first()
    latest_climate = ClimateMetrics.objects.order_by('-measurement_date').first()

    mean_temp = None
    if latest_climate and latest_climate.temperature_max_c is not None and latest_climate.temperature_min_c is not None:
        try:
            mean_temp = round((float(latest_climate.temperature_max_c) + float(latest_climate.temperature_min_c)) / 2.0, 2)
        except Exception:
            mean_temp = None

    awc_mm = None
    if latest_soil and latest_soil.field_capacity_percent is not None and latest_soil.wilting_point_percent is not None and latest_soil.root_zone_depth_mm:
        try:
            awc_mm = round(((float(latest_soil.field_capacity_percent) - float(latest_soil.wilting_point_percent)) / 100.0) * float(latest_soil.root_zone_depth_mm), 2)
        except Exception:
            awc_mm = None

    calc_sections = [
        {
            'category': 'Soil',
            'items': [
                {'name': 'Field Capacity (%)', 'formula': 'Pedotransfer function (Saxton & Rawls)', 'value': getattr(latest_soil, 'field_capacity_percent', '—') if latest_soil else '—'},
                {'name': 'Wilting Point (%)', 'formula': 'Pedotransfer function (Saxton & Rawls)', 'value': getattr(latest_soil, 'wilting_point_percent', '—') if latest_soil else '—'},
                {'name': 'Available Water Capacity (mm)', 'formula': '(FC - WP) ÷ 100 × Root Zone Depth', 'value': awc_mm or '—'},
            ]
        },
        {
            'category': 'Climate',
            'items': [
                {'name': 'Mean Temp (°C)', 'formula': '(Max + Min) ÷ 2', 'value': mean_temp or '—'},
                {'name': 'ET₀ (mm/day)', 'formula': 'Penman-Monteith FAO-56 from Temp/Humidity/Wind/Solar', 'value': '—'},
                {'name': 'ETc (mm/day)', 'formula': 'ET₀ × Kc (Kc from FAO-56 lookup)', 'value': '—'},
            ]
        },
        {
            'category': 'Drought Indices',
            'items': [
                {'name': 'SPI (1/3/12-month)', 'formula': 'Anomaly of precipitation ÷ historical std dev (30+ years)', 'value': '—'},
                {'name': 'SPEI (1/3/12-month)', 'formula': 'Water balance anomaly ÷ historical std dev', 'value': '—'},
                {'name': 'PDSI', 'formula': 'Palmer Drought Severity Index model (multi-variable)', 'value': '—'},
            ]
        },
    ]

    context = {
        'regions': Region.objects.all(),
        'years': ObservationYear.objects.all(),
        'calc_sections': calc_sections,
    }
    return render(request, 'dashboard/calculations.html', context)


def calculations_data(request):
    """Return sample time-series data for calculations charts (JSON).

    This endpoint returns simple arrays of dates and values for soil, climate and drought
    so the front-end can fetch realistic example series. If the DB has recent records
    this could be extended to return real time-series.
    """
    # Example time-series: last 7 days
    from datetime import datetime, timedelta

    today = datetime.utcnow().date()
    dates = [(today - timedelta(days=i)).isoformat() for i in reversed(range(7))]

    # Sample series (coherent example values)
    soil_awc = [100, 98, 96, 95, 94, 93, 92]
    climate_temp = [22.1, 22.5, 23.0, 24.2, 25.0, 24.7, 24.5]
    climate_et0 = [3.5, 3.8, 4.0, 4.1, 4.3, 4.0, 4.2]
    drought_spi1 = [-0.2, -0.3, -0.4, -0.6, -0.8, -0.9, -1.0]

    payload = {
        'dates': dates,
        'soil': {
            'labels': dates,
            'awc_mm': soil_awc,
        },
        'climate': {
            'labels': dates,
            'temperature_c': climate_temp,
            'et0_mm_day': climate_et0,
        },
        'drought': {
            'labels': dates,
            'spi1': drought_spi1,
        }
    }
    return JsonResponse(payload)


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


# ============== DATA ENTRY VIEWS ==============

def add_soil_metrics(request):
    """Add new soil metrics"""
    if request.method == 'POST':
        form = SoilMetricsForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, _('Soil metrics added successfully!'))
            return redirect('dashboard:soil_metrics')
    else:
        form = SoilMetricsForm()
    
    return render(request, 'dashboard/metrics_form.html', {'form': form, 'title': 'Add Soil Metrics'})


def add_climate_metrics(request):
    """Add new climate metrics"""
    if request.method == 'POST':
        form = ClimateMetricsForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, _('Climate metrics added successfully!'))
            return redirect('dashboard:climate_metrics')
    else:
        form = ClimateMetricsForm()
    
    return render(request, 'dashboard/metrics_form.html', {'form': form, 'title': 'Add Climate Metrics'})


def add_drought_indices(request):
    """Add new drought indices"""
    if request.method == 'POST':
        form = DroughtIndicesForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, _('Drought indices added successfully!'))
            return redirect('dashboard:drought_indices')
    else:
        form = DroughtIndicesForm()
    
    return render(request, 'dashboard/metrics_form.html', {'form': form, 'title': 'Add Drought Indices'})


def add_agricultural_metrics(request):
    """Add new agricultural metrics"""
    if request.method == 'POST':
        form = AgriculturalMetricsForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, _('Agricultural metrics added successfully!'))
            return redirect('dashboard:agricultural_metrics')
    else:
        form = AgriculturalMetricsForm()
    
    return render(request, 'dashboard/metrics_form.html', {'form': form, 'title': 'Add Agricultural Metrics'})


def add_remote_sensing_metrics(request):
    """Add new remote sensing metrics"""
    if request.method == 'POST':
        form = RemoteSensingMetricsForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, _('Remote sensing metrics added successfully!'))
            return redirect('dashboard:remote_sensing')
    else:
        form = RemoteSensingMetricsForm()
    
    return render(request, 'dashboard/metrics_form.html', {'form': form, 'title': 'Add Remote Sensing Metrics'})


def add_hydrology_metrics(request):
    """Add new hydrology metrics"""
    if request.method == 'POST':
        form = HydrologyMetricsForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, _('Hydrology metrics added successfully!'))
            return redirect('dashboard:hydrology_metrics')
    else:
        form = HydrologyMetricsForm()
    
    return render(request, 'dashboard/metrics_form.html', {'form': form, 'title': 'Add Hydrology Metrics'})


# ============== EXCEL IMPORT VIEWS ==============

def import_excel_metrics(request):
    """Import metrics from Excel file"""
    if request.method == 'POST':
        form = ExcelImportForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                excel_file = request.FILES['excel_file']
                metric_type = form.cleaned_data['metric_type']
                
                # Read Excel file
                df = pd.read_excel(excel_file)
                records_imported = 0
                errors = []
                
                # Process based on metric type
                result = None
                if metric_type == 'soil':
                    result = _import_soil_metrics(df, errors)
                elif metric_type == 'climate':
                    result = _import_climate_metrics(df, errors)
                elif metric_type == 'drought':
                    result = _import_drought_indices(df, errors)
                elif metric_type == 'agricultural':
                    result = _import_agricultural_metrics(df, errors)
                elif metric_type == 'remote_sensing':
                    result = _import_remote_sensing_metrics(df, errors)
                elif metric_type == 'hydrology':
                    result = _import_hydrology_metrics(df, errors)

                # Normalize result
                if isinstance(result, dict):
                    records_imported = result.get('count', 0)
                    created = result.get('created', 0)
                    updated = result.get('updated', 0)
                else:
                    records_imported = int(result or 0)
                    created = 0
                    updated = 0
                
                # Log the import
                status = 'Partial' if errors else 'Success'
                DataImportLog.objects.create(
                    source='Excel',
                    filename=excel_file.name,
                    metric_type=metric_type,
                    records_imported=records_imported,
                    status=status,
                    notes=(f"{len(errors)} errors" if errors else f"Created {created}, Updated {updated}")
                )

                messages.success(request, _('Excel import completed! {} records imported.'.format(records_imported)))
                if created or updated:
                    messages.info(request, _(f"Created: {created}, Updated: {updated}"))
                if errors:
                    messages.warning(request, _('Some records had errors: {}'.format(len(errors))))
                
                return redirect('dashboard:data_ingestion')
            except Exception as e:
                messages.error(request, _('Error importing Excel file: {}'.format(str(e))))
    else:
        form = ExcelImportForm()
    
    return render(request, 'dashboard/excel_import.html', {'form': form})


def _import_soil_metrics(df, errors):
    """Import soil metrics from DataFrame"""
    count = 0
    created = 0
    updated = 0
    for idx, row in df.iterrows():
        try:
            region = Region.objects.get(name=row.get('region', ''))
            year = ObservationYear.objects.get(label=row.get('year', ''))
            measurement_date = pd.to_datetime(row.get('measurement_date')).date() if pd.notna(row.get('measurement_date')) else None

            defaults = {
                'moisture_content_percent': float(row.get('moisture_content_percent')) if pd.notna(row.get('moisture_content_percent')) else None,
                'sand_ratio': float(row.get('sand_ratio')) if pd.notna(row.get('sand_ratio')) else None,
                'clay_ratio': float(row.get('clay_ratio')) if pd.notna(row.get('clay_ratio')) else None,
                'silt_ratio': float(row.get('silt_ratio')) if pd.notna(row.get('silt_ratio')) else None,
                'root_zone_depth_mm': int(row.get('root_zone_depth_mm')) if pd.notna(row.get('root_zone_depth_mm')) else None,
                'organic_matter_percent': float(row.get('organic_matter_percent')) if pd.notna(row.get('organic_matter_percent')) else None,
                'infiltration_rate_mmhr': float(row.get('infiltration_rate_mmhr')) if pd.notna(row.get('infiltration_rate_mmhr')) else None,
                'field_capacity_percent': float(row.get('field_capacity_percent')) if pd.notna(row.get('field_capacity_percent')) else None,
                'wilting_point_percent': float(row.get('wilting_point_percent')) if pd.notna(row.get('wilting_point_percent')) else None,
                'salinity_ece_dsm': float(row.get('salinity_ece_dsm')) if pd.notna(row.get('salinity_ece_dsm')) else None,
                'ph_level': float(row.get('ph_level')) if pd.notna(row.get('ph_level')) else None,
            }

            obj, created_flag = SoilMetrics.objects.update_or_create(
                region=region,
                year=year,
                measurement_date=measurement_date,
                defaults=defaults,
            )
            count += 1
            if created_flag:
                created += 1
            else:
                updated += 1
        except Exception as e:
            errors.append(f"Row {idx}: {str(e)}")

    return {'count': count, 'created': created, 'updated': updated}


def _import_climate_metrics(df, errors):
    """Import climate metrics from DataFrame"""
    count = 0
    created = 0
    updated = 0
    for idx, row in df.iterrows():
        try:
            region = Region.objects.get(name=row.get('region', ''))
            year = ObservationYear.objects.get(label=row.get('year', ''))
            measurement_date = pd.to_datetime(row.get('measurement_date')).date() if pd.notna(row.get('measurement_date')) else None

            defaults = {
                'rainfall_mm': float(row.get('rainfall_mm')) if pd.notna(row.get('rainfall_mm')) else None,
                'seasonal_rainfall_variability': row.get('seasonal_rainfall_variability', ''),
                'temperature_max_c': float(row.get('temperature_max_c')) if pd.notna(row.get('temperature_max_c')) else None,
                'temperature_min_c': float(row.get('temperature_min_c')) if pd.notna(row.get('temperature_min_c')) else None,
                'temperature_mean_c': float(row.get('temperature_mean_c')) if pd.notna(row.get('temperature_mean_c')) else None,
                'relative_humidity_percent': int(row.get('relative_humidity_percent')) if pd.notna(row.get('relative_humidity_percent')) else None,
                'wind_speed_ms': float(row.get('wind_speed_ms')) if pd.notna(row.get('wind_speed_ms')) else None,
                'solar_radiation_mjm2day': float(row.get('solar_radiation_mjm2day')) if pd.notna(row.get('solar_radiation_mjm2day')) else None,
                'evapotranspiration_et0_mmday': float(row.get('evapotranspiration_et0_mmday')) if pd.notna(row.get('evapotranspiration_et0_mmday')) else None,
                'evapotranspiration_etc_mmday': float(row.get('evapotranspiration_etc_mmday')) if pd.notna(row.get('evapotranspiration_etc_mmday')) else None,
            }

            obj, created_flag = ClimateMetrics.objects.update_or_create(
                region=region,
                year=year,
                measurement_date=measurement_date,
                defaults=defaults,
            )
            count += 1
            if created_flag:
                created += 1
            else:
                updated += 1
        except Exception as e:
            errors.append(f"Row {idx}: {str(e)}")

    return {'count': count, 'created': created, 'updated': updated}


def _import_drought_indices(df, errors):
    """Import drought indices from DataFrame"""
    count = 0
    created = 0
    updated = 0
    for idx, row in df.iterrows():
        try:
            region = Region.objects.get(name=row.get('region', ''))
            year = ObservationYear.objects.get(label=row.get('year', ''))
            measurement_date = pd.to_datetime(row.get('measurement_date')).date() if pd.notna(row.get('measurement_date')) else None

            defaults = {
                'spi_1month': float(row.get('spi_1month')) if pd.notna(row.get('spi_1month')) else None,
                'spi_3month': float(row.get('spi_3month')) if pd.notna(row.get('spi_3month')) else None,
                'spi_12month': float(row.get('spi_12month')) if pd.notna(row.get('spi_12month')) else None,
                'spei_1month': float(row.get('spei_1month')) if pd.notna(row.get('spei_1month')) else None,
                'spei_3month': float(row.get('spei_3month')) if pd.notna(row.get('spei_3month')) else None,
                'spei_12month': float(row.get('spei_12month')) if pd.notna(row.get('spei_12month')) else None,
                'pdsi_value': float(row.get('pdsi_value')) if pd.notna(row.get('pdsi_value')) else None,
                'drought_severity_class': row.get('drought_severity_class', 'None'),
            }

            obj, created_flag = DroughtIndices.objects.update_or_create(
                region=region,
                year=year,
                measurement_date=measurement_date,
                defaults=defaults,
            )
            count += 1
            if created_flag:
                created += 1
            else:
                updated += 1
        except Exception as e:
            errors.append(f"Row {idx}: {str(e)}")

    return {'count': count, 'created': created, 'updated': updated}


def _import_agricultural_metrics(df, errors):
    """Import agricultural metrics from DataFrame"""
    count = 0
    created = 0
    updated = 0
    for idx, row in df.iterrows():
        try:
            region = Region.objects.get(name=row.get('region', ''))
            year = ObservationYear.objects.get(label=row.get('year', ''))
            crop = CropType.objects.get(name=row.get('crop', ''))
            irrigation = None
            if pd.notna(row.get('irrigation_method')):
                try:
                    irrigation = IrrigationMethod.objects.get(name=row.get('irrigation_method'))
                except Exception:
                    irrigation = None

            measurement_date = pd.to_datetime(row.get('measurement_date')).date() if pd.notna(row.get('measurement_date')) else None

            defaults = {
                'growth_stage': row.get('growth_stage', 'Vegetative'),
                'crop_coefficient_kc': float(row.get('crop_coefficient_kc')) if pd.notna(row.get('crop_coefficient_kc')) else None,
                'crop_water_requirement_mmday': float(row.get('crop_water_requirement_mmday')) if pd.notna(row.get('crop_water_requirement_mmday')) else None,
                'yield_reduction_factor': float(row.get('yield_reduction_factor')) if pd.notna(row.get('yield_reduction_factor')) else None,
                'irrigation_method': irrigation,
                'irrigation_efficiency_percent': int(row.get('irrigation_efficiency_percent')) if pd.notna(row.get('irrigation_efficiency_percent')) else None,
                'water_applied_mm': float(row.get('water_applied_mm')) if pd.notna(row.get('water_applied_mm')) else None,
                'leaf_temperature_c': float(row.get('leaf_temperature_c')) if pd.notna(row.get('leaf_temperature_c')) else None,
                'stomatal_conductance': float(row.get('stomatal_conductance')) if pd.notna(row.get('stomatal_conductance')) else None,
            }

            obj, created_flag = AgriculturalMetrics.objects.update_or_create(
                region=region,
                year=year,
                crop=crop,
                measurement_date=measurement_date,
                defaults=defaults,
            )
            count += 1
            if created_flag:
                created += 1
            else:
                updated += 1
        except Exception as e:
            errors.append(f"Row {idx}: {str(e)}")

    return {'count': count, 'created': created, 'updated': updated}


def _import_remote_sensing_metrics(df, errors):
    """Import remote sensing metrics from DataFrame"""
    count = 0
    created = 0
    updated = 0
    for idx, row in df.iterrows():
        try:
            region = Region.objects.get(name=row.get('region', ''))
            year = ObservationYear.objects.get(label=row.get('year', ''))
            measurement_date = pd.to_datetime(row.get('measurement_date')).date() if pd.notna(row.get('measurement_date')) else None

            defaults = {
                'ndvi': float(row.get('ndvi')) if pd.notna(row.get('ndvi')) else None,
                'ndwi': float(row.get('ndwi')) if pd.notna(row.get('ndwi')) else None,
                'land_surface_temperature_c': float(row.get('land_surface_temperature_c')) if pd.notna(row.get('land_surface_temperature_c')) else None,
                'satellite_soil_moisture_percent': float(row.get('satellite_soil_moisture_percent')) if pd.notna(row.get('satellite_soil_moisture_percent')) else None,
                'satellite_source': row.get('satellite_source', ''),
                'vegetation_condition_index': float(row.get('vegetation_condition_index')) if pd.notna(row.get('vegetation_condition_index')) else None,
                'evapotranspiration_sebal_mmday': float(row.get('evapotranspiration_sebal_mmday')) if pd.notna(row.get('evapotranspiration_sebal_mmday')) else None,
            }

            obj, created_flag = RemoteSensingMetrics.objects.update_or_create(
                region=region,
                year=year,
                measurement_date=measurement_date,
                defaults=defaults,
            )
            count += 1
            if created_flag:
                created += 1
            else:
                updated += 1
        except Exception as e:
            errors.append(f"Row {idx}: {str(e)}")

    return {'count': count, 'created': created, 'updated': updated}


def _import_hydrology_metrics(df, errors):
    """Import hydrology metrics from DataFrame"""
    count = 0
    created = 0
    updated = 0
    for idx, row in df.iterrows():
        try:
            region = Region.objects.get(name=row.get('region', ''))
            year = ObservationYear.objects.get(label=row.get('year', ''))
            measurement_date = pd.to_datetime(row.get('measurement_date')).date() if pd.notna(row.get('measurement_date')) else None

            defaults = {
                'precipitation_mm': float(row.get('precipitation_mm')) if pd.notna(row.get('precipitation_mm')) else None,
                'evapotranspiration_mm': float(row.get('evapotranspiration_mm')) if pd.notna(row.get('evapotranspiration_mm')) else None,
                'groundwater_depth_m': float(row.get('groundwater_depth_m')) if pd.notna(row.get('groundwater_depth_m')) else None,
                'runoff_mm': float(row.get('runoff_mm')) if pd.notna(row.get('runoff_mm')) else None,
                'river_flow_m3s': float(row.get('river_flow_m3s')) if pd.notna(row.get('river_flow_m3s')) else None,
                'reservoir_storage_m3': int(row.get('reservoir_storage_m3')) if pd.notna(row.get('reservoir_storage_m3')) else None,
                'irrigation_supply_available_m3': int(row.get('irrigation_supply_available_m3')) if pd.notna(row.get('irrigation_supply_available_m3')) else None,
                'soil_water_deficit_index_mm': float(row.get('soil_water_deficit_index_mm')) if pd.notna(row.get('soil_water_deficit_index_mm')) else None,
                'water_balance_percent': float(row.get('water_balance_percent')) if pd.notna(row.get('water_balance_percent')) else None,
            }

            obj, created_flag = HydrologyMetrics.objects.update_or_create(
                region=region,
                year=year,
                measurement_date=measurement_date,
                defaults=defaults,
            )
            count += 1
            if created_flag:
                created += 1
            else:
                updated += 1
        except Exception as e:
            errors.append(f"Row {idx}: {str(e)}")

    return {'count': count, 'created': created, 'updated': updated}


def export_metrics_excel(request, metric_type):
    """Export metrics to Excel file"""
    
    # Fetch metrics based on type
    if metric_type == 'soil':
        queryset = SoilMetrics.objects.all().values()
    elif metric_type == 'climate':
        queryset = ClimateMetrics.objects.all().values()
    elif metric_type == 'drought':
        queryset = DroughtIndices.objects.all().values()
    elif metric_type == 'agricultural':
        queryset = AgriculturalMetrics.objects.all().values()
    elif metric_type == 'remote_sensing':
        queryset = RemoteSensingMetrics.objects.all().values()
    elif metric_type == 'hydrology':
        queryset = HydrologyMetrics.objects.all().values()
    else:
        return HttpResponse('Invalid metric type', status=400)
    
    # Convert to DataFrame and export to Excel
    df = pd.DataFrame(list(queryset))
    
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name=metric_type, index=False)
    
    output.seek(0)
    response = HttpResponse(
        output.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="metrics_{metric_type}_{pd.Timestamp.now().strftime("%Y%m%d")}.xlsx"'
    
    return response


def import_logs_view(request):
    """View import history logs"""
    logs = DataImportLog.objects.order_by('-import_date')
    
    context = {
        'logs': logs,
        'total_records': sum(log.records_imported for log in logs),
        'success_count': logs.filter(status='Success').count(),
        'failed_count': logs.filter(status='Failed').count(),
    }
    
    return render(request, 'dashboard/import_logs.html', context)


def historical_view(request):
    """Display historical comparison and climate trends"""
    context = {
        'regions': Region.objects.all(),
        'years': ObservationYear.objects.all(),
        'title': _('Historical Comparison'),
    }
    return render(request, 'dashboard/historical.html', context)


def login_view(request):
    """Display login page"""
    return render(request, 'dashboard/login.html')


@require_http_methods(["GET"])
def drought_prediction_api(request):
    """Return the latest drought prediction or generate a fresh one on demand."""
    region_id = request.GET.get('region_id')
    year_id = request.GET.get('year_id')
    refresh = request.GET.get('refresh', '0').lower() in {'1', 'true', 'yes', 'on'}
    use_llm = request.GET.get('use_llm', '0').lower() in {'1', 'true', 'yes', 'on'}

    region = None
    year = None
    if region_id:
        region = get_object_or_404(Region, pk=region_id)
    else:
        region = Region.objects.order_by('name').first()
    if year_id:
        year = get_object_or_404(ObservationYear, pk=year_id)
    else:
        year = ObservationYear.objects.order_by('-label').first()

    if region is None or year is None:
        return JsonResponse({'success': False, 'error': 'Region and year are required.'}, status=400)

    latest_prediction = DroughtPrediction.objects.filter(region=region, year=year).order_by('-generated_at').first()
    if latest_prediction and not refresh:
        return JsonResponse({
            'success': True,
            'source': 'database',
            'prediction': {
                'region': region.name,
                'year': year.label,
                'generated_at': latest_prediction.generated_at,
                'risk_scores': {
                    'today': float(latest_prediction.current_risk_score),
                    'day_7': float(latest_prediction.risk_7day),
                    'day_30': float(latest_prediction.risk_30day),
                },
                'current': {
                    'soil_moisture_pct': float(latest_prediction.soil_moisture_today_pct or 0),
                },
                'forecasts': {
                    'soil_moisture_7day_pct': float(latest_prediction.soil_moisture_7day_pct or 0),
                    'soil_moisture_30day_pct': float(latest_prediction.soil_moisture_30day_pct or 0),
                },
                'drivers': latest_prediction.drivers,
                'llm_explanation': latest_prediction.explanation,
            },
        })

    try:
        from .prediction_engine.pipeline import DroughtPredictionPipeline

        pipeline = DroughtPredictionPipeline()
        result = pipeline.predict_for_region(region, year, use_llm=use_llm)
        saved_prediction = pipeline.save_prediction(region, year, result)

        return JsonResponse({
            'success': True,
            'source': 'generated',
            'prediction_id': saved_prediction.id,
            'prediction': {
                'region': region.name,
                'year': year.label,
                'generated_at': saved_prediction.generated_at,
                'risk_scores': result['risk_scores'],
                'current': result['current'],
                'forecasts': result['forecasts'],
                'drivers': result['drivers'],
                'llm_explanation': result['llm_explanation'],
            },
        })
    except Exception as exc:
        if latest_prediction is not None:
            return JsonResponse({
                'success': True,
                'source': 'database',
                'warning': str(exc),
                'prediction': {
                    'region': region.name,
                    'year': year.label,
                    'generated_at': latest_prediction.generated_at,
                    'risk_scores': {
                        'today': float(latest_prediction.current_risk_score),
                        'day_7': float(latest_prediction.risk_7day),
                        'day_30': float(latest_prediction.risk_30day),
                    },
                    'current': {
                        'soil_moisture_pct': float(latest_prediction.soil_moisture_today_pct or 0),
                    },
                    'forecasts': {
                        'soil_moisture_7day_pct': float(latest_prediction.soil_moisture_7day_pct or 0),
                        'soil_moisture_30day_pct': float(latest_prediction.soil_moisture_30day_pct or 0),
                    },
                    'drivers': latest_prediction.drivers,
                    'llm_explanation': latest_prediction.explanation,
                },
            })
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


@require_http_methods(["POST"])
def ajax_upload_file(request):
    """AJAX endpoint for drag-and-drop file upload — saves to PostgreSQL"""
    try:
        uploaded_file = request.FILES.get('file')
        metric_type = request.POST.get('metric_type', '')

        if not uploaded_file:
            return JsonResponse({'success': False, 'error': 'No file provided'}, status=400)

        if not metric_type:
            return JsonResponse({'success': False, 'error': 'Please select a metric type'}, status=400)

        filename = uploaded_file.name.lower()

        # Read into DataFrame
        if filename.endswith('.csv'):
            df = pd.read_csv(uploaded_file)
        elif filename.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(uploaded_file)
        else:
            return JsonResponse({
                'success': False,
                'error': 'Unsupported file format. Use .csv, .xlsx, or .xls'
            }, status=400)

        if df.empty:
            return JsonResponse({'success': False, 'error': 'The uploaded file contains no data'}, status=400)

        records_imported = 0
        errors = []
        created = 0
        updated = 0

        # Use existing import functions
        result = None
        if metric_type == 'soil':
            result = _import_soil_metrics(df, errors)
        elif metric_type == 'climate':
            result = _import_climate_metrics(df, errors)
        elif metric_type == 'drought':
            result = _import_drought_indices(df, errors)
        elif metric_type == 'agricultural':
            result = _import_agricultural_metrics(df, errors)
        elif metric_type == 'remote_sensing':
            result = _import_remote_sensing_metrics(df, errors)
        elif metric_type == 'hydrology':
            result = _import_hydrology_metrics(df, errors)
        else:
            return JsonResponse({'success': False, 'error': f'Unknown metric type: {metric_type}'}, status=400)

        # Normalize result which may be a dict with counts
        if isinstance(result, dict):
            records_imported = result.get('count', 0)
            created = result.get('created', 0)
            updated = result.get('updated', 0)
        else:
            # backward compatibility: integer
            records_imported = int(result or 0)

        # Log the import
        status = 'Failed' if records_imported == 0 and errors else ('Partial' if errors else 'Success')
        username = request.user.username if request.user.is_authenticated else 'Anonymous'

        DataImportLog.objects.create(
            source='Excel',
            filename=uploaded_file.name,
            metric_type=metric_type,
            records_imported=records_imported,
            imported_by=username,
            status=status,
            notes=f"{len(errors)} errors" if errors else "No errors",
            error_details=json.dumps(errors[:20]) if errors else None,
        )

        return JsonResponse({
            'success': True,
            'message': f'Import complete: {records_imported} records saved',
            'records_imported': records_imported,
            'total_rows': len(df),
            'error_count': len(errors),
            'errors': errors[:5],  # Return first 5 errors for display
            'created': created,
            'updated': updated,
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Upload failed: {str(e)}'
        }, status=500)
