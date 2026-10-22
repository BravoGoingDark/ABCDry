import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')
django.setup()
from django.db import connection

cur = connection.cursor()
tables = ['climate_metrics','remote_sensing_metrics','soil_metrics','drought_indices','hydrology_metrics','agricultural_metrics','regions']
for t in tables:
    cur.execute("SELECT to_regclass(%s)", [t])
    print(f'{t}: exists?', cur.fetchone()[0])

print('\n--- columns of remote_sensing_metrics ---')
cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='remote_sensing_metrics' ORDER BY ordinal_position")
for r in cur.fetchall():
    print('  ', r[0])
