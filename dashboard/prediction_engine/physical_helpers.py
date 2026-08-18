import numpy as np
import pandas as pd
from scipy import stats as scipy_stats


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


def _calc_prob_zero(samples):
    samples = np.sort(samples[~np.isnan(samples)])
    n = len(samples)
    prob_zero = float(np.sum(samples == 0.0)) / n if n > 0 else 0
    return prob_zero, samples


def _fit_monthly_gamma(monthly_values):
    """Fit gamma per month with zero-precip correction. Returns dict of month->(alpha, loc, beta, prob_zero)."""
    params = {}
    for month in range(1, 13):
        vals = monthly_values.get(month, [])
        vals = np.array([v for v in vals if not np.isnan(v)])
        if len(vals) < 3:
            params[month] = (1.0, 0.0, 1.0, 0.0)
            continue
        prob_zero, non_zero = _calc_prob_zero(vals)
        non_zero = non_zero[non_zero > 0]
        if len(non_zero) < 2:
            params[month] = (1.0, 0.0, 1.0, prob_zero)
            continue
        s_u = np.log(non_zero.mean()) - np.log(non_zero).mean()
        alpha = (1 / (4 * s_u)) * (1 + np.sqrt(1 + 4 * s_u / 3)) if s_u > 0 else 1.0
        beta = non_zero.mean() / alpha if alpha > 0 else 1.0
        loc = 0.0
        try:
            a = scipy_stats.gamma.fit(non_zero, floc=0, a=alpha, scale=beta)
            alpha, beta = a[0], a[2]
        except Exception:
            pass
        params[month] = (alpha, loc, beta, prob_zero)
    return params


def calculate_spi(rainfall_series, nmonth=1):
    """
    Standardized Precipitation Index using per-month gamma distributions
    on CALENDAR-MONTH rainfall totals (the standard SPI methodology).

    rainfall_series: pd.Series of daily rainfall with DatetimeIndex.
    nmonth: accumulation period in months (1, 3, 6, 12, etc.).

    The daily series is aggregated to calendar-month totals, the gamma
    distribution is fitted per calendar month, and SPI is computed for each
    month from its accumulated total. The result is broadcast back to the
    original daily index (every day of a month carries that month's SPI),
    so callers can look values up by measurement date.
    """
    if not isinstance(rainfall_series, pd.Series) or len(rainfall_series) < 30:
        return pd.Series(dtype=float)

    # 1) Aggregate daily rainfall to true calendar-month totals
    monthly = rainfall_series.resample('ME').sum()

    # 2) Accumulate over the last nmonth calendar months
    roll = monthly.rolling(window=nmonth, min_periods=nmonth).sum()

    # 3) Fit gamma per calendar month on the ACCUMULATED totals, grouped by
    #    the month the accumulation window ends in (standard SPI-n method).
    acc_monthly_vals = {}
    for date, val in roll.items():
        if pd.notna(val):
            acc_monthly_vals.setdefault(date.month, []).append(float(val))
    month_params = _fit_monthly_gamma(acc_monthly_vals)

    # 4) SPI for each month
    month_spi = {}
    for date, val in roll.items():
        if pd.isna(val):
            continue
        alpha, loc, beta, prob_zero = month_params[date.month]
        if alpha <= 0 or beta <= 0:
            continue
        if val <= 0:
            cdf = prob_zero
        else:
            gamma_cdf = scipy_stats.gamma.cdf(val, a=alpha, loc=loc, scale=beta)
            cdf = prob_zero + (1 - prob_zero) * gamma_cdf
        cdf = max(1e-15, min(1 - 1e-15, cdf))
        month_spi[(date.year, date.month)] = round(
            max(-3.29, min(3.29, float(scipy_stats.norm.ppf(cdf)))), 2
        )

    # 5) Broadcast each month's SPI to every day of that month
    values = [month_spi.get((d.year, d.month), np.nan) for d in rainfall_series.index]
    result = pd.Series(values, index=rainfall_series.index, dtype='float64')
    result.name = f'SPI-{nmonth}'
    return result


def calculate_vci(current_ndvi, historical_ndvi_list):
    """Vegetation Condition Index. Returns percentage 0-100."""
    ndvi_min = min(historical_ndvi_list)
    ndvi_max = max(historical_ndvi_list)
    if ndvi_max == ndvi_min:
        return 100
    vci = (current_ndvi - ndvi_min) / (ndvi_max - ndvi_min) * 100
    return round(max(0, min(100, vci)), 1)