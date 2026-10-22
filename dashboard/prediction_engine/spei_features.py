"""SPEI prediction pipeline: monthly aggregation + feature engineering + ML training.

Builds a monthly dataset from daily ClimateMetrics and RemoteSensingMetrics
rows, computes SPEI-3 targets, adds lag features, and trains XGBoost regressors
for SPEI(T+1) and SPEI(T+3).

Usage:
    from dashboard.prediction_engine.spei_features import build_spei_dataset, train_spei_models
    df = build_spei_dataset(region_id=4)
    models = train_spei_models(df)
"""
import logging

import numpy as np
import pandas as pd

from dashboard.models import ClimateMetrics, RemoteSensingMetrics, Region
from dashboard.prediction_engine.physical_helpers import calculate_spei, calculate_vci

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# 1. Data loading → daily DataFrame
# ------------------------------------------------------------------ #

def _load_daily_data(region_id, lat=None, lon=None, subregion=None):
    """Load daily climate + remote sensing data for a single point.

    Returns a pd.DataFrame indexed by date with columns for all available
    climate and remote sensing fields.
    """
    qs_c = ClimateMetrics.objects.filter(region_id=region_id).order_by('measurement_date')
    qs_r = RemoteSensingMetrics.objects.filter(region_id=region_id).order_by('measurement_date')

    if lat is not None and lon is not None:
        qs_c = qs_c.filter(latitude=lat, longitude=lon)
        qs_r = qs_r.filter(latitude=lat, longitude=lon)
        if not qs_r.exists():
            # Satellite products (MODIS/SMAP) are pulled at region-center
            # resolution; fall back to all region rows when the exact sample
            # point has none, so land-memory features still load.
            qs_r = RemoteSensingMetrics.objects.filter(region_id=region_id).order_by('measurement_date')

    climate = list(qs_c.values('measurement_date', 'rainfall_mm', 'temperature_max_c',
                                'temperature_min_c', 'temperature_mean_c',
                                'relative_humidity_percent', 'wind_speed_ms',
                                'solar_radiation_mjm2day',
                                'evapotranspiration_et0_mmday'))
    remote = list(qs_r.values('measurement_date', 'ndvi', 'ndwi',
                               'land_surface_temperature_c',
                               'satellite_soil_moisture_percent',
                               'vegetation_condition_index'))

    if not climate and not remote:
        return pd.DataFrame()

    df_c = pd.DataFrame(climate).rename(columns={'measurement_date': 'date'})
    df_r = pd.DataFrame(remote).rename(columns={'measurement_date': 'date'})

    for df in [df_c, df_r]:
        if df.empty:
            continue
        df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)

    if not df_c.empty and not df_r.empty:
        # Join by calendar month: remote-sensing products (16-day composites,
        # daily LST) are aggregated to monthly means and broadcast onto every
        # climate row of that month. A nearest-date merge would only match
        # rows within a few days of a composite and drop the rest.
        df_c = df_c.set_index('date')
        df_r_m = df_r.set_index('date').resample('ME').mean()
        period_map = df_r_m.index.to_period('M')
        for col in df_r_m.columns:
            series = pd.Series(df_r_m[col].values, index=period_map)
            df_c[col] = df_c.index.to_period('M').map(series)
        df = df_c
    elif df_r.empty:
        df = df_c.set_index('date')
    else:
        df = df_r.set_index('date')

    # DecimalField columns come back as Python Decimals, which pandas stores as
    # object dtype. That silently breaks numeric dtype selection, mean/sum
    # semantics and any downstream float arithmetic, so coerce once here.
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    return df


def _load_all_points(region_id):
    """Load daily data for ALL sample points of a region.

    Returns dict of (lat, lon, subregion) → DataFrame.
    """
    region = Region.objects.get(id=region_id)
    points = []
    if region.sample_points:
        for sp in region.sample_points:
            points.append((float(sp['lat']), float(sp['lon']), sp.get('name', '').strip().lower().replace(' ', '_')))
    else:
        points.append((float(region.latitude), float(region.longitude), ''))

    data = {}
    for lat, lon, sub in points:
        df = _load_daily_data(region_id, lat=lat, lon=lon)
        if not df.empty:
            data[(lat, lon, sub)] = df
    return data


# ------------------------------------------------------------------ #
# 2. Daily → Monthly aggregation
# ------------------------------------------------------------------ #

def _aggregate_monthly(df):
    """Aggregate daily data to calendar-month resolution.

    - Sums: rainfall
    - Means: everything else (NDVI, LST, temp, humidity, wind, solar, SM)
    """
    agg_rules = {
        'rainfall_mm': 'sum',
    }
    # All other columns → mean
    mean_cols = [c for c in df.columns if c != 'rainfall_mm']
    for c in mean_cols:
        agg_rules[c] = 'mean'

    monthly = df.resample('ME').agg(agg_rules)
    monthly.index = monthly.index.to_period('M')
    return monthly


def _compute_et0_from_monthly(monthly):
    """Resolve the monthly mean daily ET0 rate for each month.

    Prefers the daily ET0 already stored in ClimateMetrics
    (evapotranspiration_et0_mmday, averaged over the month) and only
    falls back to Penman-Monteith recomputation from monthly means where
    the stored value is missing.
    """
    from dashboard.prediction_engine.physical_helpers import calculate_et0

    if 'evapotranspiration_et0_mmday' in monthly.columns:
        monthly['et0_mm_day'] = monthly['evapotranspiration_et0_mmday']
    else:
        monthly['et0_mm_day'] = np.nan

    need = monthly['et0_mm_day'].isna()
    for idx in monthly.index[need]:
        row = monthly.loc[idx]
        t = row.get('temperature_mean_c')
        h = row.get('relative_humidity_percent')
        w = row.get('wind_speed_ms')
        s = row.get('solar_radiation_mjm2day')
        if pd.notna(t) and pd.notna(h) and pd.notna(w) and pd.notna(s):
            # Approximate solar W/m² from MJ/m²/day:  W/m² = MJ/m²/day / 0.0864
            solar_wm2 = float(s) / 0.0864 if float(s) > 0 else 0
            monthly.at[idx, 'et0_mm_day'] = round(
                calculate_et0(float(t), float(w), solar_wm2, float(h)), 2)
    return monthly


# ------------------------------------------------------------------ #
# 3. SPEI computation
# ------------------------------------------------------------------ #

def _compute_monthly_spei(monthly, nmonth=3):
    """Compute SPEI-nmonth on the monthly water balance (P − ET0).

    Uses the daily-approximation trick: create daily P and ET0 series from
    the monthly totals, then use the standard calculate_spei.

    A month with no ET0 cannot have a water balance, so its SPEI is left
    unknown (NaN) and excluded from training rather than being silently
    treated as zero evaporative demand, which would bias it wet.
    """
    if 'rainfall_mm' not in monthly.columns or 'et0_mm_day' not in monthly.columns:
        return pd.Series(np.nan, index=monthly.index)

    missing_et0 = monthly.index[monthly['et0_mm_day'].isna()]
    if len(missing_et0):
        logger.warning(
            'SPEI: %d month(s) missing ET0 (%s); SPEI withheld for those months',
            len(missing_et0),
            ', '.join(str(p) for p in missing_et0[:6]) + ('...' if len(missing_et0) > 6 else ''),
        )

    # Reconstruct daily series (uniform daily value within each month)
    daily_idx = monthly.index.to_timestamp().to_series().apply(
        lambda p: pd.date_range(p, periods=p.days_in_month if hasattr(p, 'days_in_month') else 30, freq='D')
    ).explode()

    rain_daily = []
    et0_daily = []
    for date in daily_idx:
        p = date.to_period('M')
        if p in monthly.index:
            row = monthly.loc[p]
            days = p.days_in_month if hasattr(p, 'days_in_month') else 30
            rain_daily.append(row['rainfall_mm'] / days)
            et0_daily.append(row['et0_mm_day'] if pd.notna(row['et0_mm_day']) else 0.0)
        else:
            rain_daily.append(0.0)
            et0_daily.append(0.0)

    rain_s = pd.Series(rain_daily, index=daily_idx)
    et0_s = pd.Series(et0_daily, index=daily_idx)

    spei_daily = calculate_spei(rain_s, et0_s, nmonth=nmonth)

    # Aggregate back to monthly (take the last day of each month)
    spei_monthly = spei_daily.resample('ME').last()
    spei_monthly.index = spei_monthly.index.to_period('M')
    if len(missing_et0):
        spei_monthly.loc[spei_monthly.index.isin(missing_et0)] = np.nan
    return spei_monthly


# ------------------------------------------------------------------ #
# 4. Feature engineering
# ------------------------------------------------------------------ #

def _expanding_month_climatology(values, index):
    """Past-only expanding mean per calendar month.

    out[i] = mean of `values` over all PRIOR rows sharing the calendar month
    of row i. NaN until that calendar month has at least one prior
    observation. Never looks ahead, so it is safe to use as a feature in
    walk-forward training (a groupby-expanding mean computed in one pass
    would include the current row unless carefully shifted).
    """
    out = np.full(len(values), np.nan)
    sums, counts = {}, {}
    for i in range(len(values)):
        v = values[i]
        m = index[i].month
        c = counts.get(m, 0)
        if c:
            out[i] = sums[m] / c
        if v is not None and not np.isnan(v):
            sums[m] = sums.get(m, 0.0) + float(v)
            counts[m] = c + 1
    return pd.Series(out, index=index)


def _build_features(monthly_df):
    """Create feature matrix with temporal lag features.

    Input: monthly DataFrame with climate + remote sensing columns.
    Output: DataFrame ready for XGBoost.
    """
    df = monthly_df.copy()

    # Basic time features
    df['month'] = df.index.month.astype(int)
    df['season'] = ((df['month'] % 12 + 3) // 3).astype(int)  # 1=winter..4=autumn

    # Lag features for key variables
    lag_vars = ['rainfall_mm', 'ndvi', 'satellite_soil_moisture_percent',
                'temperature_mean_c', 'ndwi', 'et0_mm_day']
    for var in lag_vars:
        if var not in df.columns:
            continue
        for lag in [1, 2, 3]:
            df[f'{var}_t{lag}'] = df[var].shift(lag)

    # Current-month water-balance state (SPEI-3 known at forecast time):
    # the strongest single predictor of near-future SPEI.
    if 'spei_target' in df.columns:
        df['spei_current'] = df['spei_target']

    # Long-memory accumulation features: droughts build over seasons, so
    # multi-month totals of rainfall/ET0 and their balance carry signal
    # that single-month lags miss (especially at the T+3 horizon).
    if 'rainfall_mm' in df.columns:
        df['rain_6m'] = df['rainfall_mm'].rolling(6, min_periods=4).sum()
        df['rain_12m'] = df['rainfall_mm'].rolling(12, min_periods=9).sum()
    if 'et0_mm_day' in df.columns:
        days = pd.Series([idx.days_in_month for idx in df.index], index=df.index)
        et0_month = df['et0_mm_day'] * days
        df['et0_6m'] = et0_month.rolling(6, min_periods=4).sum()
        df['et0_12m'] = et0_month.rolling(12, min_periods=9).sum()
    if 'rain_6m' in df.columns and 'et0_6m' in df.columns:
        df['bal_6m'] = df['rain_6m'] - df['et0_6m']
        if 'rain_12m' in df.columns and 'et0_12m' in df.columns:
            df['bal_12m'] = df['rain_12m'] - df['et0_12m']
    if 'rainfall_mm' in df.columns and 'et0_mm_day' in df.columns:
        days = pd.Series([idx.days_in_month for idx in df.index], index=df.index)
        et0_month = df['et0_mm_day'] * days
        df['bal_3m'] = (df['rainfall_mm'] - et0_month).rolling(3, min_periods=3).sum()

    # Drought memory: past SPEI makes persistence explicit so the model does
    # not have to rediscover it from raw weather lags. These are the single
    # strongest leak-free predictors at short horizons.
    if 'spei_target' in df.columns:
        for lag in (1, 2, 3, 6):
            df[f'spei_lag{lag}'] = df['spei_target'].shift(lag)

    # Climatological expectation of the COMING months (past-only expanding
    # means, so no future information enters training rows). At T+3 most of
    # the outcome is future rainfall the model cannot see; handing it the
    # seasonal baseline explicitly beats forcing it to decode `month`.
    for col, prefix in (('rainfall_mm', 'rain_clim'), ('et0_mm_day', 'et0_clim')):
        if col not in df.columns:
            continue
        clim = _expanding_month_climatology(df[col].values, df.index)
        for h in (1, 3):
            total = pd.Series(0.0, index=df.index)
            for k in range(1, h + 1):
                total = total + clim.shift(-k)
            df[f'{prefix}_n{h}'] = total

    # Cyclic month encoding: December (12) and January (1) are adjacent;
    # a raw month integer makes the model learn that seam by brute force.
    month_num = np.asarray([idx.month for idx in df.index], dtype=float)
    df['month_sin'] = np.sin(2 * np.pi * month_num / 12)
    df['month_cos'] = np.cos(2 * np.pi * month_num / 12)

    # Climate teleconnection indices (North Atlantic Oscillation):
    # Standardized atmospheric pressure anomalies governing Western Mediterranean storm tracks.
    try:
        from dashboard.prediction_engine.climate_indices import merge_nao_features
        df = merge_nao_features(df)
    except Exception as exc:
        logger.warning('Could not merge climate teleconnection features: %s', exc)

    return df


def _merge_points(daily_dfs, keys):
    """Average multiple sample points into a single daily series.

    A region can hold several gauge points. Kept separate, each point yields its
    own SPEI, so the same month gets several different "correct" targets
    (Ichkeul: mean spread 0.31, max 1.89) and the training rows are correlated
    duplicates rather than independent samples. Averaging the inputs first
    produces one well-defined monthly series located at the area centroid.

    Returns (daily_df, lat, lon). Falls back to the single point if merging
    is not possible.
    """
    frames = [df for df in daily_dfs if df is not None and not df.empty]
    if not frames:
        return None, None, None
    if len(frames) == 1:
        return frames[0], keys[0][0], keys[0][1]

    merged = pd.concat(frames, axis=0)
    numeric = merged.select_dtypes(include=[np.number]).columns
    merged = merged[numeric].groupby(level=0).mean().sort_index()
    return (merged,
            float(np.mean([k[0] for k in keys])),
            float(np.mean([k[1] for k in keys])))


def build_spei_dataset(region_id, spei_nmonth=3, merge_points=True):
    """Build the full monthly dataset with SPEI targets and features.

    Returns pd.DataFrame ready for model training.

    With merge_points=True (default) a region's sample points are averaged
    into one series, so each calendar month yields exactly one row and one
    target. Pass merge_points=False to keep points separate.
    """
    point_data = _load_all_points(region_id)
    if not point_data:
        return pd.DataFrame()

    keys = list(point_data.keys())
    if merge_points and len(keys) > 1:
        merged_daily, lat, lon = _merge_points(list(point_data.values()), keys)
        if merged_daily is not None and not merged_daily.empty:
            point_data = {(lat, lon, 'merged'): merged_daily}

    all_dfs = []
    for (lat, lon, sub), daily_df in point_data.items():
        monthly = _aggregate_monthly(daily_df)
        monthly = _compute_et0_from_monthly(monthly)
        spei = _compute_monthly_spei(monthly, nmonth=spei_nmonth)
        monthly['spei_target'] = spei
        monthly['latitude'] = lat
        monthly['longitude'] = lon
        monthly['subregion'] = sub
        monthly = _build_features(monthly)
        all_dfs.append(monthly)

    if not all_dfs:
        return pd.DataFrame()

    full = pd.concat(all_dfs, axis=0)

    # Add SPEI target at T+1 and T+3
    full['spei_target_t1'] = full.groupby(['latitude', 'longitude'])['spei_target'].shift(-1)
    full['spei_target_t3'] = full.groupby(['latitude', 'longitude'])['spei_target'].shift(-3)

    return full


# ------------------------------------------------------------------ #
# 5. Model training
# ------------------------------------------------------------------ #

FEATURE_COLS = [
    # Current monthly values
    'rainfall_mm', 'et0_mm_day',
    'temperature_mean_c', 'temperature_max_c', 'temperature_min_c',
    'relative_humidity_percent', 'wind_speed_ms', 'solar_radiation_mjm2day',
    'ndvi', 'ndwi', 'land_surface_temperature_c',
    'satellite_soil_moisture_percent', 'vegetation_condition_index',
    # Time features
    'month', 'season',
    # Current water-balance state
    'spei_current',
    # Long-memory accumulation features
    'rain_6m', 'rain_12m', 'et0_6m', 'et0_12m', 'bal_6m', 'bal_3m', 'bal_12m',
    # SPEI autoregressive memory
    'spei_lag1', 'spei_lag2', 'spei_lag3', 'spei_lag6',
    # Climatological expectation of the coming 1 / 3 months
    'rain_clim_n1', 'rain_clim_n3', 'et0_clim_n1', 'et0_clim_n3',
    # Cyclic seasonality
    'month_sin', 'month_cos',
    # Geography (informative when training across pooled regions)
    'latitude', 'longitude',
    # Lag features
    'rainfall_mm_t1', 'rainfall_mm_t2', 'rainfall_mm_t3',
    'et0_mm_day_t1', 'et0_mm_day_t2', 'et0_mm_day_t3',
    'ndvi_t1', 'ndvi_t2', 'ndvi_t3',
    'satellite_soil_moisture_percent_t1', 'satellite_soil_moisture_percent_t2',
    'satellite_soil_moisture_percent_t3',
    'temperature_mean_c_t1', 'temperature_mean_c_t2', 'temperature_mean_c_t3',
    'ndwi_t1', 'ndwi_t2', 'ndwi_t3',
    # Climate teleconnection indices (North Atlantic Oscillation)
    'nao_index', 'nao_lag1', 'nao_lag2', 'nao_3m',
]


SEVERITY_WEIGHTS = {'Low': 1.0, 'Moderate': 2.0, 'High': 4.0, 'Severe': 8.0, 'Extreme': 12.0}

DROUGHT_PROB_THRESHOLD = 0.35

# A forecast whose feature month is further behind "now" than this is treated as
# stale (data feed has stopped) and is not written or shown as current.
MAX_FORECAST_LAG_MONTHS = 2

# Walk-forward (262 months, Ichkeul only) behaviour of the decision rule below.
# The regression alone is badly hedged and misses most droughts; the classifier
# alone is precise but too quiet. Either one alone is worse than the pair, so
# the warning fires when EITHER is confident.
DECISION_RULE_PROVENANCE = {
    'evaluated_months': 262,
    'drought_events': 48,
    'extreme_events': 12,
    'regression_only': {'recall': 0.38, 'precision': 0.64, 'extreme_catch': 0.42},
    'classifier_only': {'recall': 0.27, 'precision': 0.65, 'extreme_catch': 0.33},
    'hybrid': {'recall': 0.40, 'precision': 0.59, 'extreme_catch': 0.50},
    'warning_rate_per_year': 1.5,
}

# Calibration measured on the same walk-forward, drought (SPEI <= -1) frequency:
# 0.00-0.15 -> 12%, 0.15-0.35 -> 44%, 0.35-0.55 -> 60%, 0.55-0.75 -> 80%.
# Monotone, so the probability is safe to show a user as-is.
PROBABILITY_BANDS = [
    (0.55, 'high', 'Drought likely'),
    (0.35, 'elevated', 'Elevated drought risk'),
    (0.15, 'low', 'Low drought risk'),
    (0.0, 'minimal', 'Minimal drought risk'),
]


def drought_flag_from_probability(prob, threshold=DROUGHT_PROB_THRESHOLD):
    """Binary drought decision from the classifier probability.

    The regression model supplies the severity band; this supplies the
    yes/no drought call, so both surfaces must agree on one threshold.
    """
    if prob is None:
        return None
    return bool(prob >= threshold)


def drought_probability_band(prob):
    """Map a drought probability onto a human-readable band."""
    if prob is None or (isinstance(prob, float) and np.isnan(prob)):
        return 'unknown', 'Insufficient data'
    val = float(prob)
    for cutoff, key, label in PROBABILITY_BANDS:
        if val >= cutoff:
            return key, label
    return 'minimal', 'Minimal drought risk'


def drought_warning(prob, spei_t1, prob_threshold=DROUGHT_PROB_THRESHOLD,
                    spei_threshold=-1.0, month=None, crop=None):
    """Combine the classifier and the regression into one warning decision.

    Firing when either surface is confident recovers droughts that the
    hedged regression would have missed: 38% -> 40% recall and, more
    importantly, 42% -> 50% of extreme events caught.

    Phenology-aware threshold adaptation:
    During critical spring growth stages (months 2-5: Feb-May for cereals/olives),
    water deficits cause severe yield collapse. In these months, thresholds are
    dynamically sensitized (prob_threshold=0.28, spei_threshold=-0.80) to give farmers
    advance warning.

    Returns (warned, source) where source is 'classifier', 'regression',
    'both', or None when neither is confident.
    """
    p_thresh = prob_threshold
    s_thresh = spei_threshold
    if month is not None:
        try:
            m = int(month)
            if m in (2, 3, 4, 5):
                p_thresh = min(p_thresh, 0.28)
                s_thresh = max(s_thresh, -0.80)
        except (ValueError, TypeError):
            pass

    from_prob = (prob is not None and not (isinstance(prob, float) and np.isnan(prob))
                 and float(prob) >= p_thresh)
    has_spei = spei_t1 is not None and not (isinstance(spei_t1, float) and np.isnan(spei_t1))
    from_reg = bool(has_spei and float(spei_t1) <= s_thresh)

    if from_prob and from_reg:
        return True, 'both'
    if from_prob:
        return True, 'classifier'
    if from_reg:
        return True, 'regression'
    return False, None


def _severity_class(spei_value):
    """Map a SPEI value to its drought class label."""
    if spei_value > -0.5:
        return 'Low'
    if spei_value > -1.0:
        return 'Moderate'
    if spei_value > -1.5:
        return 'High'
    if spei_value > -2.0:
        return 'Severe'
    return 'Extreme'


def _severity_sample_weights(y_values):
    """Sample weights that upweight rare drought classes so the model does
    not regress extreme events toward the mean."""
    return np.array([SEVERITY_WEIGHTS[_severity_class(v)] for v in y_values],
                    dtype=float)


def _month_of_year(frame):
    """Calendar month (1-12) per row, for month-of-year climatology."""
    idx = frame.index
    if isinstance(idx, pd.PeriodIndex):
        return pd.Series(idx.month, index=frame.index)
    if isinstance(idx, pd.DatetimeIndex):
        return pd.Series(idx.month, index=frame.index)
    if 'period' in frame.columns:
        per = pd.PeriodIndex(pd.to_datetime(frame['period']), freq='M')
        return pd.Series(per.month, index=frame.index)
    return pd.Series(1, index=frame.index)


def _month_ordinal(frame):
    """Monthly ordinal per row, so a chronological split can purge a whole month.

    Works whether the frame is indexed by month or carries a 'period' column.
    """
    idx = frame.index
    if isinstance(idx, pd.PeriodIndex):
        return pd.Series(idx.astype('int64'), index=frame.index)
    if isinstance(idx, pd.DatetimeIndex):
        return pd.Series(idx.year * 12 + idx.month, index=frame.index)
    if 'period' in frame.columns:
        per = pd.PeriodIndex(pd.to_datetime(frame['period']), freq='M')
        return pd.Series(per.astype('int64'), index=frame.index)
    return pd.Series(np.arange(len(frame)), index=frame.index)


def train_spei_models(df, target_t1='spei_target_t1', target_t3='spei_target_t3',
                      mode='regression', train_t3=True):
    """Train XGBoost regressors for SPEI(T+1) and SPEI(T+3).

    mode:
      'regression'   plain squared-error regression (original behaviour)
      'weighted'     severity-weighted samples (fights class imbalance)
      'quantile_p25' 25th-percentile regression (risk-averse, errs dry-side)
      'delta'        learn SPEI(t+h) − SPEI(t) and add the known current
                     value back, so persistence (delta = 0) is the model's
                     explicit origin rather than something it must rediscover

    Returns dict with model objects, metrics, benchmarks (persistence and
    climatology on the same holdout), and feature importances.
    """
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
    from xgboost import XGBRegressor

    available_cols = [c for c in FEATURE_COLS if c in df.columns]

    # Drop rows where target is NaN
    needed_targets = [target_t1]
    if train_t3:
        needed_targets.append(target_t3)

    for target in needed_targets:
        if target not in df.columns:
            raise ValueError(f'Target column {target} not found. Run build_spei_dataset first.')

    results = {}
    target_list = [('spei_t1', target_t1)]
    if train_t3:
        target_list.append(('spei_t3', target_t3))

    for target_name, target_col in target_list:
        # Only rows with a known target are usable. Feature NaNs (e.g. SMAP
        # missing before 2015) are fine: XGBoost routes missing values natively.
        train_df = df.dropna(subset=[target_col])
        if len(train_df) < 24:
            results[target_name] = {'error': f'Only {len(train_df)} samples, need >= 24'}
            continue

        X = train_df[available_cols].values
        y = train_df[target_col].values

        # Chronological split with a PURGE gap. A row for month m carries the
        # target for month m+h, so training targets can reach into the test
        # window; the purge must equal the TARGET HORIZON, not a fixed 1
        # month, or a T+3 model trains on the very months it is scored on.
        horizon = 3 if target_col == target_t3 else 1
        month = _month_ordinal(train_df)
        months = np.sort(month.unique())
        test_start = months[min(int(len(months) * 0.8), len(months) - 1)]
        test_mask = (month >= test_start).values
        train_mask = ((month + horizon) < test_start).values
        n_purged = int((~test_mask & ~train_mask).sum())

        if train_mask.sum() < 24 or test_mask.sum() < 1:
            results[target_name] = {
                'error': (f'Not enough data after purging: {int(train_mask.sum())} '
                          f'train / {int(test_mask.sum())} test')}
            continue

        X_train, y_train = X[train_mask], y[train_mask]
        X_test, y_test = X[test_mask], y[test_mask]

        # Honest benchmarks on the SAME holdout rows: if the model cannot
        # beat persistence (T+1) or climatology, the ML adds nothing and the
        # metrics must say so next to its own.
        benchmarks = {}
        if 'spei_current' in train_df.columns:
            cur = train_df['spei_current'].values.astype(float)
            pp, pt = cur[test_mask], y_test
            ok = ~(np.isnan(pp) | np.isnan(pt))
            if ok.sum() >= 5:
                benchmarks['persistence'] = {
                    'mae': round(float(np.mean(np.abs(pp[ok] - pt[ok]))), 4),
                    'r2': round(float(r2_score(pt[ok], pp[ok])), 4),
                    'n': int(ok.sum()),
                }
        moy = _month_of_year(train_df).values
        tr_moy, te_moy = moy[train_mask], moy[test_mask]
        clim_mean = float(np.mean(y_train)) if len(y_train) else np.nan
        clim_by_month = {m: float(np.mean(y_train[tr_moy == m]))
                         for m in np.unique(tr_moy)}
        clim_pred = np.array([clim_by_month.get(m, clim_mean) for m in te_moy])
        if len(y_test) >= 5:
            benchmarks['climatology'] = {
                'mae': round(float(np.mean(np.abs(clim_pred - y_test))), 4),
                'r2': round(float(r2_score(y_test, clim_pred)), 4),
                'n': int(len(y_test)),
            }

        base_train = base_test = None
        if mode == 'delta':
            if 'spei_current' not in train_df.columns:
                results[target_name] = {'error': "mode 'delta' needs the 'spei_current' column"}
                continue
            usable = ~np.isnan(train_df['spei_current'].values.astype(float))
            keep = usable & train_mask
            X_train, y_train = X[keep], (y - train_df['spei_current'].values.astype(float))[keep]
            base_test = train_df['spei_current'].values.astype(float)[test_mask]
            if len(y_train) < 24:
                results[target_name] = {
                    'error': (f'Not enough delta rows after purging: {len(y_train)}')}
                continue

        if mode == 'quantile_p25':
            model = XGBRegressor(
                objective='reg:quantileerror',
                quantile_alpha=0.25,
                n_estimators=200,
                max_depth=3,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                min_child_weight=5,
                random_state=42,
                verbosity=0,
            )
            model.fit(X_train, y_train, verbose=False)
        elif mode == 'weighted':
            model = XGBRegressor(
                n_estimators=200,
                max_depth=3,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                min_child_weight=5,
                random_state=42,
                verbosity=0,
            )
            model.fit(X_train, y_train,
                      sample_weight=_severity_sample_weights(y_train),
                      verbose=False)
        else:
            model = XGBRegressor(
                n_estimators=300,
                max_depth=5,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                random_state=42,
                verbosity=0,
            )
            if mode == 'delta':
                # Trained on deltas: the holdout targets are on the absolute
                # scale, so an eval_set would compare apples to oranges.
                model.fit(X_train, y_train, verbose=False)
            else:
                model.fit(X_train, y_train,
                          eval_set=[(X_test, y_test)],
                          verbose=False)

        if mode == 'delta':
            # A plain model object trained on deltas; predictions get the
            # known current SPEI added back before scoring.
            y_pred = base_test + model.predict(X_test)
        else:
            y_pred = model.predict(X_test)
        mae = float(mean_absolute_error(y_test, y_pred))
        rmse = float(np.sqrt(mean_squared_error(y_test, y_pred)))
        r2 = float(r2_score(y_test, y_pred))

        # Feature importances
        importances = dict(zip(available_cols, [float(x) for x in model.feature_importances_]))
        top_features = sorted(importances.items(), key=lambda x: -x[1])[:10]

        results[target_name] = {
            'model': model,
            'mode': mode,
            'mae': round(mae, 4),
            'rmse': round(rmse, 4),
            'r2': round(r2, 4),
            'n_train': int(X_train.shape[0]),
            'n_test': int(test_mask.sum()),
            'n_purged': n_purged,
            'eval': 'purged chronological holdout (purge = target horizon)',
            'benchmarks': benchmarks,
            'top_features': top_features,
            'feature_cols': available_cols,
        }

    return results


# ------------------------------------------------------------------ #
# 6. Prediction helpers
# ------------------------------------------------------------------ #

def spei_to_risk(spei_value):
    """Convert SPEI to 0-100 risk score (higher = more drought risk).

    Mapping per Vicente-Serrano et al. (2010) drought classes:
        SPEI > -0.5  → Low risk (score 20)
        -0.5 to -1.0  → Moderate (40)
        -1.0 to -1.5  → High (60)
        -1.5 to -2.0  → Severe (80)
        < -2.0        → Extreme (100)
    """
    if spei_value is None or np.isnan(spei_value):
        return None, None
    val = float(spei_value)
    if val > -0.5:
        return 20, 'Low'
    elif val > -1.0:
        return 40, 'Moderate'
    elif val > -1.5:
        return 60, 'High'
    elif val > -2.0:
        return 80, 'Severe'
    else:
        return 100, 'Extreme'


RECOMMENDATIONS = {
    'Low': [
        'Maintain normal irrigation schedules.',
        'Continue regular monitoring.',
    ],
    'Moderate': [
        'Increase monitoring frequency to weekly.',
        'Check soil moisture levels regularly.',
        'Review irrigation efficiency.',
    ],
    'High': [
        'Optimize irrigation scheduling.',
        'Prepare water-saving measures.',
        'Prioritize high-value crop irrigation.',
    ],
    'Severe': [
        'Increase irrigation frequency.',
        'Deploy drought mitigation strategies.',
        'Consider deficit irrigation for non-critical areas.',
    ],
    'Extreme': [
        'Implement emergency drought response.',
        'Prioritize critical water resources.',
        'Deploy crop protection measures.',
        'Consider crop salvage options.',
    ],
}


def get_recommendations(risk_level, month=None, crop=None, prob=None):
    """Return actionable recommendations for the given risk level with optional
    plain-language probability statements and crop-calendar adjustments.
    """
    base_recs = list(RECOMMENDATIONS.get(risk_level, ['Monitor conditions closely.']))

    # Plain-language risk odds statement
    if prob is not None and not (isinstance(prob, float) and np.isnan(prob)):
        pct = int(round(float(prob) * 100))
        if pct >= 55:
            base_recs.insert(0, f'High probability (~{pct}%) of notable moisture deficit for the coming period.')
        elif pct >= 35:
            base_recs.insert(0, f'Elevated probability (~{pct}%) of drought conditions developing.')

    # Crop/seasonal phenology guidance
    if month is not None:
        try:
            m = int(month)
            if m in (2, 3, 4, 5) and risk_level in ('Moderate', 'High', 'Severe', 'Extreme'):
                base_recs.append(
                    'Spring critical stage (flowering/grain-fill): ensure supplemental irrigation '
                    'and avoid top-dressing nitrogen during dry spells.'
                )
        except (ValueError, TypeError):
            pass

    return base_recs


def train_drought_classifier(df, horizon=3):
    """Train a binary classifier: P(SPEI-3 < -0.5 at T+horizon) — i.e. the
    probability of ANY drought class at that horizon.

    Validated with walk-forward over the last 6 available years (out-of-fold
    predictions). The returned model is refitted on all data for production.

    Each fold PURGES the `horizon` months before the test year: a training
    row for month m carries the label of month m+horizon, so without the
    purge the last training labels would overlap the first test months and
    inflate the scores. (The previous fixed 1-month purge was insufficient
    for horizon=3 and produced misleadingly poor T+3 numbers.)

    Returns {'model', 'feature_cols', 'metrics', 'oof_proba', 'oof_true'}
    or {'error': ...}.
    """
    from sklearn.metrics import (accuracy_score, precision_score, recall_score,
                                 roc_auc_score)
    from xgboost import XGBClassifier

    tcol = 'spei_target_t%d' % horizon
    available_cols = [c for c in FEATURE_COLS if c in df.columns]
    d = df.dropna(subset=[tcol]).copy()
    if len(d) < 100:
        return {'error': f'only {len(d)} usable rows'}

    d['_year'] = d.index.year
    d['_month_ord'] = _month_ordinal(d)
    d['_y'] = (d[tcol] < -0.5).astype(int)
    X_all = d[available_cols].values
    y_all = d['_y'].values
    years_all = d['_year'].values
    months_all = d['_month_ord'].values
    test_years = sorted(set(years_all))[-6:]

    def _make(tr_y):
        pos = max(int(tr_y.sum()), 1)
        neg = int(len(tr_y)) - pos
        return XGBClassifier(
            n_estimators=200, max_depth=3, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
            scale_pos_weight=neg / pos,
            random_state=42, verbosity=0, eval_metric='logloss',
        )

    oof_p, oof_t = [], []
    purged_total = 0
    for yr in test_years:
        te_m = years_all == yr
        year_start = int(months_all[te_m].min())
        # Purge: drop training rows whose TARGET month (m + horizon) falls
        # inside the test year, not just the month before it.
        tr_m = years_all < yr
        tr_m &= (months_all + horizon) < year_start
        purged_total += int((years_all < yr).sum() - tr_m.sum())
        if tr_m.sum() < 100 or te_m.sum() == 0:
            continue
        clf = _make(y_all[tr_m])
        clf.fit(X_all[tr_m], y_all[tr_m])
        oof_p.append(clf.predict_proba(X_all[te_m])[:, 1])
        oof_t.append(y_all[te_m])

    if not oof_p:
        return {'error': 'no walk-forward folds'}

    p = np.concatenate(oof_p)
    t = np.concatenate(oof_t)
    pred = (p >= 0.5).astype(int)

    final = _make(y_all)
    final.fit(X_all, y_all)

    return {
        'model': final,
        'feature_cols': available_cols,
        'metrics': {
            'recall': float(recall_score(t, pred, zero_division=0)),
            'precision': float(precision_score(t, pred, zero_division=0)),
            'accuracy': float(accuracy_score(t, pred)),
            'auc': float(roc_auc_score(t, p)) if len(set(t)) > 1 else None,
            'n_test': int(len(t)),
            'n_purged': purged_total,
            'test_years': [int(y) for y in test_years],
        },
        'oof_proba': p,
        'oof_true': t,
    }
