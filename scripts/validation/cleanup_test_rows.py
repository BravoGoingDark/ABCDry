import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')
django.setup()
from dashboard.models import ClimateMetrics

n, _ = ClimateMetrics.objects.filter(region_id=4, measurement_date__year=2025, latitude__isnull=True).delete()
print(f'Deleted {n} test climate rows')