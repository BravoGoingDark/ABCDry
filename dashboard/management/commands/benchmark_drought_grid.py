"""Head-to-head benchmark of the gridded SPEI forecast methods.

    python manage.py benchmark_drought_grid                 # all methods
    python manage.py benchmark_drought_grid --no-lstm       # skip the slow LSTM
    python manage.py benchmark_drought_grid --scales 6 12   # subset

Every method is scored on exactly the same cases, with the same protocol as
the published forecast (drought_grid.verify):

* issue months 2011 -> last year, 29 cells each;
* models are refit at the start of every test year;
* a training example is allowed only if its TARGET month precedes the first
  issue month of that year (purge of h months), so nothing scored is ever seen;
* the scenario ensemble only replays years that ended before the issue month.

Methods
-------
scenarios   historical-year resampling (the published forecast)
ridge       linear regression, the companion model (drought_grid._Model)
xgboost     gradient-boosted trees on the same predictors as ridge
lstm        recurrent network on the last 24 months of every index and
            anomaly, one multi-lead model per scale, 3 seeds averaged,
            early stopping on the last 2 training years
persistence "SPEI stays as it is now" (reference only)

Scores: ROC AUC for drought (SPEI <= -1), MSSS against climatology (1 = perfect,
0 = no better than "always normal") and RMSE. The MSSS gap between the scenario
ensemble and each model gets a 90 % interval from a block bootstrap over test
years, because the 29 cells of one month are not independent.
"""
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from django.conf import settings
from django.core.management.base import BaseCommand
from sklearn.metrics import roc_auc_score

from dashboard.models import GridCellClimate
from dashboard.prediction_engine import drought_grid as dg

LSTM_WINDOW = 24
LSTM_SEEDS = (0, 1, 2)
N_BOOT = 2000

# Paper replica (Afan et al. 2024): univariate SPEI, 48-month look-back,
# 100 epochs, RMSprop / Adamax, one-step model rolled forward for longer leads.
PAPER_WINDOW = 48
PAPER_EPOCHS = 100
PAPER_BATCH = 256
PAPER_OPTIMIZERS = ('rmsprop', 'adamax')


# --------------------------------------------------------------------------- #
# Scores
# --------------------------------------------------------------------------- #

def _scores(obs, pred, score_for_auc):
    ev = (obs <= dg.DROUGHT_THRESHOLD).astype(int)
    mse = float(np.mean((obs - pred) ** 2))
    auc = float(roc_auc_score(ev, score_for_auc)) if 0 < ev.sum() < len(ev) else None
    msss = 1 - mse / float(np.mean(obs ** 2))
    r2 = 1 - mse / float(np.var(obs))
    return {'auc': auc, 'msss': msss, 'r2': r2, 'rmse': mse ** 0.5,
            'skilful': bool(auc is not None and auc >= dg.SKILL_MIN_AUC and msss >= dg.SKILL_MIN_MSSS)}


def _boot_msss_gap(obs, pred_a, pred_b, years, rng):
    """90 % block-bootstrap interval (by test year) of MSSS(a) - MSSS(b)."""
    uy = np.unique(years)
    pos = {y: i for i, y in enumerate(uy)}
    yi = np.array([pos[y] for y in years])
    o2 = np.bincount(yi, obs ** 2, len(uy))
    ea = np.bincount(yi, (obs - pred_a) ** 2, len(uy))
    eb = np.bincount(yi, (obs - pred_b) ** 2, len(uy))
    draws = rng.integers(0, len(uy), size=(N_BOOT, len(uy)))
    w = np.stack([np.bincount(d, minlength=len(uy)) for d in draws])
    gap = (w @ eb - w @ ea) / (w @ o2)          # = MSSS(a) - MSSS(b)
    return [float(np.percentile(gap, 5)), float(np.percentile(gap, 95))]


# --------------------------------------------------------------------------- #
# Model wrappers
# --------------------------------------------------------------------------- #

def _xgb():
    from xgboost import XGBRegressor
    return XGBRegressor(n_estimators=400, max_depth=3, learning_rate=0.03, subsample=0.8,
                        colsample_bytree=0.8, min_child_weight=20, reg_lambda=5.0,
                        tree_method='hist', n_jobs=8, random_state=0, verbosity=0)


def _lstm_inputs(df):
    """[row, window, feature] tensor of the last LSTM_WINDOW months, per cell."""
    cols = ([f'spei{k}' for k in dg.INDEX_SCALES] + ['P_a', 'PET_a', 'T_a', 'SM_a'])
    ref = (df.month.dt.year >= dg.REF_START) & (df.month.dt.year <= dg.REF_END)
    mu, sd = df.loc[ref, cols].mean(), df.loc[ref, cols].std().replace(0, 1)
    Z = ((df[cols] - mu) / sd)
    have = Z.notna().all(axis=1).to_numpy()
    Z = Z.fillna(0.0)
    Z['msin'] = np.sin(2 * np.pi * df.moy / 12)
    Z['mcos'] = np.cos(2 * np.pi * df.moy / 12)
    Z['lat'] = (df.lat - df.lat.mean()) / (df.lat.std() or 1)
    Z['lon'] = (df.lon - df.lon.mean()) / (df.lon.std() or 1)
    F = Z.to_numpy(np.float32)
    seq = np.zeros((len(df), LSTM_WINDOW, F.shape[1]), np.float32)
    valid = np.zeros(len(df), bool)
    for _, g in df.groupby('cell'):
        idx = g.index.to_numpy()                 # rows of one cell, in month order
        for j in range(LSTM_WINDOW - 1, len(idx)):
            rows = idx[j - LSTM_WINDOW + 1:j + 1]
            seq[idx[j]] = F[rows]
            valid[idx[j]] = have[idx[j]]
    return seq, valid


def _fit_lstm(Xtr, Ytr, Mtr, Xva, Yva, Mva, seed):
    import torch
    from torch import nn

    torch.manual_seed(seed)
    np.random.seed(seed)

    class Net(nn.Module):
        def __init__(self, n_in, n_out):
            super().__init__()
            self.lstm = nn.LSTM(n_in, 32, batch_first=True)
            self.drop = nn.Dropout(0.2)
            self.head = nn.Linear(32, n_out)

        def forward(self, x):
            out, _ = self.lstm(x)
            return self.head(self.drop(out[:, -1]))

    net = Net(Xtr.shape[2], Ytr.shape[1])
    opt = torch.optim.Adam(net.parameters(), lr=2e-3, weight_decay=1e-4)
    t = lambda a: torch.from_numpy(a)
    Xtr_, Ytr_, Mtr_ = t(Xtr), t(Ytr), t(Mtr)
    Xva_, Yva_, Mva_ = t(Xva), t(Yva), t(Mva)

    def loss_fn(p, y, m):
        return ((p - y) ** 2 * m).sum() / m.sum().clamp(min=1)

    best, best_state, bad = np.inf, None, 0
    for _epoch in range(80):
        net.train()
        perm = torch.randperm(len(Xtr_))
        for i in range(0, len(perm), 256):
            b = perm[i:i + 256]
            opt.zero_grad()
            loss_fn(net(Xtr_[b]), Ytr_[b], Mtr_[b]).backward()
            opt.step()
        net.eval()
        with torch.no_grad():
            v = float(loss_fn(net(Xva_), Yva_, Mva_))
        if v < best - 1e-4:
            best, bad = v, 0
            best_state = {k: x.clone() for k, x in net.state_dict().items()}
        else:
            bad += 1
            if bad >= 8:
                break
    net.load_state_dict(best_state)
    net.eval()
    return net


def _lstm_predict(net, X):
    import torch
    with torch.no_grad():
        return net(torch.from_numpy(X)).numpy()


# --------------------------------------------------------------------------- #
# Paper replica: Afan et al. (2024), Water 16, 2799
# --------------------------------------------------------------------------- #

def _paper_inputs(df, k):
    """[row, PAPER_WINDOW, 1] tensor of the last PAPER_WINDOW SPEI-k values, per cell.
    Univariate, as in the paper: the network sees nothing but the index itself."""
    v = df[f'spei{k}'].to_numpy(np.float32)
    seq = np.zeros((len(df), PAPER_WINDOW, 1), np.float32)
    valid = np.zeros(len(df), bool)
    for _, g in df.groupby('cell'):
        idx = g.index.to_numpy()
        for j in range(PAPER_WINDOW - 1, len(idx)):
            w = v[idx[j - PAPER_WINDOW + 1:j + 1]]
            if not np.isnan(w).any():
                seq[idx[j], :, 0] = w
                valid[idx[j]] = True
    return seq, valid


def _fit_paper_lstm(X, y, optimizer, seed):
    """LSTM(50) -> Dense(1), one-step-ahead, fixed PAPER_EPOCHS, Keras default
    learning rate (1e-3) for the chosen optimizer, no early stopping."""
    import torch
    from torch import nn

    torch.manual_seed(seed)

    class Net(nn.Module):
        def __init__(self):
            super().__init__()
            self.lstm = nn.LSTM(1, 50, batch_first=True)
            self.head = nn.Linear(50, 1)

        def forward(self, x):
            out, _ = self.lstm(x)
            return self.head(out[:, -1])

    net = Net()
    opt = {'rmsprop': lambda p: torch.optim.RMSprop(p, lr=1e-3, alpha=0.9, eps=1e-7),
           'adamax': lambda p: torch.optim.Adamax(p, lr=1e-3, eps=1e-7)}[optimizer](net.parameters())
    X_, y_ = torch.from_numpy(X), torch.from_numpy(y[:, None])
    for _epoch in range(PAPER_EPOCHS):
        net.train()
        perm = torch.randperm(len(X_))
        for i in range(0, len(perm), PAPER_BATCH):
            b = perm[i:i + PAPER_BATCH]
            opt.zero_grad()
            ((net(X_[b]) - y_[b]) ** 2).mean().backward()
            opt.step()
    net.eval()
    return net


def _paper_recursive(net, X, n_leads):
    """Feed each one-month prediction back in, as the paper did for its 40-year run."""
    import torch
    w = torch.from_numpy(X.copy())
    out = []
    with torch.no_grad():
        for _ in range(n_leads):
            p = net(w)                                   # [n, 1]
            out.append(p[:, 0].numpy())
            w = torch.cat([w[:, 1:], p[:, None, :]], dim=1)
    return np.stack(out, axis=1)                         # [n, n_leads]


# --------------------------------------------------------------------------- #
# Command
# --------------------------------------------------------------------------- #

class Command(BaseCommand):
    help = 'Compare scenario ensemble, ridge, XGBoost and LSTM on the same leak-free hindcast.'

    def add_arguments(self, parser):
        parser.add_argument('--scales', type=int, nargs='*', default=list(dg.SCALES))
        parser.add_argument('--no-lstm', action='store_true')
        parser.add_argument('--no-xgb', action='store_true')
        parser.add_argument('--paper-lstm', action='store_true',
                            help='add the Afan et al. (2024) univariate LSTM with RMSprop and Adamax')
        parser.add_argument('--paper-refit-years', type=int, default=1,
                            help='refit the paper LSTM every N test years (still leak-free: '
                                 'trained only on months before the block)')
        parser.add_argument('--out', default=str(Path(settings.BASE_DIR) / 'models' / 'benchmark_drought_grid.json'))

    def handle(self, *args, **opts):
        log = lambda s: self.stdout.write(s)
        t0 = time.time()
        records = list(GridCellClimate.objects.values(
            'cell', 'month', 'precip_mm', 'tmax_c', 'tmin_c', 'tmean_c', 'tdew_c',
            'wind_ms', 'solar_mj', 'soil_moisture'))
        df = dg.add_indices(dg.prepare_frame(records))
        ordm = (df.month.dt.year * 12 + df.month.dt.month).to_numpy()
        years = df.month.dt.year.to_numpy()
        last_year = int(years.max())
        test_years = list(range(dg.VERIFY_START, last_year + 1))
        scales = [k for k in opts['scales'] if k in dg.SCALES]
        leads = list(dg.LEADS)
        methods = (['scenarios', 'ridge'] + ([] if opts['no_xgb'] else ['xgboost'])
                   + ([] if opts['no_lstm'] else ['lstm'])
                   + ([f'paper_{o}' for o in PAPER_OPTIMIZERS] if opts['paper_lstm'] else []))

        # pred[(k, h)][method] = array over df rows (NaN = no prediction)
        pred = {(k, h): {m: np.full(len(df), np.nan) for m in methods} for k in scales for h in leads}
        prob = {(k, h): np.full(len(df), np.nan) for k in scales for h in leads}   # scenario P(drought)

        # ---- scenario ensemble
        log('Scenario ensemble...')
        arr = dg.scenario_arrays(df)
        row_of = {(c, m): i for i, (c, m) in enumerate(zip(df.cell, df.month))}
        for t in range(len(arr['months']) - 1):
            if arr['years'][t] < dg.VERIFY_START:
                continue
            ens = dg.scenario_ensemble(arr, t)
            if ens is None:
                continue
            rows = np.array([row_of.get((c, arr['months'][t]), -1) for c in arr['cells']])
            keep = rows >= 0
            for k in scales:
                e = ens['spei'][k]
                for h in leads:
                    pred[(k, h)]['scenarios'][rows[keep]] = np.median(e[keep, :, h - 1], axis=1)
                    prob[(k, h)][rows[keep]] = (e[keep, :, h - 1] <= dg.DROUGHT_THRESHOLD).mean(axis=1)

        # ---- ridge and XGBoost, refit every test year
        for k in scales:
            for h in leads:
                X, y = dg.design(df, k, h)
                ok = (X.notna().all(axis=1) & y.notna()).to_numpy()
                for yr in test_years:
                    test = ok & (years == yr)
                    if not test.any():
                        continue
                    train = ok & (ordm + h < yr * 12 + 1)
                    pred[(k, h)]['ridge'][test] = dg._Model().fit(X[train], y[train]).predict(X[test])
                    if 'xgboost' in methods:
                        m = _xgb().fit(X[train].to_numpy(), y[train].to_numpy())
                        pred[(k, h)]['xgboost'][test] = m.predict(X[test].to_numpy())
            log(f'  ridge{"/xgboost" if "xgboost" in methods else ""} SPEI-{k} done ({time.time() - t0:.0f}s)')

        # ---- LSTM, one multi-lead network per scale, refit every test year
        if 'lstm' in methods:
            import torch
            torch.set_num_threads(8)
            seq, valid = _lstm_inputs(df)
            for k in scales:
                Y = np.stack([df.groupby('cell')[f'spei{k}'].shift(-h).to_numpy() for h in leads], axis=1)
                Y = Y.astype(np.float32)
                for yr in test_years:
                    cutoff = yr * 12 + 1
                    lead_ok = (ordm[:, None] + np.array(leads)[None, :] < cutoff) & ~np.isnan(Y)
                    train_rows = valid & lead_ok.any(axis=1)
                    # last two training years hold out for early stopping
                    va_rows = train_rows & (years >= yr - 2)
                    tr_rows = train_rows & (years < yr - 2)
                    test = valid & (years == yr)
                    if not test.any():
                        continue
                    M = lead_ok.astype(np.float32)
                    Yz = np.nan_to_num(Y)
                    outs = []
                    for seed in LSTM_SEEDS:
                        net = _fit_lstm(seq[tr_rows], Yz[tr_rows], M[tr_rows],
                                        seq[va_rows], Yz[va_rows], M[va_rows], seed)
                        outs.append(_lstm_predict(net, seq[test]))
                    out = np.mean(outs, axis=0)
                    for j, h in enumerate(leads):
                        pred[(k, h)]['lstm'][test] = out[:, j]
                log(f'  lstm SPEI-{k} done ({time.time() - t0:.0f}s)')

        # ---- paper replica: univariate one-step LSTM, refit every test year
        if opts['paper_lstm']:
            import torch
            torch.set_num_threads(8)
            for k in scales:
                seq, valid = _paper_inputs(df, k)
                y1 = df.groupby('cell')[f'spei{k}'].shift(-1).to_numpy(np.float32)
                step = max(1, opts['paper_refit_years'])
                for yr in test_years[::step]:
                    test = valid & (years >= yr) & (years < yr + step)
                    if not test.any():
                        continue
                    train = valid & ~np.isnan(y1) & (ordm + 1 < yr * 12 + 1)
                    for o in PAPER_OPTIMIZERS:
                        net = _fit_paper_lstm(seq[train], y1[train], o, seed=0)
                        out = _paper_recursive(net, seq[test], len(leads))
                        for j, h in enumerate(leads):
                            pred[(k, h)][f'paper_{o}'][test] = out[:, j]
                    log(f'  paper LSTM SPEI-{k} {yr} done ({time.time() - t0:.0f}s)')

        # ---- score on the cases every method covers
        rng = np.random.default_rng(0)
        protocol = f'expanding window, refit yearly, purge = lead; issue months {dg.VERIFY_START}-{last_year}'
        if opts['paper_lstm'] and opts['paper_refit_years'] > 1:
            protocol += f'; paper LSTM refit every {opts["paper_refit_years"]} years'
        result = {'protocol': protocol,
                  'methods': methods, 'skill_rule': {'min_auc': dg.SKILL_MIN_AUC, 'min_msss': dg.SKILL_MIN_MSSS},
                  'scores': {}}
        for k in scales:
            for h in leads:
                target = df.groupby('cell')[f'spei{k}'].shift(-h).to_numpy()
                P = pred[(k, h)]
                common = ~np.isnan(target) & (years >= dg.VERIFY_START) & ~np.isnan(prob[(k, h)])
                for m in methods:
                    common &= ~np.isnan(P[m])
                o = target[common]
                entry = {'n_cases': int(common.sum()),
                         'n_months': int(len(np.unique(ordm[common])))}
                for m in methods:
                    auc_score = prob[(k, h)][common] if m == 'scenarios' else -P[m][common]
                    entry[m] = _scores(o, P[m][common], auc_score)
                pers = df[f'spei{k}'].to_numpy()[common]
                entry['persistence'] = _scores(o, pers, -pers)
                for m in methods[1:]:
                    entry['scenarios'][f'msss_gap_vs_{m}_90ci'] = _boot_msss_gap(
                        o, P['scenarios'][common], P[m][common], years[common], rng)
                result['scores'][f'{k}_{h}'] = entry
        result['runtime_s'] = round(time.time() - t0)

        Path(opts['out']).write_text(json.dumps(result, indent=1), encoding='utf-8')
        self._report(result, scales, leads, methods, log)
        log(self.style.SUCCESS(f'Saved {opts["out"]} ({result["runtime_s"]} s)'))

    def _report(self, res, scales, leads, methods, log):
        short = {'scenarios': 'scen', 'ridge': 'ridge', 'xgboost': 'xgb', 'lstm': 'lstm',
                 'paper_rmsprop': 'pRMS', 'paper_adamax': 'pAdx'}
        log('')
        log('MSSS (AUC) by lead; * = passes the publish rule; [lo, hi] = 90 % interval of scen - other MSSS')
        for k in scales:
            log(f'SPEI-{k}')
            for h in leads:
                e = res['scores'][f'{k}_{h}']
                cells = []
                for m in methods + ['persistence']:
                    s = e[m]
                    cells.append(f'{short.get(m, "pers")} {s["msss"]:+.2f}({s["auc"] or 0:.2f}){"*" if s["skilful"] else " "}')
                gaps = ' '.join(f'vs {short[m]} [{a:+.2f},{b:+.2f}]'
                                for m in methods[1:]
                                for a, b in [e['scenarios'][f'msss_gap_vs_{m}_90ci']])
                log(f'  +{h:<2} ' + '  '.join(cells) + '   ' + gaps)
        log('')
        log('Longest lead passing the publish rule:')
        for k in scales:
            log(f'  SPEI-{k}: ' + ', '.join(
                f'{m} {max([h for h in leads if res["scores"][f"{k}_{h}"][m]["skilful"]], default=0)}'
                for m in methods))
