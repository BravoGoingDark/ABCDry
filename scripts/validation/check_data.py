import sqlite3, os

db = 'db.sqlite3'
if not os.path.exists(db):
    print('No db.sqlite3 found')
else:
    conn = sqlite3.connect(db)
    c = conn.cursor()

    # Check all dashboard tables
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'dashboard_%'")
    tables = [r[0] for r in c.fetchall()]

    for t in tables:
        c.execute(f'SELECT COUNT(*) FROM "{t}"')
        cnt = c.fetchone()[0]
        print(f'{t}: {cnt} rows')

    print('\n--- RemoteSensingMetrics detail ---')
    c.execute('SELECT COUNT(*) FROM dashboard_remotesensingmetrics')
    total = c.fetchone()[0]
    print(f'Total: {total}')

    if total > 0:
        c.execute('SELECT region_id, COUNT(*) FROM dashboard_remotesensingmetrics GROUP BY region_id')
        for r in c.fetchall():
            print(f'  Region {r[0]}: {r[1]} rows')

        c.execute('SELECT MIN(date), MAX(date) FROM dashboard_remotesensingmetrics')
        row = c.fetchone()
        print(f'  Date range: {row[0]} to {row[1]}')

        c.execute('SELECT subregion, COUNT(*) FROM dashboard_remotesensingmetrics GROUP BY subregion')
        for r in c.fetchall():
            print(f'  Subregion: {r[0]} -> {r[1]} rows')

        # Check coordinates
        try:
            c.execute('SELECT DISTINCT point_lat, point_lon, subregion FROM dashboard_remotesensingmetrics ORDER BY subregion')
            for r in c.fetchall():
                print(f'  Point: lat={r[0]}, lon={r[1]}, subregion={r[2]}')
        except Exception as e:
            print(f'  (no point_lat/point_lon columns: {e})')

    # Check region sample_points
    print('\n--- Regions ---')
    c.execute('SELECT id, name, sample_points FROM dashboard_region')
    for r in c.fetchall():
        print(f'  Region {r[0]} ({r[1]}): sample_points={r[2]}')

    conn.close()
