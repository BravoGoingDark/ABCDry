"""Probe hybrid severity-aware variants: weighted quantile + P30 quantile.

Run: python scripts/probe_severity_variants.py
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

from dashboard.prediction_engine.spei_features import (  # noqa: E402
    FEATURE_COLS,
    _severity_sample_weights,
    build_spei_dataset,
)
from scripts.compare_spei_variants import TEST_YEARS, evaluate  # noqa: E402


def make_model(variant):
    common = dict(n_estimators=200, max_depth=3, learning_rate=0.05,
                  subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
                  random_state=42, verbosity=0)
    if variant == 'q25':
        return XGBRegressor(objective='reg:quantileerror', quantile_alpha=0.25, **common)
    if variant == 'hybrid_w_q25':
        return XGBRegressor(objective='reg:quantileerror', quantile_alpha=0.25, **common)
    if variant == 'hybrid_w_q30':
        return XGBRegressor(objective='reg:quantileerror', quantile_alpha=0.30, **common)
    raise ValueError(variant)


def main():
    print('Building dataset...', flush=True)
    base = build_spei_dataset(4, spei_nmonth=3)
    cols = [c for c in FEATURE_COLS if c in base.columns]

    for horizon, tcol in [('T+1', 'spei_target_t1'), ('T+3', 'spei_target_t3')]:
        d = base.dropna(subset=[tcol] + cols).copy()
        d['year'] = d.index.year
        X_all = d[cols].values
        y_all = d[tcol].values
        years_all = d['year'].values

        print('\n=== %s (walk-forward 2020-2025) ===' % horizon, flush=True)
        print('%-14s %6s %7s %8s %13s %13s %6s' % (
            'variant', 'MAE', 'R2', 'clsAcc%', 'Sev+ExtRec', 'droughtRec', 'FA'),
            flush=True)
        for variant in ['q25', 'hybrid_w_q25', 'hybrid_w_q30']:
            preds, actuals = [], []
            for yr in TEST_YEARS:
                tr_mask = years_all < yr
                te_mask = years_all == yr
                if tr_mask.sum() < 100 or te_mask.sum() == 0:
                    continue
                m = make_model(variant)
                m.fit(X_all[tr_mask], y_all[tr_mask],
                      sample_weight=_severity_sample_weights(y_all[tr_mask]))
                preds.append(m.predict(X_all[te_mask]))
                actuals.append(y_all[te_mask])
            r = evaluate(np.concatenate(actuals), np.concatenate(preds))
            print('%-14s %6.3f %7.3f %8.1f %10s %12s %8s %6d' % (
                variant, r['mae'], r['r2'], 100 * r['class_acc'],
                r['sev_ext_hits'] + ' (%.0f%%)' % (100 * r['sev_ext_recall']),
                r['drought_hits'] + ' (%.0f%%)' % (100 * r['drought_recall']),
                r['false_alarms'], r['sev_ext_fp']), flush=True)
    print('\nDONE', flush=True)


if __name__ == '__main__':
    main()
