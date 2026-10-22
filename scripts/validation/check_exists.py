import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')
django.setup()
from django.db import connection

cur = connection.cursor()
for t in ['climatemetrics', 'regions', 'remotesensingmetrics', 'droughtindices', 'soilmetrics']:
    cur.execute("SELECT to_regclass(%s)", [t])
    print(f'{t} exists?', cur.fetchone()[0])
    try:
        cur.execute(f'SELECT COUNT(*) FROM "{t}"')
        print(f'   count =', cur.fetchone()[0])
    except Exception as e:
        print('   err:', e)

print('DB name:', connection.settings_dict.get('NAME'))
print('HOST:', connection.settings_dict.get('HOST'))
