import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')
import django
django.setup()
from django.db import connection
cur = connection.cursor()
cur.execute("SELECT pg_get_serial_sequence('data_import_logs','log_id')")
seq = cur.fetchone()[0]
cur.execute(f'SELECT last_value, is_called FROM {seq}')
print('sequence', seq, cur.fetchone())
cur.execute('SELECT MAX(log_id) FROM data_import_logs')
print('max_log_id', cur.fetchone()[0])
