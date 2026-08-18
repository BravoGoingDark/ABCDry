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

    def _enrich_frame(self, df):
        """Add long-window and lagged features that correlate with SPI-3.

        SPI-3 is a ~90-day standardized rainfall anomaly, so the strongest
        legitimate predictors are the observed SPI indices and long-window
        rainfall accumulations (computed from already-observed data only —
        current SPI-3 itself is never used as a feature)."""
        frame = df.copy()

        if 'ndvi' in frame.columns:
            # Neutral fill for missing/water-NDVI so a NULL (e.g. wetland sample
            # point on open water) cannot crash or bias the model.
            frame['ndvi'] = frame['ndvi'].fillna(0.5)

        if 'etc_mm' not in frame.columns:
            frame['etc_mm'] = frame.apply(
                lambda row: calculate_etc(row.get('et0_mm', row.get('et0', 3.0)), 1.0),
                axis=1,
            )

        if 'rainfall_mm' in frame.columns:
            frame['rainfall_60d_mm'] = frame['rainfall_mm'].rolling(60, min_periods=30).sum()
            frame['rainfall_90d_mm'] = frame['rainfall_mm'].rolling(90, min_periods=30).sum()
            rain_90 = frame['rainfall_90d_mm']
            mu = rain_90.mean()
            sd = rain_90.std()
            frame['rainfall_anomaly_90d'] = ((rain_90 - mu) / sd).fillna(0.0) if sd and sd > 0 else 0.0
            frame['dry_days_90d'] = (frame['rainfall_mm'] < 1).rolling(90, min_periods=30).sum()

        if 'spi' in frame.columns:
            frame['spi_1m'] = frame['spi']
        if 'spei' in frame.columns:
            frame['spei_1m'] = frame['spei']
        if 'spi3' in frame.columns:
            frame['spi3_lag7'] = frame['spi3'].shift(7)
            frame['spi3_lag30'] = frame['spi3'].shift(30)

        for col in ['rainfall_60d_mm', 'rainfall_90d_mm', 'rainfall_anomaly_90d', 'dry_days_90d',
                    'spi_1m', 'spei_1m', 'spi3_lag7', 'spi3_lag30']:
            if col not in frame.columns:
                frame[col] = 0.0

        return frame.fillna({col: 0.0 for col in [
            'rainfall_60d_mm', 'rainfall_90d_mm', 'rainfall_anomaly_90d', 'dry_days_90d',
            'spi_1m', 'spei_1m', 'spi3_lag7', 'spi3_lag30']})

    def extract_features(self, df_context):
        """Extract features from a frame ending at the prediction day (>= 30 rows)."""
        features = {}

        df_30days = df_context.tail(30)

        features['soil_moisture_pct'] = df_30days['soil_moisture_pct'].iloc[-1]
        features['ndvi'] = df_30days['ndvi'].iloc[-1]
        features['lst_c'] = df_30days['lst_c'].iloc[-1]

        features['rainfall_30d_mm'] = df_30days['rainfall_mm'].sum()
        features['rainfall_7d_mm'] = df_30days['rainfall_mm'].tail(7).sum()
        features['etc_7d_avg_mm'] = df_30days['etc_mm'].tail(7).mean()
        features['etc_30d_avg_mm'] = df_30days['etc_mm'].mean()

        avg_temp_30d = df_30days['temp_max_c'].mean()
        current_temp = df_30days['temp_max_c'].iloc[-1]
        features['temp_anomaly_c'] = current_temp - avg_temp_30d

        days_since = 0
        for rain in reversed(df_30days['rainfall_mm'].values):
            if rain >= 1.0:
                break
            days_since += 1
        features['days_since_last_rain'] = days_since

        soil_last_7 = df_30days['soil_moisture_pct'].tail(7).values
        if len(soil_last_7) >= 2:
            x = np.arange(len(soil_last_7))
            features['soil_moisture_trend'] = np.polyfit(x, soil_last_7, 1)[0]
        else:
            features['soil_moisture_trend'] = 0

        ndvi_last_14 = df_30days['ndvi'].tail(14).values
        if len(ndvi_last_14) >= 2:
            x = np.arange(len(ndvi_last_14))
            features['ndvi_trend'] = np.polyfit(x, ndvi_last_14, 1)[0]
        else:
            features['ndvi_trend'] = 0

        if len(df_context) >= 60:
            features['rainfall_60d_mm'] = float(df_context['rainfall_60d_mm'].iloc[-1])
        else:
            features['rainfall_60d_mm'] = float(df_context['rainfall_mm'].sum())

        if len(df_context) >= 90:
            features['rainfall_90d_mm'] = float(df_context['rainfall_90d_mm'].iloc[-1])
        else:
            features['rainfall_90d_mm'] = float(df_context['rainfall_mm'].sum())

        features['rainfall_anomaly_90d'] = float(df_context['rainfall_anomaly_90d'].iloc[-1])
        features['dry_days_90d'] = float(df_context['dry_days_90d'].iloc[-1])
        features['spi_1m'] = float(df_context['spi_1m'].iloc[-1])
        features['spei_1m'] = float(df_context['spei_1m'].iloc[-1])
        features['spi3_lag7'] = float(df_context['spi3_lag7'].iloc[-1])
        features['spi3_lag30'] = float(df_context['spi3_lag30'].iloc[-1])

        return pd.DataFrame([features])

    def calculate_target_risk(self, df_30days):
        """Drought label = risk score derived from the standard SPI-3 index
        (the accepted definition of meteorological drought): risk = 50 - SPI*15,
        clamped 0-100. SPI <= -1 (moderate drought) maps to risk >= 65."""
        if 'spi3' in df_30days.columns:
            spi_value = df_30days['spi3'].iloc[-1]
        elif 'spi' in df_30days.columns:
            spi_value = df_30days['spi'].iloc[-1]
        else:
            spi_value = None

        if spi_value is None or (isinstance(spi_value, float) and np.isnan(spi_value)):
            return 50.0
        return round(max(0.0, min(100.0, 50.0 - float(spi_value) * 15.0)), 1)

    def _build_samples(self, historical_data, horizon_days=0):
        """Build samples where features are known at day t and the target is the
        SPI-3 risk at day t + horizon_days (0 = nowcast, 7/30 = forecast)."""
        enriched = self._enrich_frame(historical_data)
        features_list = []
        targets = []
        dates = []

        n = len(enriched)
        date_col = 'measurement_date' if 'measurement_date' in enriched.columns else 'date'
        for end in range(30, n - horizon_days + 1):
            context = enriched.iloc[max(0, end - 90):end]
            features_list.append(self.extract_features(context))
            future_end = end + horizon_days
            window = enriched.iloc[future_end - 30:future_end]
            targets.append(self.calculate_target_risk(window))
            dates.append(enriched[date_col].iloc[future_end - 1])

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

        X_train_scaled = self.scaler.fit_transform(X_train)
        X_val_scaled = self.scaler.transform(X_val)

        # Weight drought days much more heavily so the model stops defaulting
        # to "no drought" just because droughts are rare.
        sample_weight = np.where(y_train >= DROUGHT_RISK_THRESHOLD, DROUGHT_WEIGHT, 1.0)
        eval_weight = np.where(y_val >= DROUGHT_RISK_THRESHOLD, DROUGHT_WEIGHT, 1.0)

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
            sample_weight=sample_weight,
            sample_weight_eval_set=[eval_weight],
            eval_set=[(X_val_scaled, y_val)],
            verbose=False,
        )

        suffix = '' if horizon_days == 0 else f'_{horizon_days}d'
        with open(f'xgboost_risk_model{suffix}.pkl', 'wb') as model_file:
            pickle.dump(self.model, model_file)
        with open(f'xgboost_scaler{suffix}.pkl', 'wb') as scaler_file:
            pickle.dump(self.scaler, scaler_file)
        with open(f'xgboost_features{suffix}.pkl', 'wb') as features_file:
            pickle.dump(self.feature_names, features_file)

        self.validation_metrics = self._evaluate(X_val_scaled, y_val, dates[split_idx:])
        self.train_date = timezone.now().isoformat()
        return self

    def load(self, model_path='xgboost_risk_model.pkl', scaler_path='xgboost_scaler.pkl', features_path='xgboost_features.pkl'):
        with open(model_path, 'rb') as model_file:
            self.model = pickle.load(model_file)
        with open(scaler_path, 'rb') as scaler_file:
            self.scaler = pickle.load(scaler_file)
        with open(features_path, 'rb') as features_file:
            self.feature_names = pickle.load(features_file)
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
            'dry_days_90d': 'rainfall_deficit',
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
