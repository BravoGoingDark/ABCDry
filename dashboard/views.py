import json
from urllib.error import URLError
from urllib.request import urlopen

from django.http import JsonResponse
from django.shortcuts import render
from django.utils.translation import gettext as _

from .forms import RiskSimulationForm
from .models import (
    CropType,
    EnvironmentalSnapshot,
    IrrigationMethod,
    ObservationYear,
    Region,
    RiskAssessment,
)


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
