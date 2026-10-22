"""Does the new leak-free feature set help the SHIPPED quantile_p25 model?

Walk-forward 2020-2025 on Ichkeul, purge = horizon, comparing the baseline
feature set against the improved one under the production objective.

Run: python scripts/experiment_p25_features.py
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
        'mae': float(mean_absolute_error(actual, pred)),
        'r2': float(r2_score(actual, pred)),
        'n': len(actual),
    }


def main():
    region = Region.objects.first()
    print('Building dataset for %s ...' % region.name, flush=True)
    df = build_spei_dataset(region.id, spei_nmonth=3, merge_points=True)

    for horizon, tcol in [(1, 'spei_target_t1'), (3, 'spei_target_t3')]:
        d = df.dropna(subset=[tcol]).copy()
        d['year'] = d.index.year
        d['_mo'] = _month_ordinal(d)
        y_all = d[tcol].values.astype(float)
        years_all = d['year'].values
        mo_all = d['_mo'].values

        print('\n=== T+%d : quantile_p25 objective ===' % horizon, flush=True)
        print('%-11s %7s %7s %12s %8s %12s %5s' % (
            'features', 'MAE', 'R2', 'drought', 'prec', 'Sev+Ext', 'n'),
            flush=True)
        for name, cols in [('baseline', BASELINE_COLS), ('new_feats', FEATURE_COLS)]:
            X_all = d[cols].values.astype('float32')
            preds, actuals = [], []
            for yr in TEST_YEARS:
                te = years_all == yr
                if te.sum() == 0:
                    continue
                tr = (years_all < yr) & ((mo_all + horizon) < int(mo_all[te].min()))
                if tr.sum() < 100:
                    continue
                m = XGBRegressor(
                    objective='reg:quantileerror', quantile_alpha=0.25,
                    n_estimators=200, max_depth=3, learning_rate=0.05,
                    subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
                    random_state=42, verbosity=0)
                m.fit(X_all[tr], y_all[tr])
                preds.append(m.predict(X_all[te]))
                actuals.append(y_all[te])
            r = class_metrics(np.concatenate(actuals), np.concatenate(preds))
            print('%-11s %7.3f %7.3f %12s %8s %12s %5d' % (
                name, r['mae'], r['r2'],
                r['drought_hits'] + (' (%.0f%%)' % (100 * r['drought_recall'])),
                '%.0f%%' % (100 * r['prec']),
                r['sev_hits'] + (' (%.0f%%)' % (100 * r['sev_recall'])),
                r['n']), flush=True)


if __name__ == '__main__':
    main()
