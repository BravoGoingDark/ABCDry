import pickle

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

try:
    import xgboost as xgb
except ImportError:  # pragma: no cover - optional dependency guard
    xgb = None

from .physical_helpers import calculate_etc


class XGBoostDroughtRiskPredictor:
    """Predicts today's drought risk score and returns feature-importance drivers."""

    def __init__(self):
        self.model = None
        self.scaler = StandardScaler()
        self.feature_names = None

    def _require_xgboost(self):
        if xgb is None:
            raise ImportError("xgboost is required for XGBoostDroughtRiskPredictor. Install requirements.txt.")

    def extract_features(self, df_30days):
        features = {}

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

        return pd.DataFrame([features])

    def calculate_target_risk(self, df_30days, awc_mm, field_capacity_pct):
        current_soil_mm = df_30days['soil_water_mm'].iloc[-1] if 'soil_water_mm' in df_30days.columns else None

        if current_soil_mm and awc_mm:
            soil_risk = (1 - min(1, current_soil_mm / awc_mm)) * 100
        else:
            current_moisture = df_30days['soil_moisture_pct'].iloc[-1]
            soil_risk = (1 - min(1, current_moisture / field_capacity_pct)) * 100

        ndvi = df_30days['ndvi'].iloc[-1]
        ndvi_penalty = max(0, (0.8 - min(0.8, ndvi)) / 0.8) * 20

        spi_value = df_30days['spi'].iloc[-1] if 'spi' in df_30days.columns else 0
        spi_penalty = max(0, -spi_value) * 10

        risk = min(100, soil_risk + ndvi_penalty + spi_penalty)
        return round(risk, 1)

    def train(self, historical_data, awc_mm, field_capacity_pct):
        self._require_xgboost()
        features_list = []
        targets = []

        for i in range(len(historical_data) - 30):
            window = historical_data.iloc[i:i + 30].copy()

            if 'etc_mm' not in window.columns:
                window['etc_mm'] = window.apply(
                    lambda row: calculate_etc(row.get('et0_mm', row.get('et0', 3.0)), 1.0),
                    axis=1,
                )

            features_list.append(self.extract_features(window))
            targets.append(self.calculate_target_risk(window, awc_mm, field_capacity_pct))

        if not features_list:
            raise ValueError('Not enough data to train XGBoost risk model.')

        X = pd.concat(features_list, ignore_index=True)
        y = np.array(targets)
        self.feature_names = X.columns.tolist()

        X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=42)
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_val_scaled = self.scaler.transform(X_val)

        self.model = xgb.XGBRegressor(
            n_estimators=150,
            max_depth=5,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            early_stopping_rounds=20,
            eval_metric='mae',
        )
        self.model.fit(X_train_scaled, y_train, eval_set=[(X_val_scaled, y_val)], verbose=False)

        with open('xgboost_risk_model.pkl', 'wb') as model_file:
            pickle.dump(self.model, model_file)
        with open('xgboost_scaler.pkl', 'wb') as scaler_file:
            pickle.dump(self.scaler, scaler_file)
        with open('xgboost_features.pkl', 'wb') as features_file:
            pickle.dump(self.feature_names, features_file)

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
        X = self.extract_features(df_30days)
        X_scaled = self.scaler.transform(X)
        risk = self.model.predict(X_scaled)[0]
        return round(float(max(0, min(100, risk))), 1)

    def get_drivers(self, df_30days):
        X = self.extract_features(df_30days)
        _ = self.scaler.transform(X)

        importance = getattr(self.model, 'feature_importances_', np.zeros(len(self.feature_names or [])))

        driver_mapping = {
            'rainfall_30d_mm': 'rainfall_deficit',
            'rainfall_7d_mm': 'rainfall_deficit',
            'soil_moisture_pct': 'soil_moisture_decline',
            'soil_moisture_trend': 'soil_moisture_decline',
            'temp_anomaly_c': 'high_temperature',
            'ndvi': 'vegetation_stress',
            'ndvi_trend': 'vegetation_stress',
            'etc_7d_avg_mm': 'high_evapotranspiration',
            'days_since_last_rain': 'rainfall_deficit',
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