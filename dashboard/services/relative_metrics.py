"""Relative calculations for the Calculations page.

Every metric is shown as its latest value *relative to* a reference:

* ``normal``    - the seasonal normal: mean of the same calendar month in all
                  other years on record (all-time mean if a month has < 3 dates)
* ``previous``  - the previous reading
* ``last_year`` - the reading closest to the same date one year earlier

Values are averaged per date first, so stations / crops that share a date
count once.  Metrics whose natural zero is meaningful (SPI, SPEI, balances)
are compared as a difference; everything else as a percentage.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Optional

from django.db.models import Avg

from ..models import (
    AgriculturalMetrics,
    ClimateMetrics,
    DroughtIndices,
    HydrologyMetrics,
    RemoteSensingMetrics,
    SoilMetrics,
)

# Fields that are centred on zero or can be negative: compare as a difference.
DIFF_FIELDS = {
    'spi_1month', 'spi_3month', 'spi_12month',
    'spei_1month', 'spei_3month', 'spei_12month', 'pdsi_value',
    'water_balance_percent', 'yield_reduction_factor', 'ndwi',
}


@dataclass
class Spec:
    key: str
    name: str
    model: type
    fields: tuple
    unit: str
    formula: str
    direction: int = 0           # +1 higher = wetter/better, -1 higher = drier/worse
    kind: str = 'pct'            # 'pct' or 'diff'
    tol: float = 5.0             # |relative| below this counts as "near normal"
    window: int = 0              # >0: sum over the last N days instead of a single reading
    fn: Optional[Callable] = None
    decimals: int = 2


def _one(f):
    return (f,)


SECTIONS = [
    ('soil', 'Soil', [
        Spec('sm', 'Soil moisture', SoilMetrics, _one('moisture_content_percent'), '%', 'Measured volumetric water content', +1),
        Spec('fc', 'Field capacity', SoilMetrics, _one('field_capacity_percent'), '%', 'Saxton & Rawls: 0.28 + 0.57·clay − 0.24·sand'),
        Spec('wp', 'Wilting point', SoilMetrics, _one('wilting_point_percent'), '%', 'Saxton & Rawls: 0.06 + 0.42·clay − 0.07·sand'),
        Spec('paw', 'Plant-available water', SoilMetrics, ('field_capacity_percent', 'wilting_point_percent'), '%',
             'FC − WP', +1, fn=lambda fc, wp: fc - wp),
        Spec('om', 'Organic matter', SoilMetrics, _one('organic_matter_percent'), '%', 'Loss on ignition', +1),
    ]),
    ('climate', 'Climate', [
        Spec('rain30', 'Rainfall, last 30 days', ClimateMetrics, _one('rainfall_mm'), 'mm', 'Σ daily rainfall over 30 days', +1, window=30, decimals=1),
        Spec('wb30', 'Water balance, last 30 days', ClimateMetrics, ('rainfall_mm', 'evapotranspiration_et0_mmday'), 'mm',
             'Σ (P − ET₀) over 30 days', +1, kind='diff', tol=10, window=30, fn=lambda p, e: p - e, decimals=1),
        Spec('tmean', 'Mean temperature', ClimateMetrics, _one('temperature_mean_c'), '°C', '(Tmax + Tmin) ÷ 2', -1, kind='diff', tol=1, decimals=1),
        Spec('tmax', 'Max temperature', ClimateMetrics, _one('temperature_max_c'), '°C', 'Station / reanalysis daily maximum', -1, kind='diff', tol=1, decimals=1),
        Spec('et0', 'Reference ET (ET₀)', ClimateMetrics, _one('evapotranspiration_et0_mmday'), 'mm/day', 'FAO-56 Penman-Monteith', -1),
        Spec('rh', 'Relative humidity', ClimateMetrics, _one('relative_humidity_percent'), '%', 'Station measurement', +1, decimals=0),
        Spec('wind', 'Wind speed', ClimateMetrics, _one('wind_speed_ms'), 'm/s', 'Station measurement (2 m)', -1),
    ]),
    ('drought', 'Drought indices', [
        Spec('spi1', 'SPI 1-month', DroughtIndices, _one('spi_1month'), '', 'Gamma fit of 1-month rainfall → standard normal', +1, kind='diff', tol=0.25),
        Spec('spi3', 'SPI 3-month', DroughtIndices, _one('spi_3month'), '', 'Gamma fit of 3-month rainfall → standard normal', +1, kind='diff', tol=0.25),
        Spec('spi12', 'SPI 12-month', DroughtIndices, _one('spi_12month'), '', 'Gamma fit of 12-month rainfall → standard normal', +1, kind='diff', tol=0.25),
        Spec('spei1', 'SPEI 1-month', DroughtIndices, _one('spei_1month'), '', 'Log-logistic fit of 1-month (P − ET₀)', +1, kind='diff', tol=0.25),
        Spec('spei3', 'SPEI 3-month', DroughtIndices, _one('spei_3month'), '', 'Log-logistic fit of 3-month (P − ET₀)', +1, kind='diff', tol=0.25),
        Spec('spei12', 'SPEI 12-month', DroughtIndices, _one('spei_12month'), '', 'Log-logistic fit of 12-month (P − ET₀)', +1, kind='diff', tol=0.25),
        Spec('pdsi', 'PDSI', DroughtIndices, _one('pdsi_value'), '', 'Palmer soil water balance', +1, kind='diff', tol=0.5),
    ]),
    ('remote', 'Satellite', [
        Spec('ndvi', 'NDVI', RemoteSensingMetrics, _one('ndvi'), '', '(NIR − Red) ÷ (NIR + Red)', +1, decimals=3),
        Spec('ndwi', 'NDWI', RemoteSensingMetrics, _one('ndwi'), '', '(Green − NIR) ÷ (Green + NIR)', +1, kind='diff', tol=0.02, decimals=3),
        Spec('lst', 'Land surface temperature', RemoteSensingMetrics, _one('land_surface_temperature_c'), '°C', 'Thermal-infrared split-window', -1, kind='diff', tol=1, decimals=1),
        Spec('ssm', 'Satellite soil moisture', RemoteSensingMetrics, _one('satellite_soil_moisture_percent'), '%', 'Microwave radiometer, top 5 cm', +1),
        Spec('vci', 'Vegetation condition (VCI)', RemoteSensingMetrics, _one('vegetation_condition_index'), '%', '(NDVI − min) ÷ (max − min) × 100', +1),
    ]),
    ('hydro', 'Hydrology', [
        Spec('gw', 'Groundwater depth', HydrologyMetrics, _one('groundwater_depth_m'), 'm', 'Well / piezometer reading', -1),
        Spec('runoff', 'Runoff', HydrologyMetrics, _one('runoff_mm'), 'mm', 'SCS-CN: (P − 0.2S)² ÷ (P + 0.8S)', +1),
        Spec('flow', 'River flow', HydrologyMetrics, _one('river_flow_m3s'), 'm³/s', 'Rating curve Q = a·hᵇ', +1),
        Spec('hwb', 'Water balance', HydrologyMetrics, _one('water_balance_percent'), '%', '(Supply − Demand) ÷ Demand × 100', +1, kind='diff', tol=5),
    ]),
    ('agri', 'Crops', [
        Spec('kc', 'Crop coefficient (Kc)', AgriculturalMetrics, _one('crop_coefficient_kc'), '', 'FAO-56 growth-stage table (mean of crops)'),
        Spec('cwr', 'Crop water requirement', AgriculturalMetrics, _one('crop_water_requirement_mmday'), 'mm/day', 'ETc = ET₀ × Kc', -1),
        Spec('yrf', 'Yield reduction', AgriculturalMetrics, _one('yield_reduction_factor'), '', '1 − actual ÷ potential yield', -1, kind='diff', tol=0.05),
        Spec('ie', 'Irrigation efficiency', AgriculturalMetrics, _one('irrigation_efficiency_percent'), '%', 'Water used ÷ water applied', +1),
    ]),
]


# ---------------------------------------------------------------- series --

def _daily_series(spec: Spec, region, until=None) -> dict:
    """{date: value}, averaged across all rows (stations, crops) on each date."""
    qs = spec.model.objects.filter(region=region)
    for f in spec.fields:
        qs = qs.filter(**{f'{f}__isnull': False})
    if until:
        qs = qs.filter(measurement_date__lte=until)
    rows = qs.values('measurement_date').annotate(
        **{f'v{i}': Avg(f) for i, f in enumerate(spec.fields)}
    ).order_by('measurement_date')
    out = {}
    for r in rows:
        args = [float(r[f'v{i}']) for i in range(len(spec.fields))]
        d = r['measurement_date']
        d = d.date() if isinstance(d, dt.datetime) else d
        out[d] = spec.fn(*args) if spec.fn else args[0]
    return out


def _window_sum(series: dict, end: dt.date, days: int, min_cover: float = 0.8):
    vals = [series[d] for d in (end - dt.timedelta(days=i) for i in range(days)) if d in series]
    if len(vals) < days * min_cover:
        return None
    return sum(vals)


def _shift_year(d: dt.date, years: int) -> dt.date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:          # 29 Feb
        return d.replace(year=d.year + years, day=28)


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def _compare(spec: Spec, series: dict) -> Optional[dict]:
    if not series:
        return None
    dates = sorted(series)
    last = dates[-1]

    if spec.window:
        current = _window_sum(series, last, spec.window)
        if current is None:
            return None
        previous = _window_sum(series, last - dt.timedelta(days=spec.window), spec.window)
        last_year = _window_sum(series, _shift_year(last, -1), spec.window)
        sums = []
        for y in sorted({d.year for d in dates}):
            if y == last.year:
                continue
            s = _window_sum(series, _shift_year(last, y - last.year), spec.window)
            if s is not None:
                sums.append(s)
        normal = _mean(sums)
        normal_label = f'avg of same 30 days ({len(sums)} yrs)' if sums else ''
    else:
        current = series[last]
        previous = series[dates[-2]] if len(dates) > 1 else None
        # closest reading to one year earlier, within 20 days
        target = _shift_year(last, -1)
        near = [d for d in dates if abs((d - target).days) <= 20]
        last_year = series[min(near, key=lambda d: abs((d - target).days))] if near else None
        same_month = [series[d] for d in dates if d.month == last.month and d.year != last.year]
        if len(same_month) >= 3:
            normal = _mean(same_month)
            years = len({d.year for d in dates if d.month == last.month and d.year != last.year})
            normal_label = f'{last:%b} avg ({years} yrs)'
        else:
            others = [series[d] for d in dates if d.year != last.year]
            normal = _mean(others)
            normal_label = 'all-time avg' if others else ''

    def rel(ref):
        if ref is None:
            return None
        diff = current - ref
        if spec.kind == 'pct' and abs(ref) > 1e-9:
            value, kind = diff / abs(ref) * 100.0, 'pct'
        else:
            value, kind = diff, 'diff'
        tol = spec.tol if kind == spec.kind else 0.05 * max(abs(ref), 1.0)
        signed = value * spec.direction
        if abs(value) < tol or spec.direction == 0:
            state = 'normal' if abs(value) < tol else 'neutral'
        else:
            state = 'better' if signed > 0 else 'worse'
        return {
            'ref': round(ref, spec.decimals),
            'value': round(value, 1 if kind == 'pct' else spec.decimals),
            'kind': kind,
            'state': state,
        }

    return {
        'date': last,
        'current': round(current, spec.decimals),
        'normal_label': normal_label,
        'rel': {
            'normal': rel(normal),
            'previous': rel(previous),
            'last_year': rel(last_year),
        },
        'previous_date': dates[-2] if len(dates) > 1 and not spec.window else None,
        'n_dates': len(dates),
    }


def build_sections(region, until=None) -> tuple[list, list]:
    """Return (sections with data, names of metrics without data)."""
    sections, missing = [], []
    for sid, title, specs in SECTIONS:
        items = []
        for spec in specs:
            result = _compare(spec, _daily_series(spec, region, until))
            if result is None:
                missing.append(spec.name)
                continue
            items.append({
                'key': spec.key, 'name': spec.name, 'unit': spec.unit,
                'formula': spec.formula, 'direction': spec.direction, **result,
            })
        if items:
            sections.append({'id': sid, 'title': title, 'items': items})
    return sections, missing


# ------------------------------------------------------- chart anomalies --

def relative_series(dates: list, values: list, field_name: str) -> tuple[list, str]:
    """Turn a per-date series into departures from its calendar-month normal.

    Returns (relative values, unit) - percent of normal, or a plain
    difference for zero-centred fields.
    """
    by_month = defaultdict(list)
    for d, v in zip(dates, values):
        by_month[d.month].append(v)
    normals = {m: _mean(v) for m, v in by_month.items()}
    as_diff = field_name in DIFF_FIELDS
    out = []
    for d, v in zip(dates, values):
        n = normals[d.month]
        if as_diff or abs(n) < 1e-9:
            out.append(round(v - n, 3))
        else:
            out.append(round((v - n) / abs(n) * 100.0, 1))
    return out, ('Δ vs monthly normal' if as_diff else '% vs monthly normal')
