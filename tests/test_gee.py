import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')
django.setup()
from decouple import config
import ee
from google.oauth2 import service_account

creds = config('GEE_CREDENTIALS_FILE')
with open(creds) as f:
    import json
    project = json.load(f).get('project_id')
credentials = service_account.Credentials.from_service_account_file(
    creds, scopes=['https://www.googleapis.com/auth/earthengine.readonly'])
ee.Initialize(credentials, project=project)

# Test: sample Sentinel-2 NDVI at the first v8 point for a mid-2024 date
point = ee.Geometry.Point(9.318, 37.117)
img = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
       .filterBounds(point)
       .filterDate('2024-06-01', '2024-06-16')
       .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 30))
       .sort('system:time_start', False)
       .first())
if img is None:
    print('S2 image None')
else:
    ndvi = img.normalizedDifference(['B8', 'B4']).rename('ndvi')
    val = ndvi.reduceRegion(reducer=ee.Reducer.max(),
                            geometry=point.buffer(3000), scale=10,
                            bestEffort=True).get('ndvi').getInfo()
    print('S2 NDVI test:', val)

# Test CHIRPS rain
img2 = (ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY')
        .filterBounds(point)
        .filterDate('2024-06-01', '2024-06-02').first())
if img2 is None:
    print('CHIRPS image None')
else:
    r = img2.reduceRegion(reducer=ee.Reducer.mean(), geometry=point.buffer(5566),
                          scale=5566, bestEffort=True).get('precipitation').getInfo()
    print('CHIRPS rain test:', r)

# Test ERA5
img3 = (ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR')
        .filterBounds(point)
        .filterDate('2024-06-01', '2024-06-02').first())
if img3 is None:
    print('ERA5 image None')
else:
    t = img3.select(['temperature_2m_max']).reduceRegion(
        reducer=ee.Reducer.mean(), geometry=point, scale=11132,
        bestEffort=True).get('temperature_2m_max').getInfo()
    print('ERA5 Tmax test:', t)