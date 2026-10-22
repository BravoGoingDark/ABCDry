# ============================================================================
# ABCDryBASiN Database Quick Reference Card
# For Developers, DBAs, and Operations Teams
# ============================================================================

## CRITICAL INFORMATION

**Database:** PostgreSQL 14+ with TimescaleDB 2.x + PostGIS 3.x  
**Connection Pooling:** PgBouncer (port 6432)  
**Backup Tool:** pgBackRest  
**Backup Location:** /var/lib/pgbackrest  
**Backup Encryption:** AES-256 CBC  
**Data Retention:** 2 years (with compression policies)  

---

## QUICK COMMANDS

### Connect to Database

```bash
# PostgreSQL (direct)
psql -U agri_app_user -d agri_db -h localhost -p 5432

# Through PgBouncer (application layer)
psql -U agri_app_user -d agri_db -h localhost -p 6432

# As superuser (for admin tasks)
psql -U postgres -d agri_db
```

### Health Check (30 seconds)

```bash
# Database status
psql -U postgres -c "SELECT version();"

# Check active connections
psql -U postgres -d agri_db -c "SELECT COUNT(*) as active_connections FROM pg_stat_activity WHERE datname = 'agri_db';"

# Check backup status
sudo -u postgres pgbackrest info --stanza=agri_db

# Check PgBouncer pools
psql -h localhost -p 6432 -U pgbouncer -d pgbouncer -c "SHOW POOLS;"
```

### Backup Operations

```bash
# Trigger full backup
sudo -u postgres pgbackrest backup --type=full --stanza=agri_db

# Trigger incremental backup
sudo -u postgres pgbackrest backup --type=diff --stanza=agri_db

# Check backup status
sudo -u postgres pgbackrest info --stanza=agri_db

# Verify backup integrity
sudo -u postgres pgbackrest verify --stanza=agri_db
```

### Data Operations

```bash
# Row counts by table
psql -U agri_app_user -d agri_db << 'EOF'
SELECT tablename, (SELECT count(*) FROM tablename) as count 
FROM pg_tables 
WHERE schemaname = 'public' 
ORDER BY count DESC;
EOF

# Check disk usage
psql -U agri_app_user -d agri_db << 'EOF'
SELECT 
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
EOF

# Refresh materialized views
psql -U agri_app_user -d agri_db -c "REFRESH MATERIALIZED VIEW CONCURRENTLY mv_daily_climate_summary;"

# Analyze statistics (optimize queries)
psql -U postgres -d agri_db -c "ANALYZE;"
```

### Monitoring

```bash
# Top 10 slowest queries
psql -U postgres -d agri_db << 'EOF'
SELECT 
    substring(query, 1, 50) as query_preview,
    mean_exec_time,
    calls
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 10;
EOF

# Database size summary
psql -U postgres -c "SELECT datname, pg_size_pretty(pg_database_size(datname)) as size FROM pg_database WHERE datname = 'agri_db';"

# Check database connection limit status
psql -U postgres -d agri_db << 'EOF'
SELECT 
    (SELECT setting::int FROM pg_settings WHERE name = 'max_connections') as max_connections,
    COUNT(*) as current_connections
FROM pg_stat_activity;
EOF
```

### Troubleshooting

```bash
# Kill idle connections (if needed)
psql -U postgres -d agri_db << 'EOF'
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = 'agri_db'
    AND pid <> pg_backend_pid()
    AND state = 'idle'
    AND state_change < NOW() - INTERVAL '30 minutes';
EOF

# Kill long-running query
# First identify the PID:
psql -U postgres -d agri_db -c "SELECT pid, query_start, query FROM pg_stat_activity WHERE datname = 'agri_db' ORDER BY query_start LIMIT 5;"
# Then kill:
# SELECT pg_terminate_backend(<PID>);

# Check for locks
psql -U postgres -d agri_db << 'EOF'
SELECT 
    l.pid,
    l.usename,
    l.application_name,
    l.state,
    l.query,
    now() - l.query_start as duration
FROM pg_stat_activity l
WHERE l.wait_event_type = 'Lock'
ORDER BY l.query_start;
EOF
```

---

## CRITICAL THRESHOLDS & ALERTS

| Metric | Warning | Critical | Action |
|--------|---------|----------|--------|
| **Disk Usage** | >70% | >90% | Add storage, compress old data |
| **Connections** | >150/200 | >190/200 | Optimize pool, kill idle |
| **Query Time** | >1s | >10s | Review query plan, add index |
| **Backup Age** | >7 days | >30 days | Verify backup schedule |
| **Replication Lag** | >10s | >60s | Check network, reduce writes |
| **Memory Usage** | >80% | >95% | Increase swap, reduce shared_buffers |

---

## EMERGENCY PROCEDURES

### Database Offline / Connection Refused

```bash
# 1. Check if PostgreSQL is running
systemctl status postgresql

# 2. Restart if not running
sudo systemctl restart postgresql

# 3. Check logs
sudo tail -100 /var/log/postgresql/postgresql-14-main.log

# 4. If corrupted, restore from backup
sudo systemctl stop postgresql
sudo rm -rf /var/lib/postgresql/14/main/*
sudo -u postgres pgbackrest restore --stanza=agri_db --delta
sudo systemctl start postgresql
```

### Out of Disk Space

```bash
# Check disk usage
df -h /var/lib/postgresql

# Emergency: Compress old data
psql -U postgres -d agri_db << 'EOF'
-- Compress all chunks older than 7 days
SELECT compress_chunk(chunk_name)
FROM timescaledb_information.chunks
WHERE range_start < NOW() - INTERVAL '7 days'
LIMIT 100;
EOF

# Emergency: Delete oldest data (if compression insufficient)
psql -U postgres -d agri_db << 'EOF'
-- DELETE old data (CAUTION - permanent!)
DELETE FROM climate_metrics WHERE time < NOW() - INTERVAL '3 years';
DELETE FROM soil_metrics WHERE time < NOW() - INTERVAL '3 years';
-- Then VACUUM to reclaim space
VACUUM ANALYZE;
EOF
```

### Backup Failed

```bash
# Check backup status
sudo -u postgres pgbackrest info --stanza=agri_db

# Check backup logs
sudo tail -f /var/log/pgbackrest/

# Retry backup
sudo -u postgres pgbackrest backup --type=full --stanza=agri_db --verbose

# If persistent, contact DBA
echo "CRITICAL: Backup failed" | mail -s "DB Backup Alert" admin@example.com
```

### Slow Application Response

```bash
# 1. Check active queries
psql -U postgres -d agri_db -c "SELECT query_start, query FROM pg_stat_activity WHERE datname = 'agri_db' ORDER BY query_start LIMIT 5;"

# 2. Check PgBouncer pool saturation
psql -h localhost -p 6432 -U pgbouncer -d pgbouncer -c "SHOW POOLS;"

# 3. Check system resources
vmstat 1 5  # CPU, memory, I/O
iostat -x 1 5  # Disk I/O

# 4. If query is slow:
EXPLAIN ANALYZE <slow_query>;

# 5. If pool is saturated, increase pool size in pgbouncer.ini and reload
sudo systemctl reload pgbouncer
```

---

## MAINTENANCE SCHEDULE

**Daily:**
- [ ] Check backup status: `pgbackrest info --stanza=agri_db`
- [ ] Monitor disk usage: `df -h /var/lib/postgresql`
- [ ] Review error logs: `tail /var/log/postgresql/postgresql-14-main.log`

**Weekly:**
- [ ] Run: `VACUUM ANALYZE;`
- [ ] Check slow queries: `SELECT * FROM pg_stat_statements;`
- [ ] Verify backup restoration on test system

**Monthly:**
- [ ] Test full recovery procedure
- [ ] Update statistics: `ANALYZE;`
- [ ] Review backup retention policies

**Quarterly:**
- [ ] Full disaster recovery drill
- [ ] Rotate database passwords
- [ ] Review and optimize slow queries

---

## ENVIRONMENT VARIABLES

```bash
# Database connection
export DB_HOST=localhost
export DB_PORT=5432
export DB_NAME=agri_db
export DB_USER=agri_app_user
export DB_PASSWORD=***

# PgBouncer
export PGBOUNCER_HOST=localhost
export PGBOUNCER_PORT=6432

# Django settings
export DJANGO_SETTINGS_MODULE=agri_dashboard.settings_production

# Backup
export PGBACKREST_REPO1_PATH=/var/lib/pgbackrest
export PGBACKREST_STANZA=agri_db
```

---

## KEY FILE LOCATIONS

| File | Location | Purpose |
|------|----------|---------|
| PostgreSQL config | `/etc/postgresql/14/main/postgresql.conf` | DB tuning |
| PostgreSQL logs | `/var/log/postgresql/postgresql-14-main.log` | Error tracking |
| PgBouncer config | `/etc/pgbouncer/pgbouncer.ini` | Connection pooling |
| PgBouncer logs | `/var/log/pgbouncer/pgbouncer.log` | Pool status |
| pgBackRest config | `/etc/pgbackrest/pgbackrest.conf` | Backup policy |
| Backups | `/var/lib/pgbackrest` | Backup storage |
| Django logs | `/var/log/agri_dashboard/django.log` | Application logs |
| Database schema | `database_schema_timescaledb.sql` | Schema definition |

---

## USEFUL QUERIES

```sql
-- Table sizes
SELECT tablename, pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) 
FROM pg_tables WHERE schemaname = 'public' ORDER BY 2 DESC;

-- Hypertable info
SELECT * FROM timescaledb_information.hypertables;

-- Current replication status
SELECT * FROM pg_stat_replication;

-- Index usage
SELECT schemaname, tablename, indexname, idx_scan FROM pg_stat_user_indexes ORDER BY idx_scan ASC;

-- Unused indexes
SELECT schemaname, tablename, indexname FROM pg_stat_user_indexes WHERE idx_scan = 0;

-- Row count summary
SELECT schemaname, tablename, n_live_tup FROM pg_stat_user_tables ORDER BY n_live_tup DESC;

-- Check for missing indexes
SELECT * FROM pg_stat_user_indexes WHERE idx_scan = 0 LIMIT 10;
```

---

## ESCALATION CONTACTS

| Issue | Contact | Escalate To |
|-------|---------|------------|
| Database down | DBA on-call | Infrastructure Lead |
| Slow queries | Application Team | Senior DBA |
| Backup failed | Backup Admin | CTO |
| Disk full | SysAdmin | Infrastructure |
| Connection pool exhausted | Dev Lead | Architecture Review |

---

## ADDITIONAL RESOURCES

- **PostgreSQL Docs:** https://www.postgresql.org/docs/14/
- **TimescaleDB Docs:** https://docs.timescale.com/
- **PostGIS Docs:** https://postgis.net/docs/
- **PgBouncer Wiki:** https://pgbouncer.github.io/
- **pgBackRest Docs:** https://pgbackrest.org/
- **Django Database Docs:** https://docs.djangoproject.com/en/4.2/ref/databases/

---

**Last Updated:** [Date]  
**Version:** 1.0  
**Approved By:** [DBA Lead]

