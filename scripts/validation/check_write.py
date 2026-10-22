import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')
django.setup()
from dashboard.models import RemoteSensingMetrics, ClimateMetrics

print("--- RemoteSensingMetrics 2026-08-20..22 ---")
for o in RemoteSensingMetrics.objects.filter(region_id=4, measurement_date__gte='2026-08-20', measurement_date__lte='2026-08-22').order_by('measurement_date','subregion'):
    print(f'  {o.measurement_date} {o.latitude},{o.longitude} subregion={o.subregion} ndvi={o.ndvi} src={o.satellite_source}')

print("\n--- ClimateMetrics 2026-08-20..22 ---")
for o in ClimateMetrics.objects.filter(region_id=4, measurement_date__gte='2026-08-20', measurement_date__lte='2026-08-22').order_by('measurement_date','subregion'):
    print(f'  {o.measurement_date} {o.latitude},{o.longitude} subregion={o.subregion} rain={o.rainfall_mm}')