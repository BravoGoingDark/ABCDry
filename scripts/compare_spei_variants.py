"""Compare SPEI forecast model variants with walk-forward validation.

Variants: regression (baseline), weighted (severity-weighted),
quantile_p25 (risk-averse), plus the persistence benchmark.

Run: python scripts/compare_spei_variants.py
"""
import os
import sys

import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')
os.chdir(BASE_DIR)

import django  # noqa: E402

django.setup()

from xgboost import XGBRegressor  # noqa: E402
from sklearn.metrics import mean_absolute_error, r2_score  # noqa: E402

from dashboard.prediction_engine.spei_features import (  # noqa: E402
    FEATURE_COLS,
    _severity_class,
    _severity_sample_weights,
    build_spei_dataset,
)

TEST_YEARS = [2020, 2021, 2022, 2023, 2024, 2025]
VARIANTS = ['regression', 'weighted', 'quantile_p25']


def make_model(variant):
    if variant == 'quantile_p25':
        return XGBRegressor(
            objective='reg:quantileerror', quantile_alpha=0.25,
            n_estimators=200, max_depth=3, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
            random_state=42, verbosity=0)
    if variant == 'weighted':
        return XGBRegressor(
            n_estimators=200, max_depth=3, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
            random_state=42, verbosity=0)
    return XGBRegressor(
        n_estimators=300, max_depth=5, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8,
        random_state=42, verbosity=0)


def fit_variant(variant, X, y):
    model = make_model(variant)
    if variant == 'weighted':
        model.fit(X, y, sample_weight=_severity_sample_weights(y))
    else:
        model.fit(X, y)
    return model


def evaluate(actual, pred):
    ac = [_severity_class(v) for v in actual]
    pc = [_severity_class(v) for v in pred]
    acc = float(np.mean([a == p for a, p in zip(ac, pc)]))
    # Severe+Extreme band detection (merged class)
    sa = [c in ('Severe', 'Extreme') for c in ac]
    sp = [c in ('Severe', 'Extreme') for c in pc]
    s_tp = sum(1 for a, p in zip(sa, sp) if a and p)
    s_fn = sum(1 for a, p in zip(sa, sp) if a and not p)
    s_fp = sum(1 for a, p in zip(sa, sp) if p and not a)
    # drought (any non-Low class) detection
    abin = [0 if c == 'Low' else 1 for c in ac]
    pbin = [0 if c == 'Low' else 1 for c in pc]
    tp = sum(1 for a, p in zip(abin, pbin) if a == 1 and p == 1)
    fn = sum(1 for a, p in zip(abin, pbin) if a == 1 and p == 0)
    fp = sum(1 for a, p in zip(abin, pbin) if a == 0 and p == 1)
    n_drought = tp + fn
    n_sev = s_tp + s_fn
    return {
        'mae': float(mean_absolute_error(actual, pred)),
        'r2': float(r2_score(actual, pred)),
        'class_acc': acc,
        'sev_ext_recall': s_tp / n_sev if n_sev else 0.0,
        'sev_ext_hits': '%d/%d' % (s_tp, n_sev),
        'sev_ext_fp': s_fp,
        'drought_recall': tp / n_drought if n_drought else 0.0,
        'drought_hits': '%d/%d' % (tp, n_drought),
        'false_alarms': fp,
    }


def main():
    print('Building dataset...')
    base = build_spei_dataset(4, spei_nmonth=3)
    cols = [c for c in FEATURE_COLS if c in base.columns]

    # Persistence predictions: SPEI(t+h) := SPEI(t)
    for h in (1, 3):
        base['persist_t%d' % h] = base.groupby(
            ['latitude', 'longitude'])['spei_target'].shift(h)

    for horizon, tcol in [('T+1', 'spei_target_t1'), ('T+3', 'spei_target_t3')]:
        h = 1 if horizon == 'T+1' else 3
        d = base.dropna(subset=[tcol]).copy()
        d['year'] = d.index.year
        X_all = d[cols].values
        y_all = d[tcol].values
        years_all = d['year'].values

        results = {}
        for variant in VARIANTS:
            preds, actuals = [], []
            for yr in TEST_YEARS:
                tr_mask = years_all < yr
                te_mask = years_all == yr
                if tr_mask.sum() < 100 or te_mask.sum() == 0:
                    continue
                model = fit_variant(variant, X_all[tr_mask], y_all[tr_mask])
                preds.append(model.predict(X_all[te_mask]))
                actuals.append(y_all[te_mask])
            results[variant] = evaluate(np.concatenate(actuals),
                                        np.concatenate(preds))

        dp = base.dropna(subset=[tcol, 'persist_t%d' % h]).copy()
        dp['year'] = dp.index.year
        dp = dp[dp['year'].isin(TEST_YEARS)]
        results['persistence'] = evaluate(
            dp[tcol].values, dp['persist_t%d' % h].values)

        print('\n=== %s (walk-forward 2020-2025) ===' % horizon)
        print('%-14s %6s %7s %8s %13s %13s %6s' % (
            'variant', 'MAE', 'R2', 'clsAcc%', 'Sev+ExtRec', 'droughtRec', 'FA'))
        for variant in VARIANTS + ['persistence']:
            r = results[variant]
            print('%-14s %6.3f %7.3f %8.1f %10s %12s %8s %6d' % (
                variant, r['mae'], r['r2'], 100 * r['class_acc'],
                r['sev_ext_hits'] + ' (%.0f%%)' % (100 * r['sev_ext_recall']),
                r['drought_hits'] + ' (%.0f%%)' % (100 * r['drought_recall']),
                r['false_alarms'], r['sev_ext_fp']))


if __name__ == '__main__':
    main()
