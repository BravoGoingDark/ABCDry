# -*- coding: utf-8 -*-
import os, sys, django, warnings as W, numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
W.filterwarnings("ignore")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "agri_dashboard.settings")
django.setup()
from xgboost import XGBRegressor
from sklearn.metrics import r2_score, mean_absolute_error
from dashboard.models import Region
from dashboard.prediction_engine.spei_features import build_spei_dataset, FEATURE_COLS

r = Region.objects.get(name="Ichkeul")

def add_vci(df, window=60):
    """VCI = 100*(NDVI - min)/(max - min) over a trailing window."""
    s = df['ndvi'].astype(float)
    v = pd.Series(np.nan, index=df.index)
    for i in range(len(s)):
        if i < 12: continue
        w = s.iloc[max(0, i-window):i+1].dropna()
        if len(w) < 24: continue
        lo, hi = w.min(), w.max()
        if hi > lo: v.iloc[i] = 100.0 * (s.iloc[i] - lo) / (hi - lo)
    return df.assign(vci=v)

def walk(d, t="spei_target_t1", minrows=96):
    d = d.dropna(subset=[t, "spei_current"]).dropna(axis=1, how="all")
    cols = [c for c in FEATURE_COLS if c in d.columns] + \
           [c for c in ("vci",) if c in d.columns]
    X = d[cols].apply(pd.to_numeric, errors="coerce").values.astype("float32")
    y = d[t].values.astype(float); cur = d["spei_current"].values.astype(float)
    P, Y, C = [], [], []
    for i in range(minrows, len(d)):
        m = XGBRegressor(n_estimators=300, max_depth=4, learning_rate=0.05,
                         subsample=0.8, colsample_bytree=0.8,
                         objective="reg:squarederror", tree_method="hist",
                         random_state=42, n_jobs=2)
        m.fit(X[:i], y[:i])
        P.append(float(m.predict(X[i:i+1])[0])); Y.append(y[i]); C.append(cur[i])
    Y=np.array(Y); P=np.array(P); C=np.array(C)
    return (r2_score(Y,P), mean_absolute_error(Y,P), r2_score(Y,C),
            mean_absolute_error(Y,C), len(Y), len(cols))

base = build_spei_dataset(r.id, merge_points=True)
rows=[]
rows.append(("A baseline (SPEI-3, 36 feat)", walk(base)))
rows.append(("B + VCI from NDVI",            walk(add_vci(base.copy()))))
for nm in (6, 12):
    d6 = build_spei_dataset(r.id, spei_nmonth=nm, merge_points=True)
    rows.append(("C SPEI-%d instead of 3" % nm, walk(d6)))

print("=== T+1 walk-forward, Ichkeul ===\n")
print("%-30s %-22s %-22s" % ("config", "MODEL (R2 / MAE)", "persistence (R2 / MAE)"))
for n,(r2m,maem,r2p,maep,nn,nf) in rows:
    print("%-30s %+.3f / %.3f          %+.3f / %.3f   (n=%d, f=%d)"
          % (n, r2m, maem, r2p, maep, nn, nf))
