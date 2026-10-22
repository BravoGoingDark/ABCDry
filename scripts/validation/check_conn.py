import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')
django.setup()
from django.db import connection
print('DB:', connection.settings_dict.get('NAME'))
print('ENGINE:', connection.settings_dict.get('ENGINE'))
print('HOST:', connection.settings_dict.get('HOST'))

# Check regions
from dashboard.models import Region
for r in Region.objects.all():
    print(f'Region {r.id} ({r.name}): lat={r.latitude}, lon={r.longitude}, sample_points={r.sample_points}')

# Check if the table actually has data via raw SQL
cur = connection.cursor()
cur.execute('SELECT COUNT(*) FROM remote_sensing_metrics')
print('remote_sensing_metrics raw count:', cur.fetchone()[0])
cur.execute('SELECT COUNT(*) FROM climate_metrics')
print('climate_metrics raw count:', cur.fetchone()[0])
