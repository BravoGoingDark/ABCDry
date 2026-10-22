"""Evaluate T+1/T+3 SPEI model improvements with purged walk-forward.

Compares, per horizon:
  baseline      : pre-improvement feature set (no SPEI lags, no climatology,
                  raw month int), purge gap = horizon (leak-free)
  +new_feats    : adds spei_lag1/2/3/6, bal_3m/12m, past-only expanding
                  rain/ET0 climatology, cyclic month encoding
  +delta        : same features, model learns SPEI(t+h) - SPEI(t)
  +quantile_p25 : same features, risk-averse 25th-percentile objective
  persistence   : SPEI(t+h) := SPEI(t) -- the bar the ML must clear

Every variant is trained with a purge gap EQUAL TO THE HORIZON, so T+3
training targets can never overlap the test months (the old code purged a
fixed 1 month, which leaked at T+3).

Run: python scripts/experiment_spei_improvements.py
"""
import os
import sys

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')
os.chdir(BASE_DIR)

import django  # noqa: E402

django.setup()

from xgboost import XGBRegressor  # noqa: E402
from sklearn.metrics import mean_absolute_error, r2_score  # noqa: E402

from dashboard.models import Region  # noqa: E402
from dashboard.prediction_engine.spei_features import (  # noqa: E402
    FEATURE_COLS, _severity_class, _month_ordinal, build_spei_dataset,
)

TEST_YEARS = [2020, 2021, 2022, 2023, 2024, 2025]

NEW_FEATS = [
    'spei_lag1', 'spei_lag2', 'spei_lag3', 'spei_lag6',
    'bal_3m', 'bal_12m',
    'rain_clim_n1', 'rain_clim_n3', 'et0_clim_n1', 'et0_clim_n3',
    'month_sin', 'month_cos',
]
BASELINE_COLS = [c for c in FEATURE_COLS if c not in NEW_FEATS]


def make_model(variant):
    if variant == 'quantile_p25':
        return XGBRegressor(
            objective='reg:quantileerror', quantile_alpha=0.25,
            n_estimators=200, max_depth=3, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
            random_state=42, verbosity=0)
    if variant == 'delta':
        return XGBRegressor(
            n_estimators=300, max_depth=4, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8,
            random_state=42, verbosity=0)
    return XGBRegressor(
        n_estimators=300, max_depth=5, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8,
        random_state=42, verbosity=0)


def class_metrics(actual, pred):
    ac = [_severity_class(v) for v in actual]
    pc = [_severity_class(v) for v in pred]
    sa = [c in ('Severe', 'Extreme') for c in ac]
    sp = [c in ('Severe', 'Extreme') for c in pc]
    s_tp = sum(1 for a, p in zip(sa, sp) if a and p)
    n_sev = sum(sa)
    abin = [0 if c == 'Low' else 1 for c in ac]
    pbin = [0 if c == 'Low' else 1 for c in pc]
    tp = sum(1 for a, p in zip(abin, pbin) if a and p)
    fn = sum(1 for a, p in zip(abin, pbin) if a and not p)
    fp = sum(1 for a, p in zip(abin, pbin) if not a and p)
    n_d = tp + fn
    return {
        'drought_recall': tp / n_d if n_d else 0.0,
        'drought_hits': '%d/%d' % (tp, n_d),
        'fa': fp,
        'prec': tp / (tp + fp) if (tp + fp) else 0.0,
        'sev_recall': s_tp / n_sev if n_sev else 0.0,
        'sev_hits': '%d/%d' % (s_tp, n_sev),
    }


def walk_forward(df, cols, tcol, horizon, variant):
    """Year-by-year walk-forward with horizon-length purge. Returns (metrics, preds)."""
    # XGBoost routes missing feature values natively, so only the target
    # must be known (and, for delta mode, the current-SPEI base).
    d = df.dropna(subset=[tcol]).copy()
    d['year'] = d.index.year
    d['_mo'] = _month_ordinal(d)
    X_all = d[cols].values.astype('float32')
    y_all = d[tcol].values.astype(float)
    years_all = d['year'].values
    mo_all = d['_mo'].values

    preds, actuals = [], []
    for yr in TEST_YEARS:
        te = years_all == yr
        if te.sum() == 0:
            continue
        year_start = int(mo_all[te].min())
        tr = (years_all < yr) & ((mo_all + horizon) < year_start)
        if tr.sum() < 100:
            continue
        m = make_model(variant)
        if variant == 'delta':
            cur = d['spei_current'].values.astype(float)
            keep = ~np.isnan(cur[tr])
            m.fit(X_all[tr][keep], (y_all[tr] - cur[tr])[keep])
            p = cur[te] + m.predict(X_all[te])
        else:
            m.fit(X_all[tr], y_all[tr])
            p = m.predict(X_all[te])
        preds.append(p)
        actuals.append(y_all[te])

    p = np.concatenate(preds)
    a = np.concatenate(actuals)
    cm = class_metrics(a, p)
    cm.update({
        'mae': float(mean_absolute_error(a, p)),
        'r2': float(r2_score(a, p)),
        'n': len(a),
    })
    return cm


def persistence_cm(df, tcol, horizon, years=TEST_YEARS):
    dp = df.dropna(subset=[tcol, 'spei_current']).copy()
    dp = dp[dp.index.year.isin(years)]
    a, p = dp[tcol].values, dp['spei_current'].values.astype(float)
    cm = class_metrics(a, p)
    cm.update({
        'mae': float(mean_absolute_error(a, p)),
        'r2': float(r2_score(a, p)),
        'n': len(a),
    })
    return cm


def main():
    region = Region.objects.first()
    print('Building dataset for %s ...' % region.name, flush=True)
    df = build_spei_dataset(region.id, spei_nmonth=3, merge_points=True)
    print('rows: %d  %s -> %s' % (len(df), df.index.min(), df.index.max()),
          flush=True)

    variants = [
        ('baseline', BASELINE_COLS, None),
        ('new_feats', FEATURE_COLS, None),
        ('delta', FEATURE_COLS, 'delta'),
        ('quantile_p25', FEATURE_COLS, 'quantile_p25'),
    ]

    for horizon, tcol in [(1, 'spei_target_t1'), (3, 'spei_target_t3')]:
        print('\n=== T+%d  (purged walk-forward 2020-2025) ===' % horizon,
              flush=True)
        print('%-13s %7s %7s %9s %9s %10s %8s %5s' % (
            'variant', 'MAE', 'R2', 'drought', 'droughtP', 'Sev+Ext', 'FA', 'n'),
            flush=True)
        pers = persistence_cm(df, tcol, horizon)
        print('%-13s %7.3f %7.3f %9s %9s %10s %8s %5d' % (
            'persistence', pers['mae'], pers['r2'],
            pers['drought_hits'] + (' (%.0f%%)' % (100 * pers['drought_recall'])),
            '%.0f%%' % (100 * pers['prec']),
            pers['sev_hits'] + (' (%.0f%%)' % (100 * pers['sev_recall'])),
            pers['fa'], pers['n']), flush=True)
        for name, cols, mode in variants:
            r = walk_forward(df, cols, tcol, horizon, mode or 'regression')
            print('%-13s %7.3f %7.3f %9s %9s %10s %8s %5d' % (
                name, r['mae'], r['r2'],
                r['drought_hits'] + (' (%.0f%%)' % (100 * r['drought_recall'])),
                '%.0f%%' % (100 * r['prec']),
                r['sev_hits'] + (' (%.0f%%)' % (100 * r['sev_recall'])),
                r['fa'], r['n']), flush=True)


if __name__ == '__main__':
    main()
