"""Inspect a trained synthetic XGBoost model with feature importances and partial dependence.

Usage:
    python scripts/analyze_xgboost_poc.py --input scripts/sample_drought_large.csv --model scripts/xgb_quick.pkl
"""
from __future__ import annotations

import argparse
from pathlib import Path

import joblib
import numpy as np
import pandas as pd


def compute_partial_dependence(model, X: np.ndarray, feature_index: int, grid: np.ndarray) -> list[float]:
    baseline = X.copy()
    outputs: list[float] = []
    for value in grid:
        modified = baseline.copy()
        modified[:, feature_index] = value
        outputs.append(float(np.mean(model.predict(modified))))
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', default='scripts/sample_drought_large.csv')
    parser.add_argument('--model', default='scripts/xgb_quick.pkl')
    parser.add_argument('--top-k', type=int, default=10)
    args = parser.parse_args()

    bundle = joblib.load(args.model)
    model = bundle['model']
    imputer = bundle['imputer']
    features = bundle['features']

    df = pd.read_csv(args.input, low_memory=False)
    X = imputer.transform(df[features])

    importances = getattr(model, 'feature_importances_', None)
    if importances is None:
        raise RuntimeError('Model does not expose feature_importances_.')

    ranked = sorted(zip(features, importances), key=lambda item: item[1], reverse=True)
    print('Top feature importances:')
    for name, score in ranked[: args.top_k]:
        print(f'  {name:35s} {score:.4f}')

    print('\nPartial dependence (average prediction across a small value grid):')
    for name, _ in ranked[: min(3, len(ranked))]:
        index = features.index(name)
        series = pd.to_numeric(df[name], errors='coerce').dropna()
        if series.empty:
            continue
        grid = np.quantile(series.to_numpy(), np.linspace(0.1, 0.9, 5))
        values = compute_partial_dependence(model, X, index, grid)
        print(f'  {name}:')
        for grid_value, pred_value in zip(grid, values):
            print(f'    {grid_value:10.4f} -> {pred_value:8.3f}')


if __name__ == '__main__':
    main()
