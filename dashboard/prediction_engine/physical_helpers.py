import numpy as np


def calculate_field_capacity(sand_pct, clay_pct, silt_pct, organic_matter_pct):
    """Saxton & Rawls pedotransfer function. Returns Field Capacity (% volume)."""
    return 20.0 + (0.3 * clay_pct) + (0.1 * silt_pct) - (0.05 * sand_pct)


def calculate_wilting_point(sand_pct, clay_pct, silt_pct):
    """Saxton & Rawls pedotransfer function. Returns Wilting Point (% volume)."""
    return 8.0 + (0.2 * clay_pct) + (0.05 * silt_pct) - (0.03 * sand_pct)


def calculate_available_water_capacity(fc_pct, wp_pct, root_depth_mm):
    """Returns Available Water Capacity in mm."""
    return (fc_pct - wp_pct) / 100 * root_depth_mm


def calculate_et0(temp_mean_c, wind_speed_ms, solar_radiation_wm2, humidity_pct):
    """Penman-Monteith FAO-56 approximation. Returns ET0 in mm/day."""
    es = 0.6108 * np.exp(17.27 * temp_mean_c / (temp_mean_c + 237.3))
    ea = es * (humidity_pct / 100)
    vpd = es - ea
    delta = 4098 * es / (temp_mean_c + 237.3) ** 2
    psychrometric = 0.000665 * 101.3
    rn = solar_radiation_wm2 * 0.0864
    wind_factor = 0.26 * (1 + 0.54 * wind_speed_ms)
    et0 = (0.408 * delta * rn + psychrometric * wind_factor * vpd) / (delta + psychrometric)
    return max(0, round(et0, 2))


def get_crop_coefficient(crop_type, days_since_planting, total_growth_days):
    """FAO-56 Kc lookup based on crop type and growth stage."""
    kc_table = {
        'wheat': {'initial': 0.4, 'mid': 1.1, 'late': 0.4},
        'maize': {'initial': 0.3, 'mid': 1.2, 'late': 0.5},
        'barley': {'initial': 0.35, 'mid': 1.05, 'late': 0.35},
        'olive': {'initial': 0.5, 'mid': 0.65, 'late': 0.55},
    }
    stages = kc_table.get(crop_type.lower(), {'initial': 0.5, 'mid': 1.0, 'late': 0.5})

    if days_since_planting < 0.3 * total_growth_days:
        return stages['initial']
    if days_since_planting < 0.7 * total_growth_days:
        return stages['mid']
    return stages['late']


def calculate_etc(et0, kc):
    """Crop evapotranspiration in mm/day."""
    return et0 * kc


def update_soil_water(previous_mm, rainfall_mm, irrigation_mm, etc_mm, runoff_mm=0):
    """Daily water balance. Returns new soil water in mm, cannot go below 0."""
    new = previous_mm + rainfall_mm + irrigation_mm - etc_mm - runoff_mm
    return max(0, new)


def calculate_spi(rainfall_series_30day_sum, historical_30day_means, historical_30day_std):
    """Standardized Precipitation Index. Returns value from -3 to +3."""
    if historical_30day_std == 0:
        return 0
    spi = (rainfall_series_30day_sum - historical_30day_means) / historical_30day_std
    return max(-3, min(3, spi))


def calculate_vci(current_ndvi, historical_ndvi_list):
    """Vegetation Condition Index. Returns percentage 0-100."""
    ndvi_min = min(historical_ndvi_list)
    ndvi_max = max(historical_ndvi_list)
    if ndvi_max == ndvi_min:
        return 100
    vci = (current_ndvi - ndvi_min) / (ndvi_max - ndvi_min) * 100
    return round(max(0, min(100, vci)), 1)