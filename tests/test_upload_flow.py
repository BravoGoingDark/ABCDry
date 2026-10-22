import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')
django.setup()

import tempfile
import numpy as np
import pandas as pd

from dashboard.views.ingestion_views import _normalize_import_df, _import_climate_metrics
from dashboard.models import ClimateMetrics

# Build a file with the EXACT columns the user has
n = 30
dates = pd.date_range('2025-01-01', periods=n, freq='D')
df = pd.DataFrame({
    'Date': dates,
    'Precipitation_mm': np.round(np.random.uniform(0, 8, n), 1),
    'Tmean_C': np.round(np.random.uniform(15, 30, n), 1),
    'Tmin_C': np.round(np.random.uniform(10, 22, n), 1),
    'Tmax_C': np.round(np.random.uniform(22, 35, n), 1),
    'relative_humidity': np.round(np.random.uniform(40, 80, n), 0),
    'solar_radiation_MJ_m2_day': np.round(np.random.uniform(10, 25, n), 2),
    'wind_speed_10m': np.round(np.random.uniform(0.5, 6, n), 2),
})

# Save to temp xlsx (simulating upload)
with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as f:
    tmp = f.name
df.to_excel(tmp, index=False)

# Read as the view would
uploaded = pd.read_excel(tmp)
print('Raw columns:', list(uploaded.columns))

# Normalize (simulating region selected = Ichkeul id 4)
norm_df, norm_errors = _normalize_import_df(uploaded, 'climate', region_name='Ichkeul')
print('\nNormalized columns:', list(norm_df.columns))
print('Normalize errors:', norm_errors)
print('Region values:', sorted(norm_df['region'].unique()))
print('Year values:', sorted(norm_df['year'].unique())[:5], '...')
print('measurement_date sample:', norm_df['measurement_date'].head(2).tolist())

# Run the import
errors = list(norm_errors)
result = _import_climate_metrics(norm_df, errors)
print('\nImport result:', result)
print('Errors:', errors[:5])

# Verify in DB
count = ClimateMetrics.objects.filter(region_id=4, measurement_date__year=2025).count()
print('\nRows in DB for Ichkeul 2025:', count)
sample = ClimateMetrics.objects.filter(region_id=4, measurement_date__year=2025).first()
if sample:
    print('Sample row:', sample.measurement_date, 'rain=', sample.rainfall_mm, 'tmean=', sample.temperature_mean_c)

os.remove(tmp)