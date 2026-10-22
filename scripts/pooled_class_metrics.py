"""Precision/recall/accuracy for the POOLED multi-region model.

Uses the same 80/20 chronological split as train_spei_pooled (which, given
region-ordered concatenation, holds out Ichkeul + recent Bizerte years - i.e.
a quasi unseen-region test).
"""
import os
import sys

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')
os.chdir(BASE_DIR)

import django
django.setup()

from xgboost import XGBRegressor
from dashboard.models import Region
from dashboard.prediction_engine.spei_features import (
    FEATURE_COLS, _severity_sample_weights, build_spei_dataset,
)
from scripts.compare_spei_variants import evaluate

print('Building pooled dataset...', flush=True)
dfs = []
for region in Region.objects.filter(latitude__isnull=False):
    try:
        d = build_spei_dataset(region.id, spei_nmonth=3)
    except Exception:
        continue
    if not d.empty:
        dfs.append(d)

pool = pd.concat(dfs)
cols = [c for c in FEATURE_COLS if c in pool.columns]
print('pooled rows:', len(pool), flush=True)

for tname, tcol in [('T+1', 'spei_target_t1'), ('T+3', 'spei_target_t3')]:
    d = pool.dropna(subset=[tcol] + cols)
    n = len(d)
    split = int(n * 0.8)
    tr, te = d.iloc[:split], d.iloc[split:]
    m = XGBRegressor(objective='reg:quantileerror', quantile_alpha=0.25,
                     n_estimators=200, max_depth=3, learning_rate=0.05,
                     subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
                     random_state=42, verbosity=0)
    m.fit(tr[cols].values, tr[tcol].values)
    pred = m.predict(te[cols].values)
    act = te[tcol].values
    r = evaluate(act, pred)
    tp = int(r['drought_hits'].split('/')[0]); ndr = int(r['drought_hits'].split('/')[1])
    prec = tp / (tp + r['false_alarms']) if (tp + r['false_alarms']) else 0
    sp = int(r['sev_ext_hits'].split('/')[0]); nsev = int(r['sev_ext_hits'].split('/')[1])
    print()
    print('=== POOLED %s (holdout n=%d) ===' % (tname, len(te)), flush=True)
    print(' drought recall      : %d/%d = %.0f%%' % (tp, ndr, 100*r['drought_recall']))
    print(' drought precision   : %d/%d = %.0f%%' % (tp, tp + r['false_alarms'], 100*prec))
    print(' exact class accuracy: %.1f%%' % (100*r['class_acc']))
    print(' Sev+Ext recall      : %s = %.0f%%' % (r['sev_ext_hits'], 100*r['sev_ext_recall']))
    print(' MAE=%.3f  R2=%.3f' % (r['mae'], r['r2']), flush=True)
