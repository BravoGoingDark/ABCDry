import sqlite3

conn = sqlite3.connect('db.sqlite3')
c = conn.cursor()

c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in c.fetchall()]
print("ALL TABLES:", tables)

for t in ['regions', 'dashboard_region']:
    if t in tables:
        c.execute(f'PRAGMA table_info("{t}")')
        cols = c.fetchall()
        print(f'\n=== {t} columns ===')
        for r in cols:
            print(f'  {r[1]} {r[2]}')
        c.execute(f'SELECT COUNT(*) FROM "{t}"')
        print(f'  rows: {c.fetchone()[0]}')
        try:
            c.execute(f'SELECT * FROM "{t}"')
            for row in c.fetchall():
                print(f'  {row}')
        except Exception as e:
            print(f'  select err: {e}')

conn.close()
