import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')
django.setup()
from django.db import connection
cur = connection.cursor()
cur.execute("SHOW search_path")
print('search_path:', cur.fetchone())
cur.execute("SELECT schemaname, tablename FROM pg_tables WHERE tablename IN ('climatemetrics','regions','remotesensingmetrics') ORDER BY schemaname, tablename")
for r in cur.fetchall():
    print(r)
