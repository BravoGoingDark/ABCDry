import pickle

import numpy as np
import pandas as pd
from django.utils import timezone

try:
    import xgboost as xgb
except ImportError:  # pragma: no cover - optional dependency guard
    xgb = None

from .physical_helpers import calculate_etc

DROUGHT_WEIGHT = 10.0
DROUGHT_RISK_THRESHOLD = 65.0
EVAL_THRESHOLDS = [55.0, 60.0, 65.0]


class XGBoostDroughtRiskPredictor:
    """Predicts today's drought risk score and returns feature-importance drivers."""

    def __init__(self, horizon_days=0):
        from sklearn.preprocessing import StandardScaler
        self.model = None
        self.scaler = StandardScaler()
        self.feature_names = None
        self.validation_metrics = {}
        self.train_date = None
        self.horizon_days = horizon_days

    def _require_xgboost(self):
        if xgb is None:
            raise ImportError("xgboost is required for XGBoostDroughtRiskPredictor. Install requirements.txt.")

    RAIN_WINDOWS = (7, 30, 60, 90)

    @staticmethod
    def _date_column(frame):
        for candidate in ('measurement_date', 'date'):
            if candidate in frame.columns:
                return candidate
        return None

    @staticmethod
    def _naive_dates(series):
        """Dates as tz-naive UTC.

        The metric tables mix tz-aware and tz-naive timestamps, and taking
        .values off a tz-aware column silently drops the offset, which then
        fails when compared against an aware Timestamp. Normalizing to naive
        UTC once keeps every window comparison consistent.
        """
        return pd.to_datetime(series, utc=True).dt.tz_localize(None)

    @classmethod
    def _windowed(cls, frame, values, days, index):
        """Sum `values` over the trailing `days` calendar days, by date.

        Row-count windows (.rolling(90)) are only equivalent to a 90-day window
        when the frame holds exactly one row per day. It does not: gauge
        regions are daily while CHIRPS regions are monthly, so 90 rows meant
        90 days for one region and 7.5 years for another. Time-based rolling
        gives the same 90 days everywhere, and monthly totals are summed as
        whole months, which is exactly what a 90-day rainfall total means.
        """
        series = pd.Series(np.asarray(values, dtype=float), index=index)
        return series.rolling(f'{int(days)}D', min_periods=1).sum().values

    def _enrich_frame(self, df):
        """Add long-window and lagged features that correlate with SPI-3.

        All windows are calendar-time based (see _windowed) so they keep their
        meaning across regions whose source data has different granularity.
        SPI-3 is a ~90-day standardized rainfall anomaly, so the strongest
        legitimate predictors are the observed SPI indices and long-window
        rainfall accumulations computed from already-observed data only."""
        frame = df.copy()
        date_col = self._date_column(frame)
        if date_col is None:
            raise ValueError('History frame needs a measurement_date/date column.')

        frame[date_col] = self._naive_dates(frame[date_col])
        frame = frame.sort_values(date_col).reset_index(drop=True)
        index = pd.DatetimeIndex(frame[date_col])

        if 'ndvi' in frame.columns:
            frame['ndvi'] = frame['ndvi'].fillna(0.5)

        if 'etc_mm' not in frame.columns:
            frame['etc_mm'] = frame.apply(
                lambda row: calculate_etc(row.get('et0_mm', row.get('et0', 3.0)), 1.0),
                axis=1,
            )

        resolution = frame.get('temporal_resolution_days')
        if resolution is None:
            resolution = pd.Series(1.0, index=frame.index)
        resolution = pd.to_numeric(resolution, errors='coerce').fillna(1.0)

        if 'rainfall_mm' in frame.columns:
            rain = pd.to_numeric(frame['rainfall_mm'], errors='coerce').fillna(0.0)
            for days in self.RAIN_WINDOWS:
                frame[f'rainfall_{days}d_mm'] = self._windowed(frame, rain, days, index)
            # Scale-free dry spell: a dry day counts 1, a dry month counts its
            # own length, so the feature means the same thing in both regions.
            dry_days = (rain < 1.0).astype(float) * resolution
            frame['dry_ratio_90d'] = self._windowed(frame, dry_days, 90, index) / 90.0

        if 'spi' in frame.columns:
            frame['spi_1m'] = frame['spi']
        if 'spei' in frame.columns:
            frame['spei_1m'] = frame['spei']

        # The 3-month index is the quantity being predicted. It is only a legal
        # feature when forecasting (the value at t is known, the target is at
        # t+horizon); for a 0-day nowcast it would be the label itself.
        if self.horizon_days and self.horizon_days > 0 and 'spei3' in frame.columns:
            frame['spei3_current'] = frame['spei3']
            frame['spei3_lag30'] = self._shift_days(frame['spei3'], index, 30)
            frame['spei3_lag90'] = self._shift_days(frame['spei3'], index, 90)

        # Calendar-date lags: the value observed 7 / 30 days ago, which is what
        # a forecast actually conditions on.
        for src, lag_days, out in (('spi3', 7, 'spi3_lag7'), ('spi3', 30, 'spi3_lag30')):
            if src in frame.columns:
                frame[out] = self._shift_days(frame[src], index, lag_days)

        derived = [f'rainfall_{d}d_mm' for d in self.RAIN_WINDOWS] + [
            'dry_ratio_90d', 'spi_1m', 'spei_1m', 'spi3_lag7', 'spi3_lag30']
        if self.horizon_days and self.horizon_days > 0:
            derived += ['spei3_current', 'spei3_lag30', 'spei3_lag90']
        for col in derived:
            if col not in frame.columns:
                frame[col] = 0.0

        return frame.fillna({col: 0.0 for col in derived})

    @staticmethod
    def _shift_days(values, index, days):
        """Value of `values` as observed `days` calendar days earlier."""
        series = pd.Series(pd.to_numeric(values, errors='coerce').values, index=index)
        return series.reindex(index - pd.Timedelta(days=days)).values

    def _value_days_ago(self, frame, col, days, date_col):
        """Value of `col` on the calendar day `days` before each row."""
        if col not in frame.columns:
            return np.zeros(len(frame))
        index = pd.DatetimeIndex(self._naive_dates(frame[date_col]))
        series = pd.Series(pd.to_numeric(frame[col], errors='coerce').values, index=index)
        return series.reindex(index - pd.Timedelta(days=days)).values

    def extract_features(self, df_context):
        """Extract features from a frame ending at the prediction day."""
        features = {}
        frame = df_context
        date_col = self._date_column(frame)
        if date_col is None:
            raise ValueError('Feature context needs a measurement_date/date column.')
        last_date = self._naive_dates(frame[date_col]).iloc[-1]
        index = pd.DatetimeIndex(self._naive_dates(frame[date_col]))

        def recent(col, days):
            """Rows inside the trailing `days` calendar days."""
            mask = index >= (last_date - pd.Timedelta(days=days))
            return frame.loc[mask]

        last_30 = recent(None, 30)
        last_7 = recent(None, 7)

        features['soil_moisture_pct'] = last_30['soil_moisture_pct'].iloc[-1]
        features['ndvi'] = last_30['ndvi'].iloc[-1]
        features['lst_c'] = last_30['lst_c'].iloc[-1] if 'lst_c' in last_30.columns else 0.0

        rain = pd.to_numeric(last_30['rainfall_mm'], errors='coerce').fillna(0.0)
        features['rainfall_30d_mm'] = rain.sum()
        features['rainfall_7d_mm'] = pd.to_numeric(
            last_7['rainfall_mm'], errors='coerce').fillna(0.0).sum()
        features['etc_7d_avg_mm'] = pd.to_numeric(last_7['etc_mm'], errors='coerce').mean()
        features['etc_30d_avg_mm'] = pd.to_numeric(last_30['etc_mm'], errors='coerce').mean()

        temps = pd.to_numeric(last_30['temp_max_c'], errors='coerce')
        features['temp_anomaly_c'] = temps.iloc[-1] - temps.mean()

        # Date-aware dry spell: calendar days since the last wet observation.
        wet = frame.loc[pd.to_numeric(frame['rainfall_mm'], errors='coerce').fillna(0.0) >= 1.0]
        features['days_since_last_rain'] = (
            float((last_date - self._naive_dates(wet[date_col]).max()).days) if len(wet) else float('nan')
        )

        for col, days, out in (('soil_moisture_pct', 7, 'soil_moisture_trend'),
                               ('ndvi', 14, 'ndvi_trend')):
            values = pd.to_numeric(recent(None, days)[col], errors='coerce').values
            if len(values) >= 2 and not np.all(np.isnan(values)):
                filled = np.nan_to_num(values, nan=float(np.nanmean(values)))
                x = np.arange(len(filled))
                features[out] = float(np.polyfit(x, filled, 1)[0])
            else:
                features[out] = 0.0

        features['rainfall_60d_mm'] = float(frame['rainfall_60d_mm'].iloc[-1])
        features['rainfall_90d_mm'] = float(frame['rainfall_90d_mm'].iloc[-1])
        features['dry_ratio_90d'] = float(frame['dry_ratio_90d'].iloc[-1])

        rain_90 = float(frame['rainfall_90d_mm'].iloc[-1])
        features['rainfall_anomaly_90d'] = self._rain90_anomaly(rain_90)

        features['spi_1m'] = float(frame['spi_1m'].iloc[-1])
        features['spei_1m'] = float(frame['spei_1m'].iloc[-1])
        features['spi3_lag7'] = float(self._value_days_ago(frame, 'spi3', 7, date_col)[-1])
        features['spi3_lag30'] = float(self._value_days_ago(frame, 'spi3', 30, date_col)[-1])

        if self.horizon_days and self.horizon_days > 0:
            features['spei3_current'] = float(frame['spei3_current'].iloc[-1])
            features['spei3_lag30'] = float(frame['spei3_lag30'].iloc[-1])
            features['spei3_lag90'] = float(frame['spei3_lag90'].iloc[-1])

        return pd.DataFrame([features])

    def _rain90_anomaly(self, rain_90):
        """Standardize the 90-day rainfall total with TRAIN-set statistics.

        Previously mu/sd were taken from the whole frame including the
        validation years, which leaked the answer into the features."""
        mean = getattr(self, 'rain90_mean', None)
        std = getattr(self, 'rain90_std', None)
        if mean is None or std is None or not std or std != std or std <= 0:
            return 0.0
        return (float(rain_90) - float(mean)) / float(std)

    def calculate_target_risk(self, df_30days):
        """Drought label = risk score derived from the standard 3-month drought
        index: risk = 50 - index*15, clamped 0-100. Index <= -1 (moderate
        drought) maps to risk >= 65.

        The first *usable* index wins. The columns are tried in order of
        specificity rather than blindly preferring spi3, because spi_3month
        and spi_1month are NULL for every row in this database: preferring it
        unconditionally made every label collapse to the neutral 50.0, so the
        model was trained to predict a constant and all reported scores were
        meaningless."""
        for column in ('spi3', 'spi', 'spei3', 'spei'):
            if column not in df_30days.columns:
                continue
            value = df_30days[column].iloc[-1]
            try:
                value = float(value)
            except (TypeError, ValueError):
                continue
            if value != value:  # NaN
                continue
            return round(max(0.0, min(100.0, 50.0 - value * 15.0)), 1)

        # No drought index at all: an unlabelled sample, not a neutral one.
        return None


    CONTEXT_DAYS = 180

    def _build_samples(self, historical_data, horizon_days=0):
        """Build samples where features are known at day t and the target is the
        SPI-3 risk at day t + horizon_days (0 = nowcast, 7/30 = forecast).

        The context and the target window are selected by calendar date, not by
        row offset, so a sample means the same thing whether the region reports
        daily gauges or monthly CHIRPS totals."""
        enriched = self._enrich_frame(historical_data)
        features_list = []
        targets = []
        dates = []

        n = len(enriched)
        date_col = self._date_column(enriched)
        stamps = self._naive_dates(enriched[date_col])

        for end in range(30, n - horizon_days + 1):
            anchor = stamps.iloc[end - 1]
            # Context: the trailing CONTEXT_DAYS calendar days ending at `end`.
            start = enriched.index[(stamps <= anchor) & (stamps > anchor - pd.Timedelta(days=self.CONTEXT_DAYS))]
            if len(start) == 0:
                continue
            context = enriched.loc[start[0]:end - 1]
            features = self.extract_features(context)

            future_end = end + horizon_days
            future_date = stamps.iloc[future_end - 1]
            fut = enriched.index[(stamps <= future_date) & (stamps > future_date - pd.Timedelta(days=30))]
            window = enriched.loc[fut[0]:future_end - 1] if len(fut) else enriched.iloc[future_end - 1:future_end]
            target = self.calculate_target_risk(window)
            if target is None:
                # No observed drought index for this date -> unlabelled, so it
                # cannot be used for supervised training or scoring.
                continue
            features_list.append(features)
            targets.append(target)
            dates.append(future_date)

        if not features_list:
            raise ValueError('Not enough data to train XGBoost risk model.')

        return pd.concat(features_list, ignore_index=True), np.array(targets), pd.to_datetime(pd.Series(dates))

    def _evaluate(self, X_val_scaled, y_val, val_dates):
        preds = np.clip(self.model.predict(X_val_scaled), 0, 100)
        residuals = preds - y_val
        mae = float(np.mean(np.abs(residuals)))
        rmse = float(np.sqrt(np.mean(residuals ** 2)))
        ss_res = float(np.sum(residuals ** 2))
        ss_tot = float(np.sum((y_val - np.mean(y_val)) ** 2))
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

        drought = y_val >= DROUGHT_RISK_THRESHOLD

        # Metrics are reported at the FIXED threshold (65) only, so the numbers
        # are honest out-of-sample figures. Tuning a "best" threshold on the
        # validation set would inflate them.
        predicted = preds >= DROUGHT_RISK_THRESHOLD
        tp = float(np.sum(drought & predicted))
        fp = float(np.sum((~drought) & predicted))
        fn = float(np.sum(drought & (~predicted)))
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

        thresholds = []
        for threshold in EVAL_THRESHOLDS:
            predicted_t = preds >= threshold
            tp_t = float(np.sum(drought & predicted_t))
            fp_t = float(np.sum((~drought) & predicted_t))
            fn_t = float(np.sum(drought & (~predicted_t)))
            precision_t = tp_t / (tp_t + fp_t) if (tp_t + fp_t) else 0.0
            recall_t = tp_t / (tp_t + fn_t) if (tp_t + fn_t) else 0.0
            f1_t = 2 * precision_t * recall_t / (precision_t + recall_t) if (precision_t + recall_t) else 0.0
            thresholds.append({
                'threshold': threshold,
                'precision': round(precision_t, 3),
                'recall': round(recall_t, 3),
                'f1': round(f1_t, 3),
                'drought_days_caught': int(tp_t),
                'drought_days_total': int(drought.sum()),
            })

        return {
            'split': f"{val_dates.min().date()} -> {val_dates.max().date()}",
            'n_samples': int(len(y_val)),
            'mae': round(mae, 2),
            'rmse': round(rmse, 2),
            'r2': round(r2, 3),
            'drought_days_total': int(drought.sum()),
            'prediction_threshold': DROUGHT_RISK_THRESHOLD,
            'drought_precision': round(precision, 3),
            'drought_recall': round(recall, 3),
            'drought_f1': round(f1, 3),
            'drought_days_caught': int(tp),
            'thresholds': thresholds,
        }

    def train(self, historical_data, horizon_days=None, *args, **kwargs):
        self._require_xgboost()
        if horizon_days is None:
            horizon_days = self.horizon_days
        self.horizon_days = horizon_days
        X, y, dates = self._build_samples(historical_data, horizon_days=horizon_days)
        self.feature_names = X.columns.tolist()

        # Chronological walk-forward split (no random-shuffle leakage):
        # train through 2022, validate 2023+; fall back to 80/20 chronological
        # when the history does not span both periods.
        if len(dates) >= 60 and dates.min().year <= 2016 and int((dates >= '2023-01-01').sum()) >= 30:
            split_idx = int((dates < '2023-01-01').sum())
        else:
            split_idx = int(0.8 * len(X))

        X_train, X_val = X.iloc[:split_idx], X.iloc[split_idx:]
        y_train, y_val = y[:split_idx], y[split_idx:]

        # Standardize the 90-day rainfall anomaly with TRAIN-period statistics
        # only. Computing mu/sd over the full frame (as before) leaked the
        # validation years into the features and inflated every score.
        rain90_train = pd.to_numeric(X_train['rainfall_90d_mm'], errors='coerce')
        self.rain90_mean = float(rain90_train.mean())
        std = float(rain90_train.std())
        self.rain90_std = std if std and std == std and std > 0 else None
        if self.rain90_std is not None:
            X = X.copy()
            X['rainfall_anomaly_90d'] = (
                pd.to_numeric(X['rainfall_90d_mm'], errors='coerce') - self.rain90_mean
            ) / self.rain90_std
            X = X.fillna({'rainfall_anomaly_90d': 0.0})
            X_train, X_val = X.iloc[:split_idx], X.iloc[split_idx:]

        X_train_scaled = self.scaler.fit_transform(X_train)
        X_val_scaled = self.scaler.transform(X_val)

        # No drought-class weighting here. The label is a continuous severity
        # score that already grows with dryness, and up-weighting the ~7% of
        # drought days was measured to hurt calibration of that score
        # (7-day R2 0.374 weighted vs 0.595 unweighted, MAE 4.23 vs 3.15).
        # Class weighting belongs on a classifier, not this regressor.

        self.model = xgb.XGBRegressor(
            n_estimators=300,
            max_depth=5,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            early_stopping_rounds=25,
            eval_metric='mae',
        )
        self.model.fit(
            X_train_scaled,
            y_train,
            eval_set=[(X_val_scaled, y_val)],
            verbose=False,
        )

        suffix = '' if horizon_days == 0 else f'_{horizon_days}d'
        import os
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        models_dir = os.path.join(root_dir, 'models')
        out_dir = models_dir if os.path.exists(models_dir) else '.'

        with open(os.path.join(out_dir, f'xgboost_risk_model{suffix}.pkl'), 'wb') as model_file:
            pickle.dump(self.model, model_file)
        with open(os.path.join(out_dir, f'xgboost_scaler{suffix}.pkl'), 'wb') as scaler_file:
            pickle.dump(self.scaler, scaler_file)
        with open(os.path.join(out_dir, f'xgboost_features{suffix}.pkl'), 'wb') as features_file:
            pickle.dump(self.feature_names, features_file)
        with open(os.path.join(out_dir, f'xgboost_rain_stats{suffix}.pkl'), 'wb') as stats_file:
            pickle.dump({'mean': self.rain90_mean, 'std': self.rain90_std}, stats_file)

        self.validation_metrics = self._evaluate(X_val_scaled, y_val, dates[split_idx:])
        self.train_date = timezone.now().isoformat()
        return self

    def load(self, model_path='xgboost_risk_model.pkl', scaler_path='xgboost_scaler.pkl',
             features_path='xgboost_features.pkl', stats_path='xgboost_rain_stats.pkl'):
        import os
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        models_dir = os.path.join(root_dir, 'models')

        def _resolve(p):
            if os.path.exists(p):
                return p
            alt = os.path.join(models_dir, os.path.basename(p))
            if os.path.exists(alt):
                return alt
            return p

        with open(_resolve(model_path), 'rb') as model_file:
            self.model = pickle.load(model_file)
        with open(_resolve(scaler_path), 'rb') as scaler_file:
            self.scaler = pickle.load(scaler_file)
        with open(_resolve(features_path), 'rb') as features_file:
            self.feature_names = pickle.load(features_file)

        # Train-set rainfall statistics used by rainfall_anomaly_90d. Absent in
        # models saved before this fix, in which case the anomaly is 0.0.
        resolved_stats = _resolve(stats_path)
        if os.path.exists(resolved_stats):
            with open(resolved_stats, 'rb') as stats_file:
                stats = pickle.load(stats_file) or {}
            self.rain90_mean = stats.get('mean')
            self.rain90_std = stats.get('std')
        else:
            self.rain90_mean, self.rain90_std = None, None
        return self


    def predict(self, df_30days):
        enriched = self._enrich_frame(df_30days)
        X = self.extract_features(enriched)
        X_scaled = self.scaler.transform(X)
        risk = self.model.predict(X_scaled)[0]
        return round(float(max(0, min(100, risk))), 1)

    def get_drivers(self, df_30days):
        enriched = self._enrich_frame(df_30days)
        X = self.extract_features(enriched)
        _ = self.scaler.transform(X)

        importance = getattr(self.model, 'feature_importances_', np.zeros(len(self.feature_names or [])))

        driver_mapping = {
            'rainfall_30d_mm': 'rainfall_deficit',
            'rainfall_7d_mm': 'rainfall_deficit',
            'rainfall_60d_mm': 'rainfall_deficit',
            'rainfall_90d_mm': 'rainfall_deficit',
            'rainfall_anomaly_90d': 'rainfall_deficit',
            'dry_ratio_90d': 'rainfall_deficit',
            'spi_1m': 'rainfall_deficit',
            'spei_1m': 'rainfall_deficit',
            'spi3_lag7': 'rainfall_deficit',
            'spi3_lag30': 'rainfall_deficit',
            'days_since_last_rain': 'rainfall_deficit',
            'soil_moisture_pct': 'soil_moisture_decline',
            'soil_moisture_trend': 'soil_moisture_decline',
            'temp_anomaly_c': 'high_temperature',
            'ndvi': 'vegetation_stress',
            'ndvi_trend': 'vegetation_stress',
            'etc_7d_avg_mm': 'high_evapotranspiration',
            'etc_30d_avg_mm': 'high_evapotranspiration',
        }

        driver_scores = {
            'rainfall_deficit': 0,
            'soil_moisture_decline': 0,
            'high_temperature': 0,
            'vegetation_stress': 0,
            'high_evapotranspiration': 0,
        }

        for feature_name, importance_score in zip(self.feature_names or [], importance):
            driver_name = driver_mapping.get(feature_name)
            if driver_name in driver_scores:
                driver_scores[driver_name] += float(importance_score)

        total = sum(driver_scores.values())
        abs_scores = {k: round(v, 1) for k, v in driver_scores.items()}
        if total > 0:
            driver_scores = {key: round((value / total) * 100, 1) for key, value in driver_scores.items()}

        return {
            'rainfall_deficit': driver_scores.get('rainfall_deficit', 0),
            'high_temperature': driver_scores.get('high_temperature', 0),
            'soil_moisture_decline': driver_scores.get('soil_moisture_decline', 0),
            'vegetation_stress': driver_scores.get('vegetation_stress', 0),
            'high_evapotranspiration': driver_scores.get('high_evapotranspiration', 0),
            'absolute': abs_scores,
        }
