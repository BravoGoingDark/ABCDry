# ============================================================================
# Migration Guide: SQLite → PostgreSQL + TimescaleDB + PostGIS
# ============================================================================
# This guide covers the complete migration from SQLite to a production-grade
# PostgreSQL 14+ database with TimescaleDB for time-series optimization,
# PostGIS for geospatial data, and PgBouncer for connection pooling.
# ============================================================================

## PHASE 1: PRE-MIGRATION PREPARATION
======================================

### 1.1 Environment Setup

#### Windows (Development)
```powershell
# Install PostgreSQL 14 (with PostGIS during installer)
choco install postgresql --params='/Password:your_password'

# Install pgAdmin 4 (GUI for database management)
choco install pgadmin4

# Install PgBouncer (via pre-built binaries or WSL)
# Download: https://pgbouncer.github.io/
# Or use WSL: sudo apt-get install pgbouncer

# Install pgBackRest (via WSL or pre-built)
sudo apt-get install pgbackrest

# Install TimescaleDB extension
# Via psql: CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
```

#### Linux (Production - Ubuntu/Debian)
```bash
# Add PostgreSQL repository
sudo sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo apt-key add -

# Install PostgreSQL 14 with PostGIS
sudo apt-get update
sudo apt-get install postgresql-14 postgresql-14-postgis-3 postgresql-14-postgis-3-scripts

# Install TimescaleDB
# Option A: Via APT (Recommended)
sudo apt-key adv --keyserver keyserver.ubuntu.com --recv-keys 17FAB2DE54A004A5
echo "deb https://packagecloud.io/timescale/timescaledb/ubuntu/ $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/timescaledb.list
sudo apt-get update
sudo apt-get install timescaledb-2-postgresql-14

# Install PgBouncer
sudo apt-get install pgbouncer

# Install pgBackRest
sudo apt-get install pgbackrest

# Install additional utilities
sudo apt-get install postgresql-contrib-14 postgresql-client-14
```

#### macOS (Intel/Apple Silicon)
```bash
# Using Homebrew
brew install postgresql@14
brew install postgis
brew install timescaledb
brew install pgbouncer
brew install pgbackrest

# Start PostgreSQL
brew services start postgresql@14
```

### 1.2 Backup Current SQLite Database

```bash
# On development machine, backup existing SQLite
cp db.sqlite3 db.sqlite3.backup.$(date +%Y%m%d_%H%M%S)

# Verify backup integrity
sqlite3 db.sqlite3 "SELECT COUNT(*) FROM django_migrations;"
```

### 1.3 Install Python Dependencies

```bash
# Add database drivers to requirements.txt
pip install psycopg2-binary          # PostgreSQL adapter
pip install django-gevent-pool       # Connection pooling
pip install django-redis             # Redis caching
pip install django-cors-headers      # CORS support
pip install djangorestframework       # REST API framework
pip install django-extensions        # Management commands
pip install celery                   # Async tasks
pip install redis                    # Redis client
pip install django-db-geventpool     # Advanced pooling
pip install django-environ           # Environment variables (python-decouple)

# Install for Windows/macOS GDAL support
pip install gdal  # May require system library dependencies
```

```bash
# Save to requirements.txt
pip freeze > requirements.txt
```

---

## PHASE 2: DATABASE CREATION & CONFIGURATION
==============================================

### 2.1 Create PostgreSQL Database & User

```bash
# Connect to PostgreSQL as superuser
psql -U postgres -h localhost

# Create database
CREATE DATABASE agri_db
    ENCODING 'UTF8'
    LOCALE 'en_US.UTF-8'
    TEMPLATE template0;

# Create application user with limited privileges
CREATE USER agri_app_user WITH PASSWORD 'your_secure_password_here';

# Grant privileges
GRANT CONNECT ON DATABASE agri_db TO agri_app_user;
GRANT CREATE ON DATABASE agri_db TO agri_app_user;

# Set default privileges
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE ON TABLES TO agri_app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO agri_app_user;

# Optionally allow superuser for initial setup
ALTER USER agri_app_user CREATEDB;

# Exit psql
\q
```

### 2.2 Apply TimescaleDB Schema

```bash
# Copy schema file to server
scp database_schema_timescaledb.sql user@production-server:/tmp/

# Apply schema
psql -U agri_app_user -d agri_db -h localhost < database_schema_timescaledb.sql

# Verify installation
psql -U agri_app_user -d agri_db -h localhost

# In psql:
SELECT extname FROM pg_extension WHERE extname = 'timescaledb';  -- Should show timescaledb
SELECT * FROM timescaledb_information.hypertables;              -- Should show hypertables
SELECT COUNT(*) FROM regions;                                     -- Should show test data
```

### 2.3 Enable Required PostgreSQL Extensions

```bash
psql -U postgres -d agri_db -c "CREATE EXTENSION IF NOT EXISTS uuid-ossp CASCADE;"
psql -U postgres -d agri_db -c "CREATE EXTENSION IF NOT EXISTS pg_trgm CASCADE;"  -- For full-text search
psql -U postgres -d agri_db -c "CREATE EXTENSION IF NOT EXISTS pgcrypto CASCADE;"  -- For encryption
psql -U postgres -d agri_db -c "CREATE EXTENSION IF NOT EXISTS pg_stat_statements CASCADE;"  -- For query analysis
```

### 2.4 Configure PostgreSQL Performance

Edit `/etc/postgresql/14/main/postgresql.conf`:

```ini
# Memory settings (for 32GB server)
shared_buffers = 8GB
effective_cache_size = 24GB
maintenance_work_mem = 2GB
work_mem = 50MB

# Connection settings
max_connections = 200
max_prepared_transactions = 100

# Checkpoint settings
checkpoint_completion_target = 0.9
wal_buffers = 16MB
max_wal_size = 4GB
min_wal_size = 1GB

# Parallel query execution
max_parallel_workers_per_gather = 4
max_parallel_workers = 8

# Query optimization
random_page_cost = 1.1  # For SSD storage
effective_io_concurrency = 200

# Logging
log_statement = 'all'  # Change to 'mod' in production
log_duration = on
log_min_duration_statement = 1000  # Log queries over 1 second

# TimescaleDB
shared_preload_libraries = 'timescaledb'
timescaledb.license = 'community'

# WAL archiving (for pgBackRest)
archive_mode = on
archive_command = 'pgbackrest archive-push %p'
archive_timeout = 300
wal_level = replica
max_wal_senders = 10
wal_keep_size = 1GB
```

Reload configuration:
```bash
sudo systemctl restart postgresql
# or
sudo pg_ctl -D /var/lib/postgresql/14/main reload
```

### 2.5 Migrate Data from SQLite to PostgreSQL

#### Option A: Django dumpdata/loaddata (Simpler, for small datasets)

```bash
# 1. Dump data from SQLite
# (Make sure settings.py points to SQLite database)
python manage.py dumpdata --exclude auth --exclude sessions > fixture_data.json

# 2. Switch to PostgreSQL settings
# Edit settings.py or use settings_production.py

# 3. Run Django migrations
python manage.py migrate

# 4. Load data into PostgreSQL
python manage.py loaddata fixture_data.json

# 5. Verify data
python manage.py shell
>>> from dashboard.models import Region
>>> Region.objects.count()  # Should match SQLite count
```

#### Option B: Direct SQL Migration (Better for large datasets)

```bash
# 1. Export SQLite to SQL script
sqlite3 db.sqlite3 .dump > sqlite_dump.sql

# 2. Convert SQLite SQL to PostgreSQL SQL
# Edit sqlite_dump.sql to:
#   - Remove PRAGMA statements
#   - Replace AUTOINCREMENT with SERIAL/BIGSERIAL
#   - Fix data type mismatches
#   - Remove SQLite-specific constraints

# 3. Create Django migrations for new schema
python manage.py makemigrations
python manage.py migrate

# 4. Import data with Python script (see next section)
```

#### Option C: Python Script for Controlled Migration

```python
# migration_script.py
import os
import django
from django.conf import settings
from dashboard.models import (
    Region, ObservationYear, CropType, IrrigationMethod,
    EnvironmentalSnapshot, SoilMetrics, ClimateMetrics,
    DroughtIndices, AgriculturalMetrics, RemoteSensingMetrics,
    HydrologyMetrics, RiskAssessment, DataImportLog
)
import sqlite3
from datetime import datetime

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings_production')
django.setup()

# Connect to SQLite database
sqlite_db = sqlite3.connect('db.sqlite3')
sqlite_db.row_factory = sqlite3.Row
cursor = sqlite_db.cursor()

def migrate_regions():
    """Migrate regions from SQLite to PostgreSQL"""
    cursor.execute('SELECT * FROM dashboard_region')
    for row in cursor.fetchall():
        Region.objects.get_or_create(
            name=row['name'],
            defaults={
                'country': row.get('country'),
                'latitude': row.get('latitude'),
                'longitude': row.get('longitude'),
                'elevation_m': row.get('elevation_m'),
                'area_km2': row.get('area_km2'),
            }
        )
    print(f"✓ Migrated {Region.objects.count()} regions")

def migrate_observation_years():
    """Migrate observation years"""
    cursor.execute('SELECT * FROM dashboard_observationyear')
    for row in cursor.fetchall():
        ObservationYear.objects.get_or_create(
            label=row['label'],
            defaults={'start_date': row.get('start_date'), 'end_date': row.get('end_date')}
        )
    print(f"✓ Migrated {ObservationYear.objects.count()} observation years")

def migrate_climate_metrics():
    """Migrate climate metrics to TimescaleDB hypertable"""
    cursor.execute('SELECT * FROM dashboard_climatemetrics')
    count = 0
    for row in cursor.fetchall():
        try:
            region = Region.objects.get(id=row['region_id'])
            year = ObservationYear.objects.get(id=row['year_id'])
            
            ClimateMetrics.objects.get_or_create(
                region=region,
                year=year,
                measurement_date=row['measurement_date'],
                defaults={
                    'rainfall_mm': row.get('rainfall_mm'),
                    'temperature_max_c': row.get('temperature_max_c'),
                    'temperature_min_c': row.get('temperature_min_c'),
                    'temperature_mean_c': row.get('temperature_mean_c'),
                    'relative_humidity_percent': row.get('relative_humidity_percent'),
                    'wind_speed_ms': row.get('wind_speed_ms'),
                    'solar_radiation_mjm2day': row.get('solar_radiation_mjm2day'),
                    'evapotranspiration_et0_mmday': row.get('evapotranspiration_et0_mmday'),
                    'updated_at': datetime.now(),
                }
            )
            count += 1
        except Exception as e:
            print(f"  Error migrating climate metrics {row['id']}: {e}")
    
    print(f"✓ Migrated {count} climate metrics to TimescaleDB")

def migrate_soil_metrics():
    """Migrate soil metrics to TimescaleDB hypertable"""
    # Similar pattern to migrate_climate_metrics()
    # ...
    pass

def migrate_all():
    """Run all migrations"""
    print("Starting migration from SQLite to PostgreSQL + TimescaleDB...")
    print("-" * 60)
    
    migrate_regions()
    migrate_observation_years()
    # Add other migrations as needed
    migrate_climate_metrics()
    migrate_soil_metrics()
    
    print("-" * 60)
    print("✓ Migration completed successfully!")
    
    # Verify
    print("\nData counts:")
    print(f"  Regions: {Region.objects.count()}")
    print(f"  Climate metrics: {ClimateMetrics.objects.count()}")
    print(f"  Soil metrics: {SoilMetrics.objects.count()}")

if __name__ == '__main__':
    migrate_all()
```

Run migration:
```bash
python migration_script.py
```

### 2.6 Verify Data Migration

```bash
# Connect to PostgreSQL
psql -U agri_app_user -d agri_db

# Check hypertables contain data
SELECT COUNT(*) FROM climate_metrics;
SELECT COUNT(*) FROM soil_metrics;
SELECT COUNT(*) FROM drought_indices;

# Verify constraints and indexes
SELECT * FROM timescaledb_information.hypertables;
SELECT * FROM pg_stat_user_indexes;

# Check time range of data
SELECT MIN(time) as earliest, MAX(time) as latest FROM climate_metrics;
```

---

## PHASE 3: CONNECTION POOLING SETUP
====================================

### 3.1 Install and Configure PgBouncer

#### Linux:
```bash
# Already installed via apt-get above

# Configure PgBouncer
sudo cp pgbouncer.ini /etc/pgbouncer/pgbouncer.ini
sudo chmod 600 /etc/pgbouncer/pgbouncer.ini
sudo chown postgres:postgres /etc/pgbouncer/pgbouncer.ini

# Create pgbouncer system user
sudo useradd --system pgbouncer

# Update userlist.txt with MD5 hashes
# Generate MD5: python3 -c "import hashlib; print('md5' + hashlib.md5(b'md5PASSWORD_USERNAMEusername').hexdigest())"
sudo cp pgbouncer_userlist.txt /etc/pgbouncer/userlist.txt
sudo chmod 600 /etc/pgbouncer/userlist.txt
sudo chown pgbouncer:pgbouncer /etc/pgbouncer/userlist.txt

# Create log directory
sudo mkdir -p /var/log/pgbouncer
sudo chown pgbouncer:pgbouncer /var/log/pgbouncer

# Start PgBouncer service
sudo systemctl start pgbouncer
sudo systemctl enable pgbouncer

# Verify PgBouncer is running
sudo systemctl status pgbouncer
```

#### macOS:
```bash
# Start via Homebrew
brew services start pgbouncer

# Or manually
pgbouncer /usr/local/etc/pgbouncer.ini
```

### 3.2 Configure Django to Use PgBouncer

Edit `settings_production.py`:
```python
DATABASES = {
    'default': {
        'ENGINE': 'django.contrib.gis.db.backends.postgis',
        'NAME': 'agri_db',
        'USER': 'agri_app_user',
        'PASSWORD': 'password',
        'HOST': 'localhost',  # PgBouncer host
        'PORT': '6432',       # PgBouncer port (not 5432!)
        'CONN_MAX_AGE': 0,    # Disable Django connection pooling
    }
}
```

### 3.3 Test PgBouncer Connection

```bash
# Connect through PgBouncer
psql -h localhost -p 6432 -U agri_app_user -d agri_db

# In psql, check pool status
SHOW POOLS;  -- Should show active connections

# Or via admin database
psql -h localhost -p 6432 -U pgbouncer -d pgbouncer
SHOW STATS;
SHOW CLIENTS;
SHOW SERVERS;
```

---

## PHASE 4: BACKUP & RECOVERY SETUP
===================================

### 4.1 Install and Configure pgBackRest

#### Linux:
```bash
# Already installed via apt-get above

# Create backup directory
sudo mkdir -p /var/lib/pgbackrest
sudo chmod 700 /var/lib/pgbackrest
sudo chown postgres:postgres /var/lib/pgbackrest

# Configure pgBackRest
sudo cp pgbackrest.conf /etc/pgbackrest/pgbackrest.conf
sudo chmod 600 /etc/pgbackrest/pgbackrest.conf
sudo chown postgres:postgres /etc/pgbackrest/pgbackrest.conf

# Initialize stanza
sudo -u postgres pgbackrest stanza-create --stanza=agri_db

# Verify stanza
sudo -u postgres pgbackrest check --stanza=agri_db
```

### 4.2 Create Backup Schedule (Crontab)

```bash
# Edit crontab
sudo crontab -e -u postgres

# Add backup jobs:
# Full backup: Sunday 2:00 AM
0 2 * * 0 /usr/bin/pgbackrest backup --type=full --stanza=agri_db

# Differential: Monday-Saturday 2:00 AM
0 2 * * 1-6 /usr/bin/pgbackrest backup --type=diff --stanza=agri_db

# WAL archiving (triggered automatically, but add for clarity)
*/5 * * * * /usr/bin/pgbackrest archive-push >> /var/log/pgbackrest/cron.log 2>&1
```

### 4.3 Test Backup & Recovery

```bash
# Take first backup
sudo -u postgres pgbackrest backup --type=full --stanza=agri_db

# Check backup status
sudo -u postgres pgbackrest info --stanza=agri_db

# Verify backup is valid
sudo -u postgres pgbackrest verify --stanza=agri_db

# Expected output:
#   20240526-023000F full backup: 2.0GB, 3 WAL files, 256MB compressed
```

---

## PHASE 5: DJANGO CONFIGURATION
================================

### 5.1 Update Django Settings

```bash
# Copy settings to production environment
cp settings_production.py agri_dashboard/

# Update DJANGO_SETTINGS_MODULE environment variable
export DJANGO_SETTINGS_MODULE=agri_dashboard.settings_production
```

### 5.2 Create .env File

```bash
# Copy environment template
cp .env.production .env

# Edit with actual values
nano .env

# Restrict permissions
chmod 600 .env

# Add to .gitignore
echo ".env*" >> .gitignore
echo "*.sqlite3" >> .gitignore
```

### 5.3 Run Django Migrations

```bash
# Apply Django ORM migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Collect static files
python manage.py collectstatic --noinput

# Verify database connectivity
python manage.py shell
>>> from django.db import connection
>>> connection.ensure_connection()
>>> print("✓ Connected to", connection.settings_dict['HOST'])
>>> from dashboard.models import Region
>>> Region.objects.count()
```

### 5.4 Test Application

```bash
# Run development server (for testing only)
python manage.py runserver

# Or with Gunicorn (for production)
gunicorn agri_dashboard.wsgi:application --bind 0.0.0.0:8000 --workers 4
```

---

## PHASE 6: PERFORMANCE OPTIMIZATION
===================================

### 6.1 Create Indexes

```bash
# Already created in schema file, but verify:
psql -U agri_app_user -d agri_db

SELECT * FROM pg_stat_user_indexes WHERE idx_scan = 0;  -- Unused indexes
```

### 6.2 Analyze Database Statistics

```bash
# Update query planner statistics
psql -U postgres -d agri_db -c "ANALYZE;"

# Check table sizes
psql -U agri_app_user -d agri_db << 'EOF'
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size
FROM pg_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
EOF
```

### 6.3 Monitor Slow Queries

```bash
# Enable slow query logging in postgresql.conf
log_min_duration_statement = 1000  # 1 second

# Analyze slow queries
psql -U postgres -d agri_db -c "SELECT query, calls, mean_exec_time FROM pg_stat_statements WHERE mean_exec_time > 1000 ORDER BY mean_exec_time DESC LIMIT 10;"
```

### 6.4 Setup Query Monitoring

```bash
# Install pgAdmin or use built-in monitoring
# Query: SELECT * FROM pg_stat_statements;
# Tools: pgAdmin (GUI), psql (\d+), pg_stat_kcache (I/O stats)
```

---

## PHASE 7: VERIFICATION & TESTING
==================================

### 7.1 Migration Verification Checklist

```bash
# ✓ All tables exist in PostgreSQL
psql -U agri_app_user -d agri_db -c "\dt+"

# ✓ All data migrated successfully
psql -U agri_app_user -d agri_db << 'EOF'
SELECT 'regions' as table_name, COUNT(*) as count FROM regions
UNION ALL
SELECT 'climate_metrics', COUNT(*) FROM climate_metrics
UNION ALL
SELECT 'soil_metrics', COUNT(*) FROM soil_metrics
UNION ALL
SELECT 'drought_indices', COUNT(*) FROM drought_indices;
EOF

# ✓ TimescaleDB hypertables active
psql -U agri_app_user -d agri_db -c "SELECT hypertable_name, num_chunks FROM timescaledb_information.hypertables;"

# ✓ Spatial indexes work
psql -U agri_app_user -d agri_db << 'EOF'
SELECT COUNT(*) FROM regions WHERE ST_Contains(geometry, ST_GeomFromText('POINT(9.15 37.26)', 4326));
EOF

# ✓ PgBouncer active connections
psql -h localhost -p 6432 -U pgbouncer -d pgbouncer -c "SHOW POOLS;"

# ✓ Backup created
sudo -u postgres pgbackrest info --stanza=agri_db
```

### 7.2 Performance Testing

```bash
# Load test with pgbench
pgbench -U agri_app_user -d agri_db -c 50 -j 4 -T 300

# Monitor during test
watch -n 1 'psql -U postgres -d agri_db -c "SELECT datname, usename, state, query FROM pg_stat_activity WHERE datname = '\''agri_db'\'' ORDER BY query_start DESC LIMIT 10;"'
```

### 7.3 Disaster Recovery Drill

```bash
# On a test server, practice recovery:

# 1. Stop PostgreSQL
sudo systemctl stop postgresql

# 2. Clear data directory
sudo rm -rf /var/lib/postgresql/14/main/*

# 3. Restore from backup
sudo -u postgres pgbackrest restore --stanza=agri_db --delta

# 4. Start PostgreSQL
sudo systemctl start postgresql

# 5. Verify restored data
psql -U agri_app_user -d agri_db -c "SELECT COUNT(*) FROM climate_metrics;"
```

---

## PHASE 8: CUTOVER & GO-LIVE
=============================

### 8.1 Pre-Cutover Checklist

- [ ] All data migrated and verified
- [ ] Performance testing completed and acceptable
- [ ] Backup/recovery tested successfully
- [ ] PgBouncer connection pooling active
- [ ] Monitoring and logging configured
- [ ] Team trained on new infrastructure
- [ ] Rollback plan documented
- [ ] Communication plan for users

### 8.2 Cutover Steps

```bash
# 1. Final data sync (minimal downtime)
# Backup SQLite
cp db.sqlite3 db.sqlite3.final

# 2. Verify PostgreSQL is ready
psql -U agri_app_user -d agri_db -c "SELECT COUNT(*) FROM regions;"

# 3. Switch Django to use PostgreSQL
# Update DJANGO_SETTINGS_MODULE or production server configuration

# 4. Warm up PgBouncer connection pool
python manage.py shell << 'EOF'
from django.db import connection
# Make a few queries to populate connection pool
from dashboard.models import Region
Region.objects.count()
EOF

# 5. Monitor application
tail -f /var/log/agri_dashboard/django.log

# 6. Alert users of cutover completion
echo "✓ Migration complete. Application now running on PostgreSQL + TimescaleDB"
```

### 8.3 Post-Cutover Monitoring

```bash
# Monitor for first 24 hours
# Check error logs
tail -f /var/log/agri_dashboard/django.log /var/log/pgbouncer/pgbouncer.log

# Monitor database performance
watch -n 5 'psql -U postgres -d agri_db -c "SELECT * FROM pg_stat_activity WHERE datname = '\''agri_db'\'' ;" | wc -l'

# Check backup auto-archiving
sudo -u postgres pgbackrest info --stanza=agri_db | grep "wal archive"

# Verify materialized views refresh
psql -U agri_app_user -d agri_db -c "REFRESH MATERIALIZED VIEW CONCURRENTLY mv_daily_climate_summary;"
```

---

## TROUBLESHOOTING
==================

### Connection Issues

```bash
# Test PostgreSQL direct connection
psql -U postgres -h localhost -c "SELECT version();"

# Test PgBouncer connection
psql -h localhost -p 6432 -U agri_app_user -d agri_db -c "SELECT version();"

# Check PgBouncer logs
sudo tail -f /var/log/pgbouncer/pgbouncer.log

# Check PostgreSQL connection limit
psql -U postgres -c "SELECT setting FROM pg_settings WHERE name = 'max_connections';"
```

### TimescaleDB Issues

```bash
# Verify hypertable creation
SELECT * FROM timescaledb_information.hypertables;

# Check chunk distribution
SELECT * FROM _timescaledb_internal._hypertable_chunk_info;

# Repair hypertable if needed
SELECT decompress_chunks(get_chunks('climate_metrics', INTERVAL '1 week ago'));
```

### Performance Problems

```bash
# Identify slow queries
SELECT query, calls, mean_exec_time FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 10;

# Analyze query plan
EXPLAIN ANALYZE SELECT * FROM climate_metrics WHERE region_id = 1 AND time > NOW() - INTERVAL '30 days';

# Update statistics
ANALYZE climate_metrics;
VACUUM ANALYZE;
```

---

## ROLLBACK PROCEDURE
=====================

If critical issues occur, rollback to SQLite:

```bash
# 1. Stop application
systemctl stop agri_dashboard

# 2. Switch back to SQLite in Django settings
# Edit settings.py or revert DJANGO_SETTINGS_MODULE

# 3. Restore SQLite backup
cp db.sqlite3.backup.20240526_140000 db.sqlite3

# 4. Restart application
systemctl start agri_dashboard

# 5. Notify team
echo "✓ Rolled back to SQLite"
```

---

## MAINTENANCE SCHEDULE
======================

**Weekly:**
- [ ] Check backup status: `pgbackrest info --stanza=agri_db`
- [ ] Monitor disk usage: `df -h /var/lib/pgbackrest`
- [ ] Check PostgreSQL logs for errors

**Monthly:**
- [ ] Update statistics: `VACUUM ANALYZE;`
- [ ] Review slow query logs
- [ ] Test backup restoration on test server
- [ ] Update PgBouncer pool settings if needed

**Quarterly:**
- [ ] Full disaster recovery drill
- [ ] Review PostgreSQL performance tuning settings
- [ ] Rotate database passwords
- [ ] Update documentation

---

## SUPPORT & REFERENCES
=======================

- PostgreSQL Documentation: https://www.postgresql.org/docs/14/
- TimescaleDB Documentation: https://docs.timescale.com/
- PostGIS Documentation: https://postgis.net/documentation/
- PgBouncer Documentation: https://pgbouncer.github.io/
- pgBackRest Documentation: https://pgbackrest.org/
- Django & Databases: https://docs.djangoproject.com/en/4.2/ref/databases/

---

**Migration Completed By:** [Your Name]  
**Date:** [Migration Date]  
**Approved By:** [Manager/DBA]  
**Notes:** [Any special considerations or deviations]

======================================================================
