import math
import datetime
from decimal import Decimal
from django.conf import settings
from django.contrib import messages
from django.db.models import Avg
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from ..forms import (
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
    SoilMetrics,
    ClimateMetrics,
    DroughtIndices,
    AgriculturalMetrics,
    RemoteSensingMetrics,
    HydrologyMetrics,
)


# ============== MODEL & METRICS REGISTRY ==============

MODEL_MAP = {
    'SoilMetrics': SoilMetrics,
    'ClimateMetrics': ClimateMetrics,
    'DroughtIndices': DroughtIndices,
    'RemoteSensingMetrics': RemoteSensingMetrics,
    'HydrologyMetrics': HydrologyMetrics,
    'AgriculturalMetrics': AgriculturalMetrics,
}

# METRICS_REGISTRY: (key, model_name, field_name, label, unit, category)
METRICS_REGISTRY = [
    # Soil Metrics
    ('soil_moisture', 'SoilMetrics', 'moisture_content_percent', _('Soil Moisture'), '%', _('Soil')),
    ('soil_sand', 'SoilMetrics', 'sand_ratio', _('Sand Ratio'), '%', _('Soil')),
    ('soil_clay', 'SoilMetrics', 'clay_ratio', _('Clay Ratio'), '%', _('Soil')),
    ('soil_silt', 'SoilMetrics', 'silt_ratio', _('Silt Ratio'), '%', _('Soil')),
    ('soil_root_zone', 'SoilMetrics', 'root_zone_depth_mm', _('Root Zone Depth'), 'mm', _('Soil')),
    ('soil_organic', 'SoilMetrics', 'organic_matter_percent', _('Organic Matter'), '%', _('Soil')),
    ('soil_infiltration', 'SoilMetrics', 'infiltration_rate_mmhr', _('Infiltration Rate'), 'mm/hr', _('Soil')),
    ('soil_fc', 'SoilMetrics', 'field_capacity_percent', _('Field Capacity'), '%', _('Soil')),
    ('soil_wp', 'SoilMetrics', 'wilting_point_percent', _('Wilting Point'), '%', _('Soil')),
    ('soil_salinity', 'SoilMetrics', 'salinity_ece_dsm', _('Salinity'), 'dS/m', _('Soil')),
    ('soil_ph', 'SoilMetrics', 'ph_level', _('pH Level'), '', _('Soil')),
    
    # Climate Metrics
    ('climate_rainfall', 'ClimateMetrics', 'rainfall_mm', _('Rainfall'), 'mm', _('Climate')),
    ('climate_temp_max', 'ClimateMetrics', 'temperature_max_c', _('Max Temperature'), '°C', _('Climate')),
    ('climate_temp_min', 'ClimateMetrics', 'temperature_min_c', _('Min Temperature'), '°C', _('Climate')),
    ('climate_temp_mean', 'ClimateMetrics', 'temperature_mean_c', _('Mean Temperature'), '°C', _('Climate')),
    ('climate_humidity', 'ClimateMetrics', 'relative_humidity_percent', _('Relative Humidity'), '%', _('Climate')),
    ('climate_wind', 'ClimateMetrics', 'wind_speed_ms', _('Wind Speed'), 'm/s', _('Climate')),
    ('climate_solar', 'ClimateMetrics', 'solar_radiation_mjm2day', _('Solar Radiation'), 'MJ/m²/day', _('Climate')),
    ('climate_et0', 'ClimateMetrics', 'evapotranspiration_et0_mmday', _('Reference ET (ET0)'), 'mm/day', _('Climate')),
    ('climate_etc', 'ClimateMetrics', 'evapotranspiration_etc_mmday', _('Crop ET (ETc)'), 'mm/day', _('Climate')),
    
    # Drought Indices
    ('drought_spi_1m', 'DroughtIndices', 'spi_1month', _('SPI 1-Month'), '', _('Drought')),
    ('drought_spi_3m', 'DroughtIndices', 'spi_3month', _('SPI 3-Month'), '', _('Drought')),
    ('drought_spi_12m', 'DroughtIndices', 'spi_12month', _('SPI 12-Month'), '', _('Drought')),
    ('drought_spei_1m', 'DroughtIndices', 'spei_1month', _('SPEI 1-Month'), '', _('Drought')),
    ('drought_spei_3m', 'DroughtIndices', 'spei_3month', _('SPEI 3-Month'), '', _('Drought')),
    ('drought_spei_12m', 'DroughtIndices', 'spei_12month', _('SPEI 12-Month'), '', _('Drought')),
    ('drought_pdsi', 'DroughtIndices', 'pdsi_value', _('PDSI'), '', _('Drought')),
    
    # Agricultural Metrics
    ('agri_growth_stage', 'AgriculturalMetrics', 'growth_stage', _('Growth Stage'), '', _('Agriculture')),
    ('agri_kc', 'AgriculturalMetrics', 'crop_coefficient_kc', _('Crop Coefficient (Kc)'), '', _('Agriculture')),
    ('agri_water_req', 'AgriculturalMetrics', 'crop_water_requirement_mmday', _('Water Requirement'), 'mm/day', _('Agriculture')),
    ('agri_yield_reduction', 'AgriculturalMetrics', 'yield_reduction_factor', _('Yield Reduction Factor'), '', _('Agriculture')),
    ('agri_irr_efficiency', 'AgriculturalMetrics', 'irrigation_efficiency_percent', _('Irrigation Efficiency'), '%', _('Agriculture')),
    ('agri_water_applied', 'AgriculturalMetrics', 'water_applied_mm', _('Water Applied'), 'mm', _('Agriculture')),
    ('agri_leaf_temp', 'AgriculturalMetrics', 'leaf_temperature_c', _('Leaf Temperature'), '°C', _('Agriculture')),
    ('agri_stomatal', 'AgriculturalMetrics', 'stomatal_conductance', _('Stomatal Conductance'), '', _('Agriculture')),
    
    # Remote Sensing Metrics
    ('rs_ndvi', 'RemoteSensingMetrics', 'ndvi', _('NDVI'), '', _('Remote Sensing')),
    ('rs_ndwi', 'RemoteSensingMetrics', 'ndwi', _('NDWI'), '', _('Remote Sensing')),
    ('rs_lst', 'RemoteSensingMetrics', 'land_surface_temperature_c', _('Land Surface Temperature'), '°C', _('Remote Sensing')),
    ('rs_soil_moisture', 'RemoteSensingMetrics', 'satellite_soil_moisture_percent', _('Soil Moisture (Satellite)'), '%', _('Remote Sensing')),
    ('rs_vci', 'RemoteSensingMetrics', 'vegetation_condition_index', _('Vegetation Condition Index'), '', _('Remote Sensing')),
    ('rs_sebal_et', 'RemoteSensingMetrics', 'evapotranspiration_sebal_mmday', _('ET (SEBAL)'), 'mm/day', _('Remote Sensing')),
    
    # Hydrology Metrics
    ('hydro_precipitation', 'HydrologyMetrics', 'precipitation_mm', _('Precipitation'), 'mm', _('Hydrology')),
    ('hydro_et', 'HydrologyMetrics', 'evapotranspiration_mm', _('Evapotranspiration'), 'mm', _('Hydrology')),
    ('hydro_gw_depth', 'HydrologyMetrics', 'groundwater_depth_m', _('Groundwater Depth'), 'm', _('Hydrology')),
    ('hydro_runoff', 'HydrologyMetrics', 'runoff_mm', _('Runoff'), 'mm', _('Hydrology')),
    ('hydro_river_flow', 'HydrologyMetrics', 'river_flow_m3s', _('River Flow'), 'm³/s', _('Hydrology')),
    ('hydro_reservoir', 'HydrologyMetrics', 'reservoir_storage_m3', _('Reservoir Storage'), 'm³', _('Hydrology')),
    ('hydro_irr_supply', 'HydrologyMetrics', 'irrigation_supply_available_m3', _('Irrigation Supply'), 'm³', _('Hydrology')),
    ('hydro_soil_deficit', 'HydrologyMetrics', 'soil_water_deficit_index_mm', _('Soil Water Deficit'), 'mm', _('Hydrology')),
    ('hydro_water_balance', 'HydrologyMetrics', 'water_balance_percent', _('Water Balance'), '%', _('Hydrology')),
]

TEMPLATE_COLUMNS = {
    'soil': [
        'region', 'year', 'measurement_date', 'latitude', 'longitude', 'subregion',
        'moisture_content_percent',
        'sand_ratio',
        'clay_ratio',
        'silt_ratio',
        'root_zone_depth_mm',
        'organic_matter_percent',
        'infiltration_rate_mmhr',
        'field_capacity_percent',
        'wilting_point_percent',
        'salinity_ece_dsm',
        'ph_level',
    ],
    'climate': [
        'region', 'year', 'measurement_date', 'latitude', 'longitude', 'subregion',
        'rainfall_mm',
        'rainfall_source',
        'seasonal_rainfall_variability',
        'temperature_max_c',
        'temperature_min_c',
        'temperature_mean_c',
        'relative_humidity_percent',
        'wind_speed_ms',
        'solar_radiation_mjm2day',
        'evapotranspiration_et0_mmday',
        'evapotranspiration_etc_mmday',
    ],
    'drought': [
        'region', 'year', 'measurement_date', 'latitude', 'longitude', 'subregion',
        'spi_1month',
        'spi_3month',
        'spi_12month',
        'spei_1month',
        'spei_3month',
        'spei_12month',
        'pdsi_value',
        'drought_severity_class',
    ],
    'agricultural': [
        'region', 'year', 'measurement_date', 'crop', 'latitude', 'longitude', 'subregion',
        'growth_stage',
        'crop_coefficient_kc',
        'crop_water_requirement_mmday',
        'yield_reduction_factor',
        'irrigation_method',
        'irrigation_efficiency_percent',
        'water_applied_mm',
        'leaf_temperature_c',
        'stomatal_conductance',
    ],
    'remote_sensing': [
        'region', 'year', 'measurement_date', 'latitude', 'longitude', 'subregion',
        'ndvi',
        'ndwi',
        'land_surface_temperature_c',
        'satellite_soil_moisture_percent',
        'satellite_source',
        'vegetation_condition_index',
        'evapotranspiration_sebal_mmday',
    ],
    'hydrology': [
        'region', 'year', 'measurement_date', 'latitude', 'longitude', 'subregion',
        'precipitation_mm',
        'evapotranspiration_mm',
        'groundwater_depth_m',
        'runoff_mm',
        'river_flow_m3s',
        'reservoir_storage_m3',
        'irrigation_supply_available_m3',
        'soil_water_deficit_index_mm',
        'water_balance_percent',
    ],
}


# ============== METRIC BROWSER ==============

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


# ============== REFERENCE DATA SEEDING ==============

def _seed_reference_data():
    """Seed reference data regions, crops, irrigation methods, and observation years."""
    from django.contrib.auth.models import User
    from django.db.models import Q

    # Seed reference regions
    for region_name in ["Tunisia", "Morocco", "Algeria", "Bizerte"]:
        Region.objects.get_or_create(name=region_name)

    # Seed reference crops
    for crop_name in ["Blé (Durum)", "Olives", "Tomates", "Orge"]:
        CropType.objects.get_or_create(name=crop_name)

    # Seed reference irrigation methods
    for irr_name in [
        "Irrigation au goutte-à-goutte",
        "Asperseurs",
        "Alimenté par la pluie",
    ]:
        IrrigationMethod.objects.get_or_create(name=irr_name)

    # Seed observation years
    for year_label in ["2026", "2025", "2024", "2023", "2022", "2020 - 2024", "2015 - 2019"]:
        ObservationYear.objects.get_or_create(label=year_label)

    # Ensure admin user has a profile
    User.objects.get_or_create(username='admin', defaults={'is_staff': True, 'is_superuser': True})


# ============== RBAC HELPERS ==============

def _is_admin_user(user):
    """Check if user is a superadmin."""
    profile = getattr(user, 'profile', None)
    if profile:
        return profile.role == "superadmin"
    return False


def _is_subadmin_user(user):
    """Check if user is a subadmin."""
    profile = getattr(user, 'profile', None)
    if profile:
        return profile.role == "subadmin"
    return False


def _is_viewer_user(user):
    """Check if user is a viewer."""
    profile = getattr(user, 'profile', None)
    if profile:
        return profile.role == "viewer"
    return False


def _deny_admin_access(request):
    """Helper to return an error response for non-admin users."""
    messages.error(request, _("You do not have permission to access the admin panel."))
    return redirect(reverse('dashboard:home'))


def _deny_data_access(request):
    """Redirect users without data mutation permission."""
    messages.error(request, _('You do not have permission to modify data.'))
    return redirect('dashboard:dashboard')


def _user_can_access_region(user, region_id):
    """Check if a subadmin can access the given region."""
    if _is_admin_user(user):
        return True
    if _is_subadmin_user(user):
        return str(user.profile.region_id) == str(region_id)
    return False


def _check_data_permission(request, region_id=None):
    """Check if user can mutate data.
    - Viewer: always denied
    - Subadmin: allowed only if region_id matches their assigned region
    - Superadmin: always allowed
    """
    if not request.user.is_authenticated:
        return False
    profile = getattr(request.user, 'profile', None)
    if not profile:
        return False
    if profile.is_viewer():
        return False
    if profile.is_superadmin():
        return True
    if profile.is_subadmin():
        if region_id is not None:
            return str(profile.region_id) == str(region_id)
        return True
    return False


# ============== COORDINATE VALIDATION ==============

def _haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate distance in km between two lat/lng pairs (Haversine formula)."""
    R = 6371
    dlat = math.radians(float(lat2) - float(lat1))
    dlon = math.radians(float(lon2) - float(lon1))
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(float(lat1))) * math.cos(math.radians(float(lat2))) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _validate_coordinates_for_region(region, latitude, longitude):
    """Check if lat/lng falls within the region's radius from its center.
    Returns (is_valid: bool, error_message: str or None).
    """
    if not region.latitude or not region.longitude:
        return True, None
    if latitude is None or longitude is None:
        return False, _('Latitude and longitude are required.')
    try:
        lat = float(latitude)
        lng = float(longitude)
    except (TypeError, ValueError):
        return False, _('Invalid latitude or longitude values.')
    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        return False, _('Latitude must be between -90 and 90, longitude between -180 and 180.')
    distance = _haversine_distance(region.latitude, region.longitude, lat, lng)
    radius = float(region.radius_km) if region.radius_km else 100.0
    if distance > radius:
        return False, _('Coordinates are {:.0f} km from the center of {}, which exceeds the {:.0f} km limit.').format(distance, region.name, radius)
    return True, None


# ============== METRIC BROWSER HELPERS ==============

def _metric_browser_value(value):
    if value is None or value == "":
        return "\u2014"
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _build_browser_row(obj):
    values = []
    search_bits = []
    latitude = getattr(obj, "latitude", None)
    longitude = getattr(obj, "longitude", None)
    point_key = ""
    if latitude is not None and longitude is not None:
        try:
            point_key = f"{float(latitude):.6f},{float(longitude):.6f}"
        except (TypeError, ValueError):
            point_key = f"{latitude},{longitude}"

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
            "point_key": point_key,
        },
    }


def _build_browser_section(key, config):
    total_count = config["model"].objects.count()
    queryset = config["model"].objects.select_related(*config["select_related"]).order_by("-id")[:25]
    rows = [_build_browser_row(obj) for obj in queryset]
    return {
        "key": key,
        "title": config["title"],
        "model_name": config["model"].__name__,
        "headers": [field.verbose_name.title() for field in config["model"]._meta.fields],
        "rows": rows,
        "count": total_count,
        "display_count": len(rows),
        "add_url": reverse(config["add_url"]),
        "export_url": reverse("dashboard:export_metrics", args=[config["export_type"]]),
    }


# ============== RISK CALCULATION ==============
# Drought severity is read from the MEASURED SPEI-3 (DroughtIndices). Crop and
# irrigation method only rescale that severity - they never invent it. With no
# recent reading the result is explicitly "Unknown": a missing or stale reading
# must never be reported as low risk.
#
# Readings refresh monthly, so up to ~2 months old is normal. Anything older
# than this and the region is effectively unassessed, not fine.
SPEI_STALE_AFTER_DAYS = 75

# How exposed a crop is to the same regional drought, as a multiplier on the
# SPEI-derived score. Coarse agronomic heuristics, not measurements: the point
# is only that one regional drought is not equally damaging for every crop.
# Deep-rooted perennials buffer a dry spell far better than shallow-rooted
# crops at their most sensitive growth stage.
_CROP_SENSITIVITY = (
    (("blé", "ble", "durum", "wheat"), 1.25),
    (("maïs", "mais", "corn", "riz", "rice"), 1.20),
    (("pomme de terre", "potato", "tomate", "tomato"), 1.20),
    (("orge", "barley", "avocat", "avocado"), 1.00),
    (("olive", "oliv", "palmier", "date", "amande", "almond", "figuier"), 0.80),
)

# How well the irrigation method buffers the crop, as a score adjustment.
# Typical field application efficiency: drip ~90-95%, sprinkler/pivot ~65-85%,
# gravity/flooded ~45-60%. A poorly buffered crop suffers more from one SPEI.
_IRRIGATION_BUFFER = (
    (("goutte", "drip"), -5),
    (("gravitaire", "flood", "submersion", "ruissellement"), 5),
)


def _crop_sensitivity(crop_name):
    lowered = (crop_name or "").lower()
    for tokens, factor in _CROP_SENSITIVITY:
        if any(token in lowered for token in tokens):
            return factor
    return 1.0


def _irrigation_buffer(irrigation_name):
    lowered = (irrigation_name or "").lower()
    for tokens, delta in _IRRIGATION_BUFFER:
        if any(token in lowered for token in tokens):
            return delta
    return 0


def assess_drought_risk(region, crop_name, irrigation_name, as_of=None):
    """Drought exposure for a crop in a region under a given irrigation method.

    Severity comes from the newest measured SPEI-3 for the region; crop and
    irrigation only rescale it. Returns a dict so callers can surface the SPEI,
    the score, the reading date, and whether that reading is still current.
    """
    from ..services.assistant_brain import _level_from_score, _score_from_spei, _spei_level

    as_of = as_of or timezone.now().date()
    result = {
        "spei": None,
        "score": None,
        "level": None,
        # Presentation band: low | moderate | high | unknown. Templates must use
        # this rather than substring-matching the level name, so that "Extreme"
        # can never fall through to a reassuring colour.
        "band": "unknown",
        "measured_on": None,
        "days_old": None,
        "stale": True,
        "assessed": False,
        "crop_sensitivity": _crop_sensitivity(crop_name),
        "irrigation_buffer": _irrigation_buffer(irrigation_name),
        "risk_level": _("Unknown"),
        "recommendation": "",
    }

    if region is None:
        result["recommendation"] = _(
            "No region was selected, so no drought assessment can be made."
        )
        return result

    reading = (
        DroughtIndices.objects.filter(region=region)
        .exclude(spei_3month=None)
        .order_by("-measurement_date")
        .first()
    )
    if reading is None:
        result["recommendation"] = _(
            "No SPEI-3 reading exists for this region, so the drought risk cannot be "
            "determined. Run the drought-index import before assessing risk."
        )
        return result

    spei = float(reading.spei_3month)
    # measurement_date is declared a DateField but the column is a timestamp,
    # so the value can come back as a datetime. Normalise before arithmetic.
    measured_on = reading.measurement_date
    if isinstance(measured_on, datetime.datetime):
        measured_on = (timezone.localtime(measured_on) if timezone.is_aware(measured_on)
                       else measured_on).date()
    days_old = (as_of - measured_on).days

    score = _score_from_spei(spei) or 0
    score = score * result["crop_sensitivity"] + result["irrigation_buffer"]
    score = int(round(max(0, min(100, score))))
    level = _level_from_score(score)

    result.update({
        "spei": round(spei, 2),
        "score": score,
        "level": level,
        "measured_on": measured_on,
        "days_old": days_old,
        "stale": days_old > SPEI_STALE_AFTER_DAYS,
    })

    if result["stale"]:
        months = max(1, round(days_old / 30.44))
        result["risk_level"] = _("Unknown (stale data)")
        result["recommendation"] = _(
            "No current assessment is possible: the newest SPEI-3 reading for this "
            "region is %(months)s months old (%(date)s). Re-run the drought-index "
            "import before acting on this result. For reference only, that reading was "
            "%(level)s (SPEI-3 %(spei)s)."
        ) % {"months": months, "date": measured_on.strftime("%Y-%m"),
             "level": level, "spei": spei}
        return result

    advice = {
        "Normal": _(
            "SPEI-3 is %(spei)s as of %(date)s: no drought stress indicated. Keep the "
            "current irrigation schedule and monitor weekly."
        ),
        "Mild": _(
            "Near-normal: SPEI-3 is %(spei)s as of %(date)s. Keep normal monitoring and "
            "avoid unnecessary irrigation."
        ),
        "Moderate": _(
            "Moderate drought: SPEI-3 is %(spei)s as of %(date)s. Shorten the irrigation "
            "interval slightly and prioritise the most sensitive growth stage."
        ),
        "Severe": _(
            "Severe drought: SPEI-3 is %(spei)s as of %(date)s. Increase irrigation "
            "frequency, concentrate limited water on the most sensitive growth stage, and "
            "postpone any non-essential sowing."
        ),
        "Extreme": _(
            "Extreme drought: SPEI-3 is %(spei)s as of %(date)s. Water availability is "
            "the binding constraint. Prioritise the most sensitive crop areas, and "
            "consider deferring water-demanding crops until conditions improve."
        ),
    }.get(level, _(
        "SPEI-3 is %(spei)s (%(level)s) as of %(date)s."
    ))

    note = ""
    if result["irrigation_buffer"] > 0 and level in ("Moderate", "Severe", "Extreme"):
        note = " " + _(
            "Note: gravity-fed irrigation loses a large share of applied water, so "
            "the crop is less buffered than the regional index alone suggests."
        )
    elif result["irrigation_buffer"] < 0 and level in ("Severe", "Extreme"):
        note = " " + _(
            "Note: drip irrigation delivers water efficiently, which partially "
            "buffers this deficit."
        )

    result["risk_level"] = level
    result["band"] = {"Normal": "low", "Mild": "low",
                      "Moderate": "moderate"}.get(level, "high")
    result["recommendation"] = (advice + note) % {
        "spei": spei, "level": level, "date": measured_on.strftime("%Y-%m"),
    }
    result["assessed"] = True
    return result


def _calculate_risk(crop_name, irrigation_name, region=None):
    """Backwards-compatible (risk_level, recommendation) pair."""
    outcome = assess_drought_risk(region, crop_name, irrigation_name)
    return outcome["risk_level"], outcome["recommendation"]


def _degree_to_compass(degree):
    directions = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]
    idx = int((degree % 360) / 45 + 0.5) % 8
    return directions[idx]


# ============== MAP & DASHBOARD CONFIG ==============

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
        "map_unavailable": _("The map could not be loaded. Please reload the page."),
        "drawings_cleared": _("All drawings have been removed."),
        "select_mode": _("Selection mode: click a drawn area to see its details."),
        "draw_mode": _("Draw mode: trace a polygon to measure the area."),
        "measure_mode": _("Ruler mode: click two points on the map to measure distance."),
        "ping_mode": _("Ping mode: click a point for exact live metrics."),
        "ruler_cleared": _("Ruler measurement cleared."),
        "ping_no_live": _("Ping saved, but live metrics are unavailable for now."),
        "first_point_done": _("First point recorded. Click the second point."),
        "distance_line": _("Distance: __M__ m (__KM__ km)."),
        "polygon_center": _("Center: __LAT__, __LNG__"),
        "polygon_line": _(
            "Area: __M2__ m\u00b2 (__HA__ ha, __KM2__ km\u00b2) | Perimeter: __PM__ m | Center: __LAT__, __LNG__"
        ),
        "ping_line": _(
            "Ping: __LAT__, __LNG__ | Wind: __WS__ km/h | Temp: __T__\u00b0C | Humidity: __H__% | Rain: __R__ mm"
        ),
        "sensor_drop_mode": _("Sensor drop mode: click the map to place a sensor pin."),
        "sensor_coords_filled": _("Coordinates filled. Complete the form and submit."),
    }


# ============== CHART / SVG HELPERS ==============

def _svg_points(values, vmin=None, vmax=None, svg_x_start=25, svg_x_end=295, svg_y_top=10, svg_y_bottom=130):
    n = len(values)
    if n == 0:
        return ""
    if n == 1:
        x = (svg_x_start + svg_x_end) / 2
        return f"{x:.1f},{((svg_y_top + svg_y_bottom) / 2):.1f}"
    lo = vmin if vmin is not None else min(values)
    hi = vmax if vmax is not None else max(values)
    if hi == lo:
        hi = lo + 1
    pts = []
    for i, v in enumerate(values):
        x = svg_x_start + (i / (n - 1)) * (svg_x_end - svg_x_start)
        norm = (v - lo) / (hi - lo)
        y = svg_y_bottom - norm * (svg_y_bottom - svg_y_top)
        pts.append(f"{x:.1f},{y:.1f}")
    return " ".join(pts)


def _month_labels(queryset=None, limit=12):
    if queryset is None:
        return ["Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
                "Jan", "Feb", "Mar", "Apr", "May"]
    ms = []
    seen = set()
    for obj in queryset:
        if obj.measurement_date:
            m = obj.measurement_date.strftime("%b")
            if m not in seen:
                ms.append(m)
                seen.add(m)
            if len(ms) >= limit:
                break
    ms.reverse()
    while len(ms) < limit:
        ms.insert(0, "")
    return ms[:limit]


def _chart_series(queryset, field, limit=12):
    vals = []
    for obj in queryset:
        v = getattr(obj, field)
        if v is not None:
            vals.append(float(v))
        if len(vals) >= limit:
            break
    vals.reverse()  # newest-first -> chronological order
    return vals


def _chart_months(queryset, field, limit=12):
    """Return exactly `limit` month labels aligned 1:1 with _chart_series()."""
    labels = []
    for obj in queryset:
        v = getattr(obj, field, None)
        if v is not None:
            labels.append(obj.measurement_date.strftime("%b") if obj.measurement_date else "")
        if len(labels) >= limit:
            break
    labels.reverse()
    while len(labels) < limit:
        labels.insert(0, "")
    return labels[:limit]


def _normalize(values):
    """Scale values to 0-100% based on data min/max."""
    if not values:
        return values
    lo, hi = min(values), max(values)
    if hi == lo:
        return [50.0] * len(values)
    return [(v - lo) / (hi - lo) * 100 for v in values]


def _year_series(queryset, field, n=12):
    """Extract n evenly-spaced values from a queryset (newest-first) for yearly view."""
    all_vals = []
    for obj in queryset:
        v = getattr(obj, field)
        if v is not None:
            all_vals.append(float(v))
    if not all_vals:
        return []
    all_vals.reverse()  # chronological
    if len(all_vals) <= n:
        return all_vals
    step = (len(all_vals) - 1) / n
    return [all_vals[round(i * step)] for i in range(n)]


def _year_months(queryset, field, n=12):
    """Month labels aligned with _year_series()."""
    all_dates = []
    for obj in queryset:
        v = getattr(obj, field, None)
        if v is not None:
            all_dates.append(obj.measurement_date)
    if not all_dates:
        return [""] * n
    all_dates.reverse()
    if len(all_dates) <= n:
        labels = [d.strftime("%b") if d else "" for d in all_dates]
        while len(labels) < n:
            labels.insert(0, "")
        return labels[:n]
    step = (len(all_dates) - 1) / n
    labels = []
    for i in range(n):
        d = all_dates[round(i * step)]
        labels.append(d.strftime("%b") if d else "")
    return labels


# ============== PREDICTION HELPERS ==============

def _prediction_warning_block(validation_metrics):
    """Operational vs trend-only horizon status derived from walk-forward skill.

    The +7d / +30d values served come from the forecast-augmented SPI-3 method,
    so their confidence is taken from that method's backtest (realistic scenario:
    3 real days for +7d, 7 real days for +30d), falling back to the XGBoost F1.
    """
    if hasattr(validation_metrics, 'validation_metrics'):
        metrics = validation_metrics.validation_metrics or {}
    elif isinstance(validation_metrics, dict):
        metrics = validation_metrics
    else:
        metrics = {}

    spi = metrics.get('spi_forecast') or {}

    def conf(m, fallback):
        f1 = (m or {}).get('drought_f1')
        return round(f1 * 100) if isinstance(f1, (int, float)) else fallback

    def spi_conf(horizon, mode, fallback):
        m = (((spi.get(horizon) or {}).get('scenarios')) or {}).get(mode)
        f1 = (m or {}).get('drought_f1')
        if isinstance(f1, (int, float)) and f1 > 0:
            return round(f1 * 100)
        return fallback

    return {
        'today': {'status': 'operational', 'confidence_pct': conf(metrics.get('nowcast'), 80)},
        'day_7': {'status': 'operational',
                  'confidence_pct': spi_conf('7', 'forecast3_plus_clim',
                                             conf(metrics.get('forecast_7d'), 55))},
        'day_30': {'status': 'trend_only',
                   'confidence_pct': spi_conf('30', 'forecast7_plus_clim',
                                              conf(metrics.get('forecast_30d'), 40))},
        'note': ('The 7-day horizon is operational. The 30-day figure is trend-only: it reflects '
                 'the GFS rainfall forecast blended with climatology, not a firm prediction.'),
    }


def _get_region_stations(region, year=None):
    """Return station coordinates and their latest metrics for the given region.

    Extracts the station coordinates from region.sample_points (such as the two
    ground stations 'v8 st humide inf' and 'v8 st sub humide') and pairs each with its
    latest database measurements (ClimateMetrics, DroughtIndices) to drive heatmap origins.
    """
    stations = []
    if not region:
        return stations

    sample_points = region.sample_points or []
    if not sample_points and region.latitude and region.longitude:
        sample_points = [{'lat': float(region.latitude), 'lon': float(region.longitude), 'name': region.name}]

    year_num = None
    if year:
        try:
            year_num = int(str(year.label if hasattr(year, 'label') else year).split()[0])
        except (ValueError, AttributeError):
            year_num = None

    for idx, sp in enumerate(sample_points, start=1):
        try:
            s_lat = float(sp['lat'])
            s_lon = float(sp['lon'])
        except (KeyError, ValueError, TypeError):
            continue

        raw_name = sp.get('name', f'Station {idx}')
        if 'humide inf' in raw_name.lower():
            label = 'Station Humide Inférieure'
        elif 'sub humide' in raw_name.lower():
            label = 'Station Sub-Humide'
        else:
            label = raw_name

        cm_query = ClimateMetrics.objects.filter(latitude=s_lat, longitude=s_lon)
        di_query = DroughtIndices.objects.filter(latitude=s_lat, longitude=s_lon)
        if year_num:
            cm_year = cm_query.filter(measurement_date__year=year_num).order_by('-measurement_date').first()
            di_year = di_query.filter(measurement_date__year=year_num).order_by('-measurement_date').first()
            cm = cm_year or cm_query.order_by('-measurement_date').first()
            di = di_year or di_query.order_by('-measurement_date').first()
        else:
            cm = cm_query.order_by('-measurement_date').first()
            di = di_query.order_by('-measurement_date').first()

        spei_val = float(di.spei_3month) if di and di.spei_3month is not None else None
        spi_val = float(di.spi_3month) if di and di.spi_3month is not None else None
        if spei_val is not None:
            st_risk = max(5, min(95, round(50 - (spei_val * 20))))
        elif spi_val is not None:
            st_risk = max(5, min(95, round(50 - (spi_val * 20))))
        else:
            st_risk = 50

        temp_c = float(cm.temperature_mean_c) if cm and cm.temperature_mean_c is not None else None
        rain_mm = float(cm.rainfall_mm) if cm and cm.rainfall_mm is not None else None
        humidity = int(cm.relative_humidity_percent) if cm and cm.relative_humidity_percent is not None else None
        wind_ms = float(cm.wind_speed_ms) if cm and cm.wind_speed_ms is not None else None
        severity = str(di.drought_severity_class) if di and di.drought_severity_class else (
            'Severe Drought' if st_risk >= 75 else ('Moderate Drought' if st_risk >= 50 else 'Normal / Safe')
        )
        date_str = cm.measurement_date.strftime('%Y-%m-%d') if cm and cm.measurement_date else None

        stations.append({
            'id': idx,
            'name': raw_name,
            'label': label,
            'lat': s_lat,
            'lon': s_lon,
            'temp_c': temp_c,
            'rain_mm': rain_mm,
            'humidity': humidity,
            'wind_speed_ms': wind_ms,
            'spei': spei_val,
            'spi': spi_val,
            'severity': severity,
            'risk_score': st_risk,
            'date': date_str,
        })

    return stations