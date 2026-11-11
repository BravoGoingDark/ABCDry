"""Gridded SPEI drought forecast for the 29 Ichkeul ERA5-Land cells.

Science summary (see docs/DROUGHT_GRID_FORECAST.md for the full write-up)
-------------------------------------------------------------------------
* Inputs per 0.1° cell, monthly, 1981 -> present:
    - precipitation  : CHIRPS v2 daily, summed (UCSB-CHG/CHIRPS/DAILY)
    - ET0            : FAO-56 Penman-Monteith from ERA5-Land daily aggregates
                       (Tmax, Tmin, dew point, 10 m wind, downward shortwave)
    - soil moisture  : ERA5-Land volumetric soil water, layers 1-2 (0-28 cm)
* Index: SPEI-k (Vicente-Serrano et al. 2010), k = 1, 3, 6, 12, 24. Climatic water
  balance D = P - ET0 accumulated over k months, a generalised-logistic
  (3-parameter log-logistic) distribution fitted per cell and calendar month
  by unbiased probability-weighted moments / L-moments (Hosking 1997, as in
  the reference SPEI package) on the WMO 1981-2010 reference period,
  probabilities transformed to a standard normal. Maximum likelihood is NOT
  used: for a location-bounded distribution it drags the bound onto the
  sample minimum, so any month just beyond the record would read as SPEI -3.7.
* Model: ridge regression on standardised predictors, one model per
  (scale k, lead h), pooled over the 29 cells. XGBoost was benchmarked and did
  not beat ridge out of sample; ridge also gives an exact additive attribution
  of each forecast to its drivers.
* Uncertainty: Gaussian predictive distribution whose sigma is the
  OUT-OF-SAMPLE RMSE of that (k, h) — so the drought probability is calibrated
  to the verified error, not the in-sample fit.
* Verification: expanding-window, refit every year 2011 -> last year. A
  training row is allowed only if its TARGET month precedes the first issue
  month of the test year, so no observation used for scoring is ever seen.
* A lead time is published as "skilful" only if, out of sample, the drought
  event (SPEI <= -1) is discriminated with ROC AUC >= 0.75 AND the mean-square
  skill score against climatology is >= 0.20. Beyond that the honest forecast
  is climatology and the map says so.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from django.conf import settings
from scipy import stats
from sklearn.linear_model import Ridge

from .physical_helpers import fao56_et0

logger = logging.getLogger(__name__)

SCALES = (3, 6, 12, 24)        # published scales (SPEI-1 has no skill past nowcast)
FEATURE_SCALES = (1, 3, 6, 12)  # predictors shared by every model
INDEX_SCALES = (1, 3, 6, 12, 24)  # every index computed (features + targets)
LEADS = tuple(range(1, 13))
REF_START, REF_END = 1981, 2010
VERIFY_START = 2011
DROUGHT_THRESHOLD = -1.0       # SPEI <= -1: moderate drought or worse (McKee et al. 1993)
SKILL_MIN_AUC = 0.75
SKILL_MIN_MSSS = 0.20
RIDGE_ALPHA = 10.0
MODEL_VERSION = 'grid-spei-scenarios-v3'   # published forecast: scenario ensemble
RIDGE_VERSION = 'grid-spei-ridge-v2'       # companion linear model (driver attribution)

SCALE_INFO = {
    3: {'label': 'SPEI-3', 'kind': 'agricultural',
        'meaning': 'Root-zone water over the last 3 months: rainfed crops, sowing and early growth.'},
    6: {'label': 'SPEI-6', 'kind': 'agricultural / hydrological',
        'meaning': 'Half-season water balance: crop yield, soil reserves and stream flow.'},
    12: {'label': 'SPEI-12', 'kind': 'hydrological',
         'meaning': 'One-year water balance: reservoirs, groundwater and inflow to Lake Ichkeul.'},
    24: {'label': 'SPEI-24', 'kind': 'long-term hydrological',
         'meaning': 'Two-year water balance: multi-year drought, large dams and aquifer recharge.'},
}

DRIVER_GROUPS = {
    'memory_long': 'Long-term water deficit already accumulated (6-24 months)',
    'memory_short': 'Recent water balance (last 1-3 months)',
    'rain': 'Last month rainfall anomaly',
    'heat': 'Evaporative demand and temperature (ET0, heat)',
    'soil': 'Soil moisture (0-28 cm)',
    'season': 'Season of the target month',
}


def _driver_group(feature):
    if feature.startswith(('spei6', 'spei12', 'spei24')):
        return 'memory_long'
    if feature.startswith(('spei1', 'spei3')):
        return 'memory_short'
    if feature == 'P_a':
        return 'rain'
    if feature in ('PET_a', 'T_a'):
        return 'heat'
    if feature.startswith('SM_a'):
        return 'soil'
    if feature in ('tsin', 'tcos'):
        return 'season'
    return None  # lat / lon: location offsets, not reported as drivers


BASE_FEATURES = (
    [f'spei{k}' for k in FEATURE_SCALES]
    + [f'spei{k}_l1' for k in FEATURE_SCALES]
    + [f'spei{k}_l2' for k in FEATURE_SCALES]
    + ['P_a', 'PET_a', 'T_a', 'SM_a', 'SM_a_l1', 'lat', 'lon']
)


def features_for(k):
    """Predictors of the SPEI-k models. Scales longer than the shared feature
    set add their own index and lags, so the SPEI-3/6/12 models are unchanged."""
    if k in FEATURE_SCALES:
        return BASE_FEATURES
    return BASE_FEATURES + [f'spei{k}', f'spei{k}_l1', f'spei{k}_l2']


# --------------------------------------------------------------------------- #
# Grid geometry
# --------------------------------------------------------------------------- #

def basin_geojson_path():
    for base in [Path(settings.BASE_DIR) / 'static', *[Path(p) for p in getattr(settings, 'STATICFILES_DIRS', [])]]:
        p = base / 'dashboard' / 'data' / 'ichkeul_basin.geojson'
        if p.exists():
            return p
    raise FileNotFoundError('ichkeul_basin.geojson not found')


def load_cells():
    """[{id, coords (GeoJSON ring list), lat, lon, km2}] for the 29 sections."""
    data = json.loads(basin_geojson_path().read_text(encoding='utf-8'))
    cells = []
    for f in data['features']:
        props = f['properties']
        if props.get('kind') != 'section':
            continue
        ring = np.array(f['geometry']['coordinates'][0], dtype=float)
        cells.append({
            'id': props['id'],
            'coords': f['geometry']['coordinates'],
            'lat': float(ring[:, 1].mean()),
            'lon': float(ring[:, 0].mean()),
            'km2': props.get('km2'),
        })
    return cells


# --------------------------------------------------------------------------- #
# Data access (Google Earth Engine)
# --------------------------------------------------------------------------- #

ERA_BANDS = ['temperature_2m_max', 'temperature_2m_min', 'temperature_2m', 'dewpoint_temperature_2m',
             'u_component_of_wind_10m', 'v_component_of_wind_10m',
             'surface_solar_radiation_downwards_sum',
             'volumetric_soil_water_layer_1', 'volumetric_soil_water_layer_2']


def last_complete_chirps_month(ee):
    """First day of the last calendar month fully covered by CHIRPS daily."""
    ic = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY')
    last = ee.Date(ic.aggregate_max('system:time_start')).format('YYYY-MM-dd').getInfo()
    d = date.fromisoformat(last)
    nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    if (nxt - d).days == 1:            # last day of month present
        return date(d.year, d.month, 1)
    return date(d.year - (d.month == 1), (d.month - 2) % 12 + 1, 1)


def fetch_cell_months(ee, months, log=print):
    """Fetch CHIRPS + ERA5-Land monthly aggregates for every cell and month.

    `months` are 'YYYY-MM-01' strings. Returns a list of dicts.
    """
    import time

    cells = load_cells()
    fc = ee.FeatureCollection([
        ee.Feature(ee.Geometry.Polygon(c['coords']), {'cell': c['id']}) for c in cells
    ])
    chirps = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY')
    era = ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR')

    def month_fc(ms):
        start = ee.Date(ms)
        end = start.advance(1, 'month')
        img = chirps.filterDate(start, end).sum().rename('chirps').addBands(
            era.filterDate(start, end).select(ERA_BANDS).mean())
        return img.reduceRegions(fc, ee.Reducer.mean(), scale=5000).map(
            lambda f: f.set('month', ms).setGeometry(None))

    rows = []
    for i in range(0, len(months), 12):   # EE limits concurrent aggregations
        chunk = months[i:i + 12]
        for attempt in range(6):
            try:
                res = ee.FeatureCollection(ee.List(chunk).map(month_fc)).flatten().getInfo()
                break
            except ee.EEException as exc:
                log(f'  Earth Engine busy ({exc}); retrying')
                time.sleep(5 * (attempt + 1))
        else:
            raise RuntimeError(f'Earth Engine fetch failed for {chunk[0]}')
        rows.extend(f['properties'] for f in res['features'])
        log(f'  fetched {chunk[0][:7]} -> {chunk[-1][:7]}')
    return rows


# --------------------------------------------------------------------------- #
# Indices and features
# --------------------------------------------------------------------------- #

def _svp(t):
    return 0.6108 * np.exp(17.27 * t / (t + 237.3))


def prepare_frame(records):
    """records: iterable of GridCellClimate-like dicts -> monthly frame with D, anomalies."""
    cells = {c['id']: c for c in load_cells()}
    df = pd.DataFrame.from_records(records)
    df['month'] = pd.PeriodIndex(pd.to_datetime(df['month']), freq='M')
    df = df[df.cell.isin(cells)].sort_values(['cell', 'month']).reset_index(drop=True)
    tmean = df.tmean_c.astype(float)
    rh = np.clip(100 * _svp(df.tdew_c.astype(float)) / _svp(tmean), 1, 100)
    df['lat'] = df.cell.map(lambda c: cells[c]['lat'])
    df['lon'] = df.cell.map(lambda c: cells[c]['lon'])
    doy = df.month.dt.to_timestamp().dt.dayofyear + 14
    df['ET0'] = [
        fao56_et0(a, b, c, d, e, la, dy) if None not in (a, b, c, d, e) and not any(
            isinstance(x, float) and math.isnan(x) for x in (a, b, c, d, e)) else np.nan
        for a, b, c, d, e, la, dy in zip(df.tmax_c, df.tmin_c, df.solar_mj, rh, df.wind_ms, df.lat, doy)
    ]
    df['P'] = df.precip_mm.astype(float)
    df['PET'] = df.ET0 * df.month.dt.days_in_month
    df['D'] = df.P - df.PET
    df['T'] = tmean
    df['SM'] = df.soil_moisture.astype(float)
    df['moy'] = df.month.dt.month
    return df


def glo_fit(x):
    """Generalised-logistic parameters (xi, alpha, kappa) by L-moments."""
    x = np.sort(np.asarray(x, dtype=float))
    n = len(x)
    i = np.arange(1, n + 1)
    b0 = x.mean()
    b1 = np.sum((i - 1) / (n - 1) * x) / n
    b2 = np.sum((i - 1) * (i - 2) / ((n - 1) * (n - 2)) * x) / n
    l1, l2, l3 = b0, 2 * b1 - b0, 6 * b2 - 6 * b1 + b0
    kappa = -l3 / l2
    if abs(kappa) < 1e-6:
        return l1, l2, 0.0
    alpha = l2 * np.sin(kappa * np.pi) / (kappa * np.pi)
    xi = l1 - alpha * (1 / kappa - np.pi / np.sin(kappa * np.pi))
    return xi, alpha, kappa


def glo_cdf(x, xi, alpha, kappa):
    x = np.asarray(x, dtype=float)
    if kappa == 0:
        y = (x - xi) / alpha
    else:
        arg = 1 - kappa * (x - xi) / alpha
        inside = arg > 0
        y = np.where(inside, -np.log(np.where(inside, arg, 1.0)) / kappa,
                     np.inf if kappa > 0 else -np.inf)
    return 1 / (1 + np.exp(-y))


def _spei_for_cell(g, k, ref_mask):
    acc = g['D'].rolling(k, min_periods=k).sum()
    out = pd.Series(np.nan, index=g.index)
    for m in range(1, 13):
        sel = (g.moy == m)
        ref = acc[sel & ref_mask.loc[g.index]].dropna()
        if len(ref) < 15:
            continue
        vals = acc[sel]
        z = stats.norm.ppf(np.clip(glo_cdf(vals, *glo_fit(ref)), 1e-4, 1 - 1e-4))
        out[sel] = np.where(vals.isna(), np.nan, z)
    return out


def add_indices(df):
    ref_mask = (df.month.dt.year >= REF_START) & (df.month.dt.year <= REF_END)
    for k in INDEX_SCALES:
        df[f'spei{k}'] = pd.concat(
            [_spei_for_cell(g, k, ref_mask) for _, g in df.groupby('cell')]).sort_index()
    ref = df[ref_mask]
    for col in ['P', 'PET', 'T', 'SM']:
        clim = ref.groupby(['cell', 'moy'])[col].agg(['mean', 'std'])
        j = df.join(clim, on=['cell', 'moy'])
        df[f'{col}_a'] = (df[col] - j['mean']) / j['std']
    g = df.groupby('cell')
    for col in [f'spei{k}' for k in INDEX_SCALES] + ['SM_a']:
        df[col + '_l1'] = g[col].shift(1)
        df[col + '_l2'] = g[col].shift(2)
    return df


def design(df, k, h):
    """Feature matrix X (with target-season terms) and target y = SPEI-k(t+h)."""
    target = df.groupby('cell')[f'spei{k}'].shift(-h)
    tm = (df.moy + h - 1) % 12 + 1
    X = df[features_for(k)].copy()
    X['tsin'] = np.sin(2 * np.pi * tm / 12)
    X['tcos'] = np.cos(2 * np.pi * tm / 12)
    return X, target


class _Model:
    """Standardise -> ridge. Keeps scaler stats for exact driver attribution."""

    def fit(self, X, y):
        self.mu = X.mean()
        self.sd = X.std().replace(0, 1)
        self.ridge = Ridge(alpha=RIDGE_ALPHA).fit((X - self.mu) / self.sd, y)
        return self

    def predict(self, X):
        return self.ridge.predict((X - self.mu) / self.sd)

    def contributions(self, X):
        """Per-feature contribution (SPEI units) relative to the training mean state."""
        Z = (X - self.mu) / self.sd
        return Z * self.ridge.coef_


def _event_scores(y, mu, sigma, prob=None):
    """Drought-event scores. `prob` overrides the Gaussian probability (ensembles)."""
    ev = (y <= DROUGHT_THRESHOLD).astype(int)
    if prob is None:
        prob = stats.norm.cdf((DROUGHT_THRESHOLD - mu) / sigma)
    base = ev.mean()
    bs = np.mean((prob - ev) ** 2)
    bs_clim = np.mean((base - ev) ** 2)
    auc = None
    if 0 < ev.sum() < len(ev):
        from sklearn.metrics import roc_auc_score
        auc = float(roc_auc_score(ev, prob))
    det = mu <= DROUGHT_THRESHOLD
    a = int((det & (ev == 1)).sum()); b = int((det & (ev == 0)).sum())
    c = int((~det & (ev == 1)).sum()); d = int((~det & (ev == 0)).sum())
    n = a + b + c + d
    expected = ((a + b) * (a + c) + (c + d) * (b + d)) / n
    return {
        'auc': auc,
        'brier_skill': float(1 - bs / bs_clim) if bs_clim else None,
        'hit_rate': a / (a + c) if a + c else None,           # POD
        'false_alarm_ratio': b / (a + b) if a + b else None,  # FAR
        'heidke': float((a + d - expected) / (n - expected)) if n != expected else None,
        'event_rate': float(base),
    }


def verify(df, log=print):
    """Expanding-window out-of-sample verification for every (k, h)."""
    ordm = df.month.dt.year * 12 + df.month.dt.month
    last_year = int(df.month.max().year)
    skill = {}
    for k in SCALES:
        for h in LEADS:
            X, y = design(df, k, h)
            ok = X.notna().all(axis=1) & y.notna()
            preds, obs, pers, months = [], [], [], []
            for yr in range(VERIFY_START, last_year + 1):
                test = ok & (df.month.dt.year == yr)
                if not test.any():
                    continue
                train = ok & (ordm + h < yr * 12 + 1)
                m = _Model().fit(X[train], y[train])
                preds.append(m.predict(X[test]))
                obs.append(y[test].values)
                pers.append(df.loc[test, f'spei{k}'].values)
                months.append(df.loc[test, 'month'].values)
            p = np.concatenate(preds); o = np.concatenate(obs); ps = np.concatenate(pers)
            rmse = float(np.sqrt(np.mean((o - p) ** 2)))
            entry = {
                'n_cases': int(len(o)),
                'n_months': int(len(set(np.concatenate(months)))),
                'period': f'{VERIFY_START}-{last_year}',
                'rmse': rmse,
                'r': float(np.corrcoef(o, p)[0, 1]),
                'r2': float(1 - np.mean((o - p) ** 2) / np.var(o)),
                'msss': float(1 - np.mean((o - p) ** 2) / np.mean(o ** 2)),
                'msss_persistence': float(1 - np.mean((o - ps) ** 2) / np.mean(o ** 2)),
            }
            entry.update(_event_scores(o, p, rmse))
            entry['skilful'] = bool(entry['auc'] is not None and entry['auc'] >= SKILL_MIN_AUC
                                    and entry['msss'] >= SKILL_MIN_MSSS)
            skill[f'{k}_{h}'] = entry
            log(f'  SPEI-{k} +{h}m  AUC={entry["auc"]:.2f}  MSSS={entry["msss"]:.2f}  '
                f'(persistence {entry["msss_persistence"]:.2f})  {"skilful" if entry["skilful"] else "no skill"}')
    return skill


def _class(spei):
    if spei <= -2: return 'extreme'
    if spei <= -1.5: return 'severe'
    if spei <= -1: return 'moderate'
    if spei <= -0.5: return 'mild'
    if spei < 0.5: return 'normal'
    if spei < 1: return 'wet'
    return 'very_wet'


def _add_months(d: date, n):
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def forecast(df, skill):
    """Fit on everything available and forecast from the latest complete month."""
    cells = {c['id']: c for c in load_cells()}
    issue = df.month.max()
    issue_d = date(issue.year, issue.month, 1)
    latest = df[df.month == issue].set_index('cell')
    payload_cells = {cid: {
        'lat': c['lat'], 'lon': c['lon'], 'km2': c['km2'],
        'observed': {f'spei{k}': _r(latest.at[cid, f'spei{k}']) if cid in latest.index else None
                     for k in INDEX_SCALES},
        'forecast': {},
    } for cid, c in cells.items()}

    for k in SCALES:
        for h in LEADS:
            X, y = design(df, k, h)
            ok = X.notna().all(axis=1) & y.notna()
            m = _Model().fit(X[ok], y[ok])
            now = (df.month == issue) & X.notna().all(axis=1)
            mu = m.predict(X[now])
            sig = skill[f'{k}_{h}']['rmse']
            contrib = m.contributions(X[now])
            for (idx, cid), mean in zip(df.loc[now, 'cell'].items(), mu):
                groups = {}
                for feat, v in contrib.loc[idx].items():
                    g = _driver_group(feat)
                    if g:
                        groups[g] = groups.get(g, 0.0) + float(v)
                drivers = sorted(({'key': g, 'label': DRIVER_GROUPS[g], 'effect': round(v, 2)}
                                  for g, v in groups.items()), key=lambda d: -abs(d['effect']))
                payload_cells[cid]['forecast'].setdefault(str(k), {})[str(h)] = {
                    'spei': round(float(mean), 2),
                    'lo': round(float(mean - 1.2816 * sig), 2),   # 80 % interval
                    'hi': round(float(mean + 1.2816 * sig), 2),
                    'p_drought': round(float(stats.norm.cdf((DROUGHT_THRESHOLD - mean) / sig)), 3),
                    'class': _class(mean),
                    'drivers': drivers,
                }

    # basin means (area-weighted) and recent observed history for context
    w = {cid: (c['km2'] or 1.0) for cid, c in cells.items()}
    basin = {}
    for k in SCALES:
        for h in LEADS:
            vals = [(payload_cells[c]['forecast'][str(k)][str(h)], w[c]) for c in payload_cells
                    if str(k) in payload_cells[c]['forecast']]
            tw = sum(x[1] for x in vals)
            basin.setdefault(str(k), {})[str(h)] = {
                'spei': round(sum(v['spei'] * wt for v, wt in vals) / tw, 2),
                'p_drought': round(sum(v['p_drought'] * wt for v, wt in vals) / tw, 3),
                'target_month': _add_months(issue_d, h).isoformat(),
            }
    hist = {}
    recent = df[df.month > issue - 36]
    for k in SCALES:
        s = recent.assign(w=recent.cell.map(w)).groupby('month').apply(
            lambda g: np.average(g[f'spei{k}'].fillna(0), weights=g.w))
        hist[str(k)] = [{'month': str(p), 'spei': round(float(v), 2)} for p, v in s.items()]

    return {
        'model_version': MODEL_VERSION,
        'issue_month': issue_d.isoformat(),
        'target_months': {str(h): _add_months(issue_d, h).isoformat() for h in LEADS},
        'scales': {str(k): SCALE_INFO[k] for k in SCALES},
        'leads': list(LEADS),
        'drought_threshold': DROUGHT_THRESHOLD,
        'skill_rule': {'min_auc': SKILL_MIN_AUC, 'min_msss': SKILL_MIN_MSSS},
        'reference_period': f'{REF_START}-{REF_END}',
        'sources': {
            'precipitation': 'CHIRPS v2.0 daily (0.05°)',
            'et0': 'FAO-56 Penman-Monteith from ERA5-Land daily aggregates (0.1°)',
            'soil_moisture': 'ERA5-Land volumetric soil water, layers 1-2',
        },
        'skill': skill,
        'cells': payload_cells,
        'basin': basin,
        'history': hist,
        'drivers': DRIVER_GROUPS,
    }


def _r(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), 2)


# --------------------------------------------------------------------------- #
# Scenario outlook (historical-year resampling)
# --------------------------------------------------------------------------- #
#
# The ridge forecast gives one best estimate. The scenario outlook answers a
# different question: "given the water balance observed so far, what would the
# index be if the coming months repeated the weather of year Y?", for every
# year on record. It is the Ensemble Streamflow Prediction idea (Day 1985)
# applied to SPEI. The observed part of the accumulation window is exact; only
# the future months are drawn from history. It needs no model and stays honest
# at any lead: once nothing of the window is observed it converges on
# climatology instead of pretending to know.
#
# ET0 has risen since 1981, so each member's ET0 is shifted so that the
# ensemble-mean ET0 of every calendar month equals the mean of the last
# SCENARIO_PET_YEARS years. Rainfall is used as recorded.

SCENARIO_BACK = max(SCALES)          # observed months kept in front of the future
SCENARIO_PET_YEARS = 10
SCENARIO_QUANTILES = (10, 25, 50, 75, 90)


def _glo_cdf_arr(x, xi, alpha, kappa):
    """glo_cdf with array parameters (broadcast against x)."""
    small = np.abs(kappa) < 1e-6
    ks = np.where(small, 1.0, kappa)
    arg = 1 - ks * (x - xi) / alpha
    inside = arg > 0
    y = np.where(inside, -np.log(np.where(inside, arg, 1.0)) / ks, np.where(ks > 0, np.inf, -np.inf))
    y = np.where(small, (x - xi) / alpha, y)
    return 1 / (1 + np.exp(-y))


def _glo_quantile_arr(f, xi, alpha, kappa):
    small = np.abs(kappa) < 1e-6
    ks = np.where(small, 1.0, kappa)
    q = xi + alpha * (1 - ((1 - f) / f) ** ks) / ks
    return np.where(small, xi + alpha * np.log(f / (1 - f)), q)


def _rolling_sum(a, k):
    """Trailing k-step sum along the last axis; NaN until k values exist."""
    cs = np.concatenate([np.zeros(a.shape[:-1] + (1,)), np.cumsum(a, axis=-1)], axis=-1)
    out = np.full(a.shape, np.nan)
    out[..., k - 1:] = cs[..., k:] - cs[..., :-k]
    return out


def scenario_arrays(df):
    """Dense [cell, month] arrays and the GLO parameters used by add_indices."""
    months = pd.period_range(df.month.min(), df.month.max(), freq='M')
    cells = sorted(df.cell.unique())

    def grid(col):
        return df.pivot(index='cell', columns='month', values=col).reindex(
            index=cells, columns=months).to_numpy(float)

    P, PET = grid('P'), grid('PET')
    years, moys = months.year.to_numpy(), months.month.to_numpy()
    ref = (years >= REF_START) & (years <= REF_END)
    params = {}
    for k in SCALES:
        acc = _rolling_sum(P - PET, k)
        par = np.full((len(cells), 12, 3), np.nan)
        for ci in range(len(cells)):
            for m in range(1, 13):
                x = acc[ci, ref & (moys == m)]
                x = x[~np.isnan(x)]
                if len(x) >= 15:
                    par[ci, m - 1] = glo_fit(x)
        params[k] = par
    return {'cells': cells, 'months': months, 'years': years, 'moys': moys, 'P': P, 'PET': PET,
            'params': params, 'spei': {k: grid(f'spei{k}') for k in SCALES}}


def scenario_ensemble(arr, t):
    """SPEI of every scale and lead if the months after index t repeated each past year.

    Only data at or before t is used: a member is 12 consecutive recorded
    months that END no later than t. Returns None when history is too short.
    """
    P, PET, moys = arr['P'], arr['PET'], arr['moys']
    n = max(LEADS)
    if t < SCENARIO_BACK - 1:
        return None
    lead_moy = (moys[t] - 1 + np.arange(1, n + 1)) % 12 + 1          # calendar month of each lead
    starts = np.array([s for s in range(0, t - n + 2) if moys[s] == lead_moy[0]], dtype=int)
    if len(starts) == 0:
        return None
    idx = starts[:, None] + np.arange(n)
    fP, fPET = P[:, idx], PET[:, idx]                                 # [cell, member, lead]
    good = ~np.isnan(fP + fPET).any(axis=(0, 2))
    starts, fP, fPET = starts[good], fP[:, good], fPET[:, good]
    if len(starts) < 10:
        return None
    lo = max(0, t - 12 * SCENARIO_PET_YEARS + 1)
    recent_m, recent = moys[lo:t + 1], PET[:, lo:t + 1]
    pet_now = np.stack([np.nanmean(recent[:, recent_m == m], axis=1) for m in lead_moy], axis=1)   # [cell, lead]
    fD = fP - (fPET + (pet_now - fPET.mean(axis=1))[:, None, :])
    obs = (P - PET)[:, t - SCENARIO_BACK + 1:t + 1]
    series = np.concatenate(
        [np.broadcast_to(obs[:, None, :], (obs.shape[0], len(starts), SCENARIO_BACK)), fD], axis=2)
    cs = np.concatenate([np.zeros(series.shape[:2] + (1,)), np.cumsum(series, axis=2)], axis=2)
    spei = {}
    for k in SCALES:
        out = np.empty(fD.shape)
        for h in LEADS:
            acc = cs[:, :, SCENARIO_BACK + h] - cs[:, :, SCENARIO_BACK + h - k]
            par = arr['params'][k][:, lead_moy[h - 1] - 1, :]
            cdf = _glo_cdf_arr(acc, par[:, 0:1], par[:, 1:2], par[:, 2:3])
            out[:, :, h - 1] = stats.norm.ppf(np.clip(cdf, 1e-4, 1 - 1e-4))
        spei[k] = out
    return {'spei': spei, 'member_years': [int(arr['years'][s]) for s in starts],
            'lead_moy': lead_moy, 'pet_now': pet_now, 'obs_d': obs}


def verify_scenarios(arr, log=print):
    """Out-of-sample check of the scenario ensemble, same issue months as verify()."""
    T = len(arr['months'])
    last_year = int(arr['years'][-1])
    store = {(k, h): ([], [], [], [], [], [], set()) for k in SCALES for h in LEADS}
    for t in range(T - 1):
        if arr['years'][t] < VERIFY_START:
            continue
        ens = scenario_ensemble(arr, t)
        if ens is None:
            continue
        for k in SCALES:
            e = ens['spei'][k]
            for h in LEADS:
                if t + h >= T:
                    break
                o = arr['spei'][k][:, t + h]
                ok = ~np.isnan(o) & ~np.isnan(e[:, :, h - 1]).any(axis=1)
                m = e[ok, :, h - 1]
                st = store[(k, h)]
                st[0].append(o[ok])
                st[1].append(np.median(m, axis=1))
                st[2].append((m <= DROUGHT_THRESHOLD).mean(axis=1))
                st[3].append(np.percentile(m, 10, axis=1))
                st[4].append(np.percentile(m, 90, axis=1))
                st[5].append(arr['spei'][k][ok, t])
                st[6].add(t)
    skill = {}
    for (k, h), st in store.items():
        if not st[0]:
            continue
        o, med, p, lo, hi, pers = (np.concatenate(x) for x in st[:6])
        mse = np.mean((o - med) ** 2)
        e = skill[f'{k}_{h}'] = {
            'n_cases': int(len(o)),
            'n_months': len(st[6]),
            'period': f'{VERIFY_START}-{last_year}',
            'rmse': float(np.sqrt(mse)),
            'r': float(np.corrcoef(o, med)[0, 1]),
            'r2': float(1 - mse / np.var(o)),
            'msss': float(1 - mse / np.mean(o ** 2)),
            'msss_persistence': float(1 - np.nanmean((o - pers) ** 2) / np.mean(o ** 2)),
            'coverage80': float(np.mean((o >= lo) & (o <= hi))),   # ideal: 0.80
        }
        e.update(_event_scores(o, med, None, prob=p))   # deterministic rule: ensemble median <= -1
        e['skilful'] = bool(e['auc'] is not None and e['auc'] >= SKILL_MIN_AUC and e['msss'] >= SKILL_MIN_MSSS)
        log(f'  scenarios SPEI-{k} +{h}m  AUC={e["auc"] or 0:.2f}  MSSS={e["msss"]:.2f}  '
            f'80% range holds {e["coverage80"]:.0%}')
    return skill


def scenarios(df, skill=None, log=print):
    """Scenario outlook from the latest month: quantiles, drought chance and the
    rain needed to be out of drought, per cell and for the basin."""
    arr = scenario_arrays(df)
    if skill is None:
        skill = verify_scenarios(arr, log=log)
    ens = scenario_ensemble(arr, len(arr['months']) - 1)
    if ens is None:
        return None
    cells_meta = {c['id']: c for c in load_cells()}
    w = np.array([(cells_meta.get(c, {}).get('km2') or 1.0) for c in arr['cells']], dtype=float)
    w = w / w.sum()
    years, moys, P = arr['years'], arr['moys'], arr['P']
    ref = (years >= REF_START) & (years <= REF_END)
    p_norm = np.stack([np.nanmean(P[:, ref & (moys == m)], axis=1) for m in ens['lead_moy']], axis=1)
    f_thr = stats.norm.cdf(DROUGHT_THRESHOLD)

    out_cells = {c: {} for c in arr['cells']}
    basin = {}
    for k in SCALES:
        e = ens['spei'][k]                                    # [cell, member, lead]
        q = np.percentile(e, SCENARIO_QUANTILES, axis=1)       # [quantile, cell, lead]
        p_dry = (e <= DROUGHT_THRESHOLD).mean(axis=1)
        eb = np.tensordot(w, e, axes=(0, 0))                   # basin mean per member: [member, lead]
        qb = np.percentile(eb, SCENARIO_QUANTILES, axis=0)
        for ci, c in enumerate(arr['cells']):
            out_cells[c][str(k)] = {str(h): {
                'p10': _r(float(q[0, ci, h - 1])), 'p50': _r(float(q[2, ci, h - 1])),
                'p90': _r(float(q[4, ci, h - 1])),
                'p_drought': round(float(p_dry[ci, h - 1]), 2)} for h in LEADS}
        basin[str(k)] = {}
        for h in LEADS:
            nf = min(h, k)                                      # future months inside the window
            fut = slice(h - nf, h)
            known = ens['obs_d'][:, SCENARIO_BACK - (k - nf):].sum(axis=1) if k > nf else 0.0
            par = arr['params'][k][:, ens['lead_moy'][h - 1] - 1, :]
            d_thr = _glo_quantile_arr(f_thr, par[:, 0], par[:, 1], par[:, 2])
            need = np.clip(d_thr - known + ens['pet_now'][:, fut].sum(axis=1), 0, None)
            need_b = float(np.dot(w, need))
            normal_b = float(np.dot(w, p_norm[:, fut].sum(axis=1)))
            order = np.argsort(eb[:, h - 1])
            basin[str(k)][str(h)] = {
                **{f'p{p}': _r(float(v)) for p, v in zip(SCENARIO_QUANTILES, qb[:, h - 1])},
                'p_drought': round(float((eb[:, h - 1] <= DROUGHT_THRESHOLD).mean()), 2),
                'observed_months': k - nf, 'future_months': nf,
                'rain_needed_mm': round(need_b), 'rain_normal_mm': round(normal_b),
                'rain_needed_pct': round(100 * need_b / normal_b) if normal_b > 1 else None,
                'driest_year': ens['member_years'][int(order[0])],
                'wettest_year': ens['member_years'][int(order[-1])],
            }
    return {
        'method': 'historical-year resampling (ESP)',
        'n_members': len(ens['member_years']),
        'member_years': [ens['member_years'][0], ens['member_years'][-1]],
        'pet_adjusted_to_last_years': SCENARIO_PET_YEARS,
        'quantiles': list(SCENARIO_QUANTILES),
        'basin': basin, 'cells': out_cells, 'skill': skill,
    }


def promote_scenarios(payload):
    """Make the scenario ensemble the published forecast.

    It verified at least as well as the ridge model at every scale and lead and
    cannot extrapolate beyond weather that has happened. The ridge estimate is
    kept beside it (`ridge`) because only a linear model gives the exact driver
    attribution, and its skill table moves to `skill_ridge`.
    """
    sc = payload.get('scenarios')
    if not sc:
        return payload
    for cid, cell in payload['cells'].items():
        for k, by_lead in cell['forecast'].items():
            for h, f in by_lead.items():
                s = ((sc['cells'].get(cid) or {}).get(k) or {}).get(h)
                if not s or s['p50'] is None:
                    continue
                f['ridge'] = {'spei': f['spei'], 'p_drought': f['p_drought']}
                f.update({'spei': s['p50'], 'lo': s['p10'], 'hi': s['p90'],
                          'p_drought': s['p_drought'], 'class': _class(s['p50'])})
    for k, by_lead in payload['basin'].items():
        for h, b in by_lead.items():
            s = (sc['basin'].get(k) or {}).get(h)
            if not s:
                continue
            b['ridge'] = {'spei': b['spei'], 'p_drought': b['p_drought']}
            b.update({'spei': s['p50'], 'p_drought': s['p_drought']})
    payload['skill_ridge'] = payload['skill']
    payload['skill'] = sc['skill']
    payload['primary'] = 'scenarios'
    payload['model_version'] = MODEL_VERSION
    return payload


def run(records, previous_skill=None, do_verify=True, log=print, previous_scenario_skill=None):
    """previous_skill is the RIDGE skill table of the last run (`skill_ridge`)."""
    df = add_indices(prepare_frame(records))
    skill = verify(df, log=log) if do_verify or not previous_skill else previous_skill
    payload = forecast(df, skill)
    payload['model_version'] = RIDGE_VERSION
    reuse = (not do_verify and previous_scenario_skill
             and all('msss_persistence' in e for e in previous_scenario_skill.values()))
    payload['scenarios'] = scenarios(df, skill=previous_scenario_skill if reuse else None, log=log)
    return promote_scenarios(payload)
