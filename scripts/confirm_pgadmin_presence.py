from django.db import connection
from dashboard.models import CropType, AgriculturalMetrics
import json

def run_sql(sql):
    with connection.cursor() as cur:
        cur.execute(sql)
        try:
            cols = [c[0] for c in cur.description]
            rows = cur.fetchall()
            return cols, rows
        except Exception:
            return None, None

print('Schema search_path:')
cols, rows = run_sql("SHOW search_path;")
print(rows)

print('\nPublic tables exist check:')
cols, rows = run_sql("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name;")
print(len(rows), 'tables in public schema')

for t in ('crop_types','agricultural_metrics'):
    print(f"\nChecking table: {t}")
    cols, rows = run_sql(f"SELECT COUNT(*) FROM {t};")
    print('count:', rows[0][0])
    cols, rows = run_sql(f"SELECT * FROM {t} LIMIT 5;")
    if rows:
        print('sample rows (up to 5):')
        print(json.dumps([dict(zip(cols, r)) for r in rows], default=str, indent=2))
    else:
        print('no sample rows or unable to fetch')

print('\nDjango ORM checks:')
print('CropType count:', CropType.objects.count())
print('AgriculturalMetrics count:', AgriculturalMetrics.objects.count())
print('\nCropType samples:')
for c in CropType.objects.all()[:10]:
    print(c.id, c.name)

print('\nAgriculturalMetrics samples:')
for a in AgriculturalMetrics.objects.select_related('crop')[:10]:
    print(a.id, 'crop_id=', a.crop_id, 'crop_name=', a.crop.name if a.crop else None)
