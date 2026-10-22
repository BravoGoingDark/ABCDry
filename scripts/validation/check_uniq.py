import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')
django.setup()
from django.db import connection
cur = connection.cursor()
for t in ['climatemetrics','remotesensingmetrics','soilmetrics','hydrologymetrics','droughtindices']:
    cur.execute("SELECT indexname, indexdef FROM pg_indexes WHERE tablename=%s AND indexdef LIKE %s", [t, '%UNIQUE%'])
    print(f'--- {t} ---')
    for r in cur.fetchall():
        print(' ', r[0])
