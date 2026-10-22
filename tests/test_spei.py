import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')
django.setup()

import numpy as np
import pandas as pd
from dashboard.prediction_engine.physical_helpers import calculate_spei, calculate_spi

# Generate 10 years of synthetic daily rainfall + ET0
np.random.seed(42)
dates = pd.date_range('2015-01-01', '2024-12-31', freq='D')
n = len(dates)

# Seasonal rainfall pattern (Mediterranean): wet winters, dry summers
month_sin = np.sin(2 * np.pi * dates.month / 12)
rainfall = np.maximum(0, 3.0 + 2.5 * month_sin + np.random.normal(0, 1.5, n))
et0 = np.maximum(0, 2.0 - 1.5 * month_sin + np.random.normal(0, 0.8, n))

rain_series = pd.Series(rainfall, index=dates, name='rainfall_mm')
et0_series = pd.Series(et0, index=dates, name='et0_mm')

# Compute SPI-3 and SPEI-3
spi3 = calculate_spi(rain_series, nmonth=3)
spei3 = calculate_spei(rain_series, et0_series, nmonth=3)

print(f'SPI-3: {spi3.notna().sum()} valid values, range [{spi3.min():.2f}, {spi3.max():.2f}]')
print(f'SPEI-3: {spei3.notna().sum()} valid values, range [{spei3.min():.2f}, {spei3.max():.2f}]')

# Sample values
valid_spei = spei3.dropna()
print(f'\nSample SPEI-3 values (first 12):')
for i, (idx, val) in enumerate(valid_spei.head(12).items()):
    print(f'  {idx.date()}: SPEI-3 = {val}')

# Distribution
print(f'\nSPEI-3 distribution:')
for label, lo, hi in [('Drought (< -1.5)', -99, -1.5), ('Severe', -1.5, -1.0), ('Moderate', -1.0, -0.5), ('Normal', -0.5, 0.5), ('Wet', 0.5, 1.0), ('Very wet', 1.0, 99)]:
    cnt = ((valid_spei >= lo) & (valid_spei < hi)).sum()
    print(f'  {label}: {cnt} months ({100*cnt/len(valid_spei):.1f}%)')
