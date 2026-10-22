import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')
django.setup()
from django.db import connection
cur = connection.cursor()
for t in ['climatemetrics','remotesensingmetrics','soilmetrics','hydrologymetrics','droughtindices','agriculturalmetrics','regions']:
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s ORDER BY ordinal_position", [t])
    cols = [r[0] for r in cur.fetchall()]
    print(f'{t}: {cols}')
