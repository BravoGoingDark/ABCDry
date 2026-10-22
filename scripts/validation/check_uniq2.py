import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')
django.setup()
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder

applied = set(MigrationRecorder.Migration.objects.filter(app='dashboard').values_list('name', flat=True))
print('0020 applied?', '0020_multi_point_unique_constraints' in applied)

cur = connection.cursor()
tables = ['climate_metrics','remote_sensing_metrics','soil_metrics','drought_indices','hydrology_metrics','agricultural_metrics']
for t in tables:
    cur.execute("SELECT indexname, indexdef FROM pg_indexes WHERE tablename=%s AND indexdef LIKE %s", [t, '%UNIQUE%'])
    rows = cur.fetchall()
    print(f'\n--- {t}: {len(rows)} unique index(es) ---')
    for r in rows:
        print('  ', r[0])
        print('     ', r[1])
