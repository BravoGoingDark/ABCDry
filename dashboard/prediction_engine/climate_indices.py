"""Climate teleconnection indices (NAO - North Atlantic Oscillation).

Ingests monthly NOAA Climate Prediction Center (CPC) standardized NAO indices,
which govern seasonal storm tracks and rainfall variability across the Western
Mediterranean and North Africa (including Tunisia).
"""
import io
import logging
import os
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
from django.conf import settings

logger = logging.getLogger(__name__)

NOAA_NAO_URL = 'https://www.cpc.ncep.noaa.gov/products/precip/CWlink/pna/norm.nao.monthly.b5001.current.ascii'


def get_climate_data_dir() -> Path:
    """Return directory for cached climate index data."""
    base = Path(settings.BASE_DIR) if hasattr(settings, 'BASE_DIR') else Path.cwd()
    data_dir = base / 'data' / 'climate_indices'
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def fetch_or_load_nao(force_refresh: bool = False) -> pd.DataFrame:
    """Load monthly NAO index as DataFrame indexed by monthly PeriodIndex.

    Columns: ['nao_index', 'nao_lag1', 'nao_lag2', 'nao_lag3', 'nao_3m']
    Caches locally to disk to avoid repeated network requests.
    """
    cache_file = get_climate_data_dir() / 'nao_monthly.csv'

    df = None
    if cache_file.exists() and not force_refresh:
        try:
            df = pd.read_csv(cache_file)
            df['period'] = pd.PeriodIndex(df['period'], freq='M')
            df = df.set_index('period')
        except Exception as exc:
            logger.warning('Failed reading cached NAO index (%s); re-fetching', exc)
            df = None

    if df is None:
        try:
            req = urllib.request.Request(NOAA_NAO_URL, headers={'User-Agent': 'Mozilla/5.0 (AgriPlatform/1.0)'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw_text = resp.read().decode('utf-8')

            records = []
            for line in raw_text.strip().splitlines():
                parts = line.strip().split()
                if len(parts) >= 3:
                    try:
                        yr, mo, val = int(parts[0]), int(parts[1]), float(parts[2])
                        records.append({'year': yr, 'month': mo, 'nao_index': val})
                    except (ValueError, IndexError):
                        continue

            raw_df = pd.DataFrame(records)
            raw_df['period'] = pd.PeriodIndex.from_fields(
                year=raw_df['year'], month=raw_df['month'], freq='M'
            )
            raw_df = raw_df.drop_duplicates(subset=['period']).sort_values('period')
            df = raw_df.set_index('period')[['nao_index']]

            # Compute lags and 3-month moving average
            df['nao_lag1'] = df['nao_index'].shift(1)
            df['nao_lag2'] = df['nao_index'].shift(2)
            df['nao_lag3'] = df['nao_index'].shift(3)
            df['nao_3m'] = df['nao_index'].rolling(3, min_periods=2).mean()

            # Save to cache
            out_df = df.reset_index()
            out_df['period'] = out_df['period'].astype(str)
            out_df.to_csv(cache_file, index=False)
            logger.info('Cached %d monthly NAO records to %s', len(df), cache_file)

        except Exception as exc:
            logger.warning('Failed fetching NOAA NAO data (%s); falling back to neutral/zeros', exc)
            # Offline emergency fallback
            periods = pd.period_range('1990-01', '2030-12', freq='M')
            df = pd.DataFrame({
                'nao_index': 0.0,
                'nao_lag1': 0.0,
                'nao_lag2': 0.0,
                'nao_lag3': 0.0,
                'nao_3m': 0.0,
            }, index=periods)

    return df


def merge_nao_features(monthly_df: pd.DataFrame) -> pd.DataFrame:
    """Merge NAO index features onto a monthly DataFrame indexed by monthly PeriodIndex."""
    nao_df = fetch_or_load_nao()
    if monthly_df.empty or nao_df.empty:
        return monthly_df

    # Match by calendar month period
    cols = ['nao_index', 'nao_lag1', 'nao_lag2', 'nao_lag3', 'nao_3m']
    res = monthly_df.join(nao_df[cols], how='left')
    return res
