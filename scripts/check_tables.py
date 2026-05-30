import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','agri_dashboard.settings')
import django
django.setup()
from django.db import connection
cur = connection.cursor()
for t in ('soil_metrics','dashboard_soilmetrics'):
    try:
        cur.execute(f"SELECT COUNT(*) FROM public.{t}")
        print(t, cur.fetchone()[0])
    except Exception as e:
        print(t, 'error:', e)

from dashboard.models import SoilMetrics
print('Model db_table =', SoilMetrics._meta.db_table)
print('Sample dashboard_soilmetrics rows:')
for r in SoilMetrics.objects.order_by('-measurement_date')[:5].values():
    print(r)
