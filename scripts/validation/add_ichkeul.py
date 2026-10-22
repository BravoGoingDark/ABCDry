import os
import sys
import django
import subprocess

try:
    import pyproj
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyproj"])
    import pyproj

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')
django.setup()

from dashboard.models import Region

# UTM Zone 32N: epsg=32632
# WGS84: epsg=4326
transformer = pyproj.Transformer.from_crs("epsg:32632", "epsg:4326", always_xy=True)

lon1, lat1 = transformer.transform(528251.02, 4107899.00)
lon2, lat2 = transformer.transform(565033.48, 4096231.44)

print(f"Point 1 (v8 st humide inf): Lat={lat1}, Lon={lon1}")
print(f"Point 2 (v8 st sub humide): Lat={lat2}, Lon={lon2}")

center_lat = (lat1 + lat2) / 2
center_lon = (lon1 + lon2) / 2

region, created = Region.objects.get_or_create(
    name="Ichkeul",
    defaults={
        'country': 'Tunisia',
        'latitude': center_lat,
        'longitude': center_lon,
        'description': 'Ichkeul region with 2 sample points (v8 st humide inf and v8 st sub humide)',
    }
)
if not created:
    region.latitude = center_lat
    region.longitude = center_lon

region.sample_points = [
    {'lat': lat1, 'lon': lon1, 'name': 'v8 st humide inf'},
    {'lat': lat2, 'lon': lon2, 'name': 'v8 st sub humide'}
]
region.save()

print(f"Region Ichkeul saved with ID: {region.id}")
