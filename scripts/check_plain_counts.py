import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')
import django
django.setup()
from django.db import connection
cur = connection.cursor()
tables = ['regions','observation_years','crop_types','irrigation_methods','environmental_snapshots','soil_metrics','climate_metrics','drought_indices','agricultural_metrics','remote_sensing_metrics','hydrology_metrics','risk_assessments','data_import_logs','audit_logs','login_attempts','user_sessions','user_activity_log']
for table in tables:
    try:
        cur.execute(f'SELECT COUNT(*) FROM public.{table}')
        print(f'{table}: {cur.fetchone()[0]}')
    except Exception as exc:
        print(f'{table}: ERROR {exc}')
