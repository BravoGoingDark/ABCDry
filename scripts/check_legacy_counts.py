import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')
import django
django.setup()
from django.db import connection
cur = connection.cursor()
for table in ['dashboard_region','dashboard_observationyear','dashboard_croptype','dashboard_irrigationmethod','dashboard_environmentalsnapshot','dashboard_soilmetrics','dashboard_climatemetrics','dashboard_droughtindices','dashboard_agriculturalmetrics','dashboard_remotesensingmetrics','dashboard_hydrologymetrics','dashboard_riskassessment','dashboard_dataimportlog']:
    try:
        cur.execute(f'SELECT COUNT(*) FROM public.{table}')
        print(f'{table}: {cur.fetchone()[0]}')
    except Exception as exc:
        print(f'{table}: ERROR {exc}')
