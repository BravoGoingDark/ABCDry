import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')
django.setup()
from dashboard.models import ClimateMetrics
from django.db.models import Count, Q

total = ClimateMetrics.objects.filter(region_id=4).count()
print(f'Total ClimateMetrics region 4: {total}')

# Check ET0 coverage
has_et0 = ClimateMetrics.objects.filter(region_id=4, evapotranspiration_et0_mmday__isnull=False).count()
print(f'Has ET0: {has_et0}')

# Check what fields are populated
sample = ClimateMetrics.objects.filter(region_id=4).first()
if sample:
    print(f'Sample row: date={sample.measurement_date}, rain={sample.rainfall_mm}, temp={sample.temperature_mean_c}, rh={sample.relative_humidity_percent}, wind={sample.wind_speed_ms}, solar={sample.solar_radiation_mjm2day}, et0={sample.evapotranspiration_et0_mmday}')
