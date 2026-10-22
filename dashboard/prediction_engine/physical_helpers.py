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


def update_soil_water(previous_mm, rainfall_mm, irrigation_mm, etc_mm, runoff_mm=0, awc_mm=None):
    """Daily water balance. Returns new soil water in mm, cannot go below 0
    or above available_water_capacity_mm (excess becomes deep percolation)."""
    new = previous_mm + rainfall_mm + irrigation_mm - etc_mm - runoff_mm
    new = max(0, new)
    if awc_mm is not None:
        new = min(new, awc_mm)
    return new


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


# ------------------------------------------------------------------ #
# SPEI – Standardized Precipitation Evapotranspiration Index
# Vicente-Serrano et al. (2010) – log-logistic on water balance
# ------------------------------------------------------------------ #

def _fit_monthly_loglogistic(monthly_values):
    """Fit 3-parameter log-logistic per calendar month using probability
    weighted moments (PWM), following Vicente-Serrano et al. (2010).

    NOTE: a scipy ``fisk.fit(vals, floc=0)`` fit is WRONG here because it
    constrains the distribution to positive support, while the water
    balance D = P - ET0 is negative in most months of semi-arid climates.
    The PWM estimator below handles negative values natively.

    Returns dict of month -> {'alpha', 'beta', 'gamma'} parameters,
    or None if the month has too few observations or the fit degenerates.
    """
    from scipy.special import gamma as _gamma
    params = {}
    for month in range(1, 13):
        vals = monthly_values.get(month, [])
        vals = np.array([v for v in vals if not np.isnan(v)], dtype=float)
        if len(vals) < 5:
            params[month] = None
            continue
        try:
            vals_sorted = np.sort(vals)
            n = len(vals_sorted)
            F = (np.arange(1, n + 1) - 0.35) / n  # Hosking plotting positions
            w0 = float(np.mean(vals_sorted))
            w1 = float(np.mean((1.0 - F) * vals_sorted))
            w2 = float(np.mean((1.0 - F) ** 2 * vals_sorted))
            denom = 3.0 * w2 - w0
            if abs(denom) < 1e-12:
                params[month] = None
                continue
            # L-moment ratio -> shape: r = 2*beta / (3*beta - 1)
            r = (2.0 * w1 - w0) / denom
            if abs(3.0 * r - 2.0) < 1e-12:
                params[month] = None
                continue
            beta = r / (3.0 * r - 2.0)
            if not np.isfinite(beta) or beta <= 1.0:
                params[month] = None
                continue
            g1 = _gamma(1.0 + 1.0 / beta)
            g2 = _gamma(1.0 - 1.0 / beta)
            if g2 == 0 or not np.isfinite(g1 * g2):
                params[month] = None
                continue
            l2 = w0 - 2.0 * w1  # second L-moment (always > 0)
            if l2 <= 0:
                params[month] = None
                continue
            alpha = beta * l2 / (g1 * g2)
            if alpha <= 0 or not np.isfinite(alpha):
                params[month] = None
                continue
            gamma_p = w0 - beta * l2
            params[month] = {'alpha': float(alpha), 'beta': float(beta),
                             'gamma': float(gamma_p)}
        except Exception:
            params[month] = None
    return params


def _spei_from_cdf(cdf_val):
    """Transform log-logistic CDF to standard normal (SPEI).

    Uses the Abramowitz & Stegun rational approximation (Eq. 26.2.23)
    from Vicente-Serrano et al. (2010).
    """
    if cdf_val <= 1e-15:
        return -3.29
    if cdf_val >= 1 - 1e-15:
        return 3.29
    if cdf_val <= 0.5:
        w = np.sqrt(-2.0 * np.log(cdf_val))
        c0, c1, c2 = 2.515517, 0.802853, 0.010328
        d1, d2, d3 = 1.432788, 0.189269, 0.001308
        spei = -(w - (c0 + c1 * w + c2 * w**2) /
                 (1.0 + d1 * w + d2 * w**2 + d3 * w**3))
    else:
        w = np.sqrt(-2.0 * np.log(1.0 - cdf_val))
        c0, c1, c2 = 2.515517, 0.802853, 0.010328
        d1, d2, d3 = 1.432788, 0.189269, 0.001308
        spei = w - (c0 + c1 * w + c2 * w**2) / \
            (1.0 + d1 * w + d2 * w**2 + d3 * w**3)
    return round(max(-3.29, min(3.29, float(spei))), 2)


def calculate_spei(precipitation_series, et0_series, nmonth=3):
    """Standardized Precipitation Evapotranspiration Index.

    Uses the log-logistic distribution on accumulated water balance
    (Precipitation − ET0), following Vicente-Serrano et al. (2010).

    Parameters
    ----------
    precipitation_series : pd.Series
        Daily rainfall (mm/day) with DatetimeIndex.
    et0_series : pd.Series
        Daily reference evapotranspiration (mm/day) with DatetimeIndex.
        Series must share the same DatetimeIndex.
    nmonth : int
        Accumulation period in months (3, 6, or 12).  Default 3.

    Returns
    -------
    pd.Series
        Daily-indexed SPEI values (each day carries its month's SPEI).
    """
    if not isinstance(precipitation_series, pd.Series) or len(precipitation_series) < 60:
        return pd.Series(dtype=float)
    if et0_series is None or et0_series.empty:
        return pd.Series(dtype=float)

    # Ensure both series are float
    precip = precipitation_series.astype(float).copy()
    et0 = et0_series.astype(float).reindex(precip.index, fill_value=0.0).copy()

    # Monthly water balance: P_month − ET0_month
    monthly_p = precip.resample('ME').sum()
    monthly_e = et0.resample('ME').sum()
    monthly_d = monthly_p - monthly_e

    # Accumulate over nmonth calendar months
    roll_d = monthly_d.rolling(window=nmonth, min_periods=nmonth).sum()

    # Group accumulated values by calendar month and fit log-logistic
    acc_monthly_vals = {}
    for date, val in roll_d.items():
        if pd.notna(val):
            acc_monthly_vals.setdefault(date.month, []).append(float(val))
    month_params = _fit_monthly_loglogistic(acc_monthly_vals)

    # SPEI for each month
    month_spei = {}
    for date, val in roll_d.items():
        if pd.isna(val):
            continue
        params = month_params.get(date.month)
        if params is None:
            continue
        # Analytic log-logistic CDF: F(x) = 1 / (1 + (alpha / (x - gamma))^beta)
        x = float(val) - params['gamma']
        if x <= 0:
            cdf = 0.0
        else:
            cdf = 1.0 / (1.0 + (params['alpha'] / x) ** params['beta'])
        month_spei[(date.year, date.month)] = _spei_from_cdf(cdf)

    # Broadcast back to daily index
    values = [month_spei.get((d.year, d.month), np.nan) for d in precip.index]
    result = pd.Series(values, index=precip.index, dtype='float64')
    result.name = f'SPEI-{nmonth}'
    return result