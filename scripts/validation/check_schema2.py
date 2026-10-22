import sqlite3

conn = sqlite3.connect('db.sqlite3')
c = conn.cursor()

print("=== applied migrations ===")
c.execute("SELECT app, name FROM django_migrations ORDER BY app, name")
for r in c.fetchall():
    print(f'  {r[0]} {r[1]}')

# Check what tables have real columns matching models
print("\n=== key table columns ===")
for t in ['dashboard_soilmetrics','dashboard_climatemetrics','dashboard_droughtindices','dashboard_agriculturalmetrics','dashboard_remotesensingmetrics','dashboard_hydrologymetrics']:
    try:
        c.execute(f'PRAGMA table_info("{t}")')
        cols = [r[1] for r in c.fetchall()]
        print(f'{t}: {cols}')
    except Exception as e:
        print(f'{t}: ERR {e}')

conn.close()
