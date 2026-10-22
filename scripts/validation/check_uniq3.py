import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')
django.setup()
from django.db import connection
cur = connection.cursor()
cur.execute("SELECT conname, conrelid::regclass FROM pg_constraint WHERE connamespace='public'::regnamespace AND contype='u' ORDER BY conrelid::regclass::text")
for r in cur.fetchall():
    print(r)
