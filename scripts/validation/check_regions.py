import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')
django.setup()
from dashboard.models import Region, ObservationYear

print('=== Regions in DB ===')
for r in Region.objects.all():
    print(f'  "{r.name}" (id={r.id})')

print('\n=== ObservationYear labels in DB ===')
years = ObservationYear.objects.all().order_by('label')
for y in years:
    print(f'  "{y.label}" (id={y.id})')