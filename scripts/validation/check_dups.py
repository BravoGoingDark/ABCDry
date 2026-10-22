import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')
django.setup()
from django.db import connection
cur = connection.cursor()
tables = ['climate_metrics','remote_sensing_metrics','soil_metrics','drought_indices','hydrology_metrics']
for t in tables:
    cur.execute(f"""
        SELECT COUNT(*) FROM (
          SELECT region_id, year_id, time, latitude, longitude, COUNT(*) c
          FROM "{t}"
          GROUP BY region_id, year_id, time, latitude, longitude
          HAVING COUNT(*) > 1
        ) dup
    """)
    print(f'{t}: duplicate (region,year,time,lat,lon) groups =', cur.fetchone()[0])
