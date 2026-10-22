"""SEAS5 seasonal-forecast validation gate for the drought platform.

Answers, with history, whether ECMWF SEAS5 seasonal rainfall forecasts carry
usable 3-month-lead signal for our regions BEFORE integrating them into the
T+3 model.  This is the go/no-go gate for making T+3 production-ready.

Steps
-----
1. DOWNLOAD : SEAS5 hindcast monthly total precipitation, leadtime 3,
   for a bounded set of forecast start months and years (CDS API).
2. EXTRACT  : ensemble-mean forecast rainfall at each region point.
3. BIAS-FIX : scale forecast to match observed CHIRPS climatology per
   region and calendar month (simple multiplicative correction).
4. SKILL    : against observed CHIRPS monthly rainfall (from our DB):
   a. Pearson correlation (forecast vs observed)
   b. Drought-signal AUC: low forecast rainfall as a predictor of an
      observed dry month (bottom tercile per calendar month)
5. GATE     : GO if median AUC >= 0.60, else NO-GO.

Usage:
    python scripts/seasonal_validation.py --download
    python scripts/seasonal_validation.py --download --start-months 9,12 --years 2000-2016

Requires a Copernicus CDS account: %USERPROFILE%\\.cdsapirc with
    url: https://cds.climate.copernicus.eu/api
    key: <YOUR-PERSONAL-ACCESS-TOKEN>
"""
import argparse
import os
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')
os.chdir(BASE_DIR)

import django  # noqa: E402

django.setup()

from dashboard.models import ClimateMetrics, Region  # noqa: E402

DATA_DIR = os.path.join(BASE_DIR, 'data', 'seas5')
AREA = [40, -10, 30, 15]  # N, W, S, E box covering our regions


def months_between(start_year, start_month, end_year, end_month):
    out = []
    y, m = start_year, start_month
    while (y, m) <= (end_year, end_month):
        out.append((y, m))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def download(start_months, years, leadtime=3):
    """Step 1: one CDS request per start month (hindcast + real-time archive)."""
    import cdsapi

    os.makedirs(DATA_DIR, exist_ok=True)
    c = cdsapi.Client(quiet=True)
    for sm in start_months:
        out = os.path.join(DATA_DIR, f'seas5_lt{leadtime}_start{sm:02d}.nc')
        if os.path.exists(out):
            print(f'  {out} already downloaded, skipping')
            continue
        # ECMWF real-time forecasts are under embargo for ~2 months after
        # release (6th of the start month). Also excludes future months.
        usable_years = [y for y in years
                        if date(y, sm, 1) < date.today() - timedelta(days=75)]
        if not usable_years:
            print(f'  start month {sm:02d}: all years under embargo, skipping')
            continue
        print(f'  downloading SEAS5 start-month {sm:02d}, years '
              f'{usable_years[0]}-{usable_years[-1]} ...')
        try:
            c.retrieve(
                'seasonal-monthly-single-levels',
                {
                    'data_format': 'netcdf',
                    'originating_centre': 'ecmwf',
                    'system': '51',
                    'variable': ['total_precipitation'],
                    'product_type': ['ensemble_mean'],
                    'leadtime_month': [str(leadtime)],
                    'year': [str(y) for y in usable_years],
                    'month': [f'{sm:02d}'],
                    'area': AREA,
                },
                out,
            )
        except Exception as exc:
            print(f'  FAILED: {str(exc)[:200]}')
            continue
        print(f'  saved {out}')


def extract_region_series(nc_path, region_ids, leadtime=3):
    """Step 2: ensemble-mean forecast rainfall per region per target month.

    SEAS5 netcdf dims: forecast_reference_time (forecast start), number
    (ensemble), latitude, longitude; forecastMonth gives the target month.
    Returns dict region_id -> Series(index=target_month_period, name='fcst_mm').
    """
    import xarray as xr

    regions = {r.id: r for r in Region.objects.filter(id__in=region_ids,
                                                      latitude__isnull=False)}
    ds = xr.open_dataset(nc_path)
    var = 'tprate' if 'tprate' in ds.variables else 'tp'
    da = ds[var]
    if 'number' in da.dims:
        da = da.mean('number')  # ensemble mean
    ref_times = pd.to_datetime(ds['forecast_reference_time'].values)
    out = {}
    for rid, region in regions.items():
        lat, lon = float(region.latitude), float(region.longitude)
        ser = da.sel(latitude=lat, longitude=lon, method='nearest')
        vals, idxs = [], []
        for i, t in enumerate(ref_times):
            start_p = pd.Period(t, freq='M')
            target_p = start_p + leadtime
            v = float(ser.isel(forecast_reference_time=i).values)
            # m/s rate -> mm accumulated over the target month
            mm = v * 86400.0 * target_p.days_in_month * 1000.0
            vals.append(mm)
            idxs.append(target_p)
        out[rid] = pd.Series(vals, index=pd.PeriodIndex(idxs, freq='M'),
                             name='fcst_mm')
    ds.close()
    return out


def observed_monthly_mm(region_id):
    """Observed monthly rainfall totals from our ClimateMetrics (CHIRPS)."""
    from dashboard.prediction_engine.spei_features import _load_daily_data
    region = Region.objects.get(id=region_id)
    pts = region.sample_points or []
    if pts:
        df = _load_daily_data(region.id, lat=float(pts[0]['lat']),
                              lon=float(pts[0]['lon']))
    else:
        df = _load_daily_data(region.id,
                              lat=float(region.latitude),
                              lon=float(region.longitude))
    if df.empty or 'rainfall_mm' not in df.columns:
        return None
    m = df['rainfall_mm'].resample('ME').sum()
    m.index = m.index.to_period('M')
    return m


def skill_gate(region_id, fcst, obs):
    """Steps 3-4: bias-fix, then correlation + drought-signal AUC."""
    import pandas as pd

    common = fcst.index.intersection(obs.index)
    if len(common) < 24:
        return None
    f = fcst.loc[common].astype(float)
    o = obs.loc[common].astype(float)

    # multiplicative bias correction per calendar month (scale forecast to
    # observed climatology); guard zero-forecast months
    month = np.array([p.month for p in common])
    f_adj = f.copy().values
    for m in range(1, 13):
        sel = month == m
        if sel.sum() < 3:
            continue
        fm, om = f.values[sel].mean(), o.values[sel].mean()
        if fm > 0.01:
            f_adj[sel] = f.values[sel] * (om / fm)
    f_adj = pd.Series(f_adj, index=common)

    corr = float(np.corrcoef(f_adj.values, o.values)[0, 1])

    # drought-signal AUC: observed dry month = bottom tercile of its calendar
    # month's climatology; predictor = low bias-corrected forecast
    def tercile_flags(values, months, high_is_dry=False):
        flags = np.zeros(len(values), dtype=int)
        for m in range(1, 13):
            sel = np.where(months == m)[0]
            if len(sel) < 6:
                continue
            thr = np.percentile(values[sel], 33)
            flags[sel] = (values[sel] <= thr).astype(int)
        return flags

    months = np.array([p.month for p in common])
    dry = tercile_flags(o.values, months)
    if dry.sum() < 8:
        return None
    # AUC without sklearn to avoid extra imports here
    order = np.argsort(f_adj.values)
    ranks = np.empty(len(order))
    ranks[order] = np.arange(1, len(order) + 1)
    n1 = dry.sum()
    n0 = len(dry) - n1
    auc = (ranks[dry == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)

    return {'n': len(common), 'corr': corr, 'auc': float(auc)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--download', action='store_true', help='Run the CDS download step')
    ap.add_argument('--start-months', default='1,2,3,4,5,6,7,8,9,10,11,12',
                    help='Forecast start months (default: all 12, real-time archive)')
    ap.add_argument('--years', default='2017-2026',
                    help='Forecast years range YYYY-YYYY (real-time archive: 2017+)')
    ap.add_argument('--leadtime', type=int, default=3)
    ap.add_argument('--regions', default='1,2,3,5,6,7,8',
                    help='Region ids to validate')
    args = ap.parse_args()

    y0, y1 = [int(x) for x in args.years.split('-')]
    start_months = [int(x) for x in args.start_months.split(',')]
    region_ids = [int(x) for x in args.regions.split(',')]

    nc_files = []
    for sm in start_months:
        p = os.path.join(DATA_DIR, f'seas5_lt{args.leadtime}_start{sm:02d}.nc')
        if os.path.exists(p):
            nc_files.append(p)

    if args.download:
        years = list(range(y0, y1 + 1))
        download(start_months, years, leadtime=args.leadtime)
        nc_files = [os.path.join(DATA_DIR, f'seas5_lt{args.leadtime}_start{sm:02d}.nc')
                    for sm in start_months]

    if not nc_files:
        print('No SEAS5 files found. Run with --download (needs a CDS key in ~/.cdsapirc).')
        return

    all_fcst = {rid: [] for rid in region_ids}
    for nc_path in nc_files:
        print(f'extracting {os.path.basename(nc_path)} ...')
        try:
            series = extract_region_series(nc_path, region_ids,
                                           leadtime=args.leadtime)
        except Exception as exc:
            print(f'  extract failed: {exc}')
            continue
        for rid, s in series.items():
            all_fcst[rid].append(s)

    aucs, corrs = [], []
    print('\n=== SKILL GATE (leadtime +%d months) ===' % args.leadtime)
    print('%-10s %6s %8s %8s' % ('region', 'n', 'corr', 'AUC'))
    for rid in region_ids:
        region = Region.objects.get(id=rid)
        fcst = pd.concat(all_fcst[rid]).groupby(level=0).mean() if all_fcst[rid] else None
        if fcst is None or fcst.empty:
            print('%-10s   no forecast data' % region.name)
            continue
        obs = observed_monthly_mm(rid)
        if obs is None or obs.empty:
            print('%-10s   no observed data' % region.name)
            continue
        res = skill_gate(rid, fcst, obs)
        if res is None:
            print('%-10s   insufficient overlap' % region.name)
            continue
        name = region.name[:9]
        print('%-10s %6d %8.3f %8.3f' % (name, res['n'], res['corr'], res['auc']))
        aucs.append(res['auc'])
        corrs.append(res['corr'])

    if aucs:
        med_auc = float(np.median(aucs))
        verdict = 'GO' if med_auc >= 0.60 else 'NO-GO'
        print('\nMedian AUC = %.3f  ->  %s' % (med_auc, verdict))
        print('(GO requires median AUC >= 0.60 across regions)')


if __name__ == '__main__':
    main()

