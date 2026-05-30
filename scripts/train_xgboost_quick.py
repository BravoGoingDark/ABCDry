"""Quick XGBoost regression POC using synthetic risk_score as target.
Generates simple eval metrics and saves a model.
"""
from __future__ import annotations

import argparse
import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.impute import SimpleImputer

try:
    import xgboost as xgb
except Exception:
    xgb = None


def load_and_prepare(path: str, features: list[str], target: str):
    df = pd.read_csv(path, parse_dates=['time', 'created_at', 'updated_at'], low_memory=False)
    df = df.sort_values('time')
    # drop rows without target
    df = df[df[target].notna()].copy()

    X = df[features].copy()
    y = df[target].astype(float).values

    imputer = SimpleImputer(strategy='median')
    X_imputed = imputer.fit_transform(X)
    return X_imputed, y, imputer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', default='scripts/sample_drought_large.csv')
    parser.add_argument('--model-out', default='scripts/xgb_quick.pkl')
    args = parser.parse_args()

    if xgb is None:
        print('xgboost not installed or failed to import. Install xgboost to run this trainer.')
        return

    features = [
        'soil_moisture_pct', 'rainfall_mm', 'irrigation_mm', 'temp_max_c', 'temp_min_c',
        'humidity_pct', 'ndvi', 'ndwi', 'evapotranspiration_etc_mmday', 'satellite_soil_moisture_percent',
        'groundwater_depth_m', 'solar_radiation_wm2', 'days_since_planting', 'crop_coefficient_kc',
        'water_applied_mm'
    ]
    target = 'risk_score'

    X, y, imputer = load_and_prepare(args.input, features, target)

    # time-aware split: last 20% rows as test
    n = X.shape[0]
    cutoff = int(n * 0.8)
    X_train, X_test = X[:cutoff], X[cutoff:]
    y_train, y_test = y[:cutoff], y[cutoff:]

    dtrain = xgb.XGBRegressor(n_estimators=200, max_depth=6, learning_rate=0.1, random_state=42)
    # Fit without advanced early-stopping to remain compatible across xgboost versions
    dtrain.fit(X_train, y_train)

    preds = dtrain.predict(X_test)
    mse = float(np.mean((y_test - preds) ** 2))
    rmse = float(np.sqrt(mse))
    mae = float(np.mean(np.abs(y_test - preds)))
    r2 = float(r2_score(y_test, preds))

    print(f'Test rows: {len(y_test)}')
    print(f'RMSE: {rmse:.3f}, MAE: {mae:.3f}, R2: {r2:.3f}')

    # Save model + imputer
    joblib.dump({'model': dtrain, 'imputer': imputer, 'features': features}, args.model_out)
    print(f'Model saved to {args.model_out}')


if __name__ == '__main__':
    main()
