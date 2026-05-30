# ============================================================================
# TimescaleDB & PostgreSQL Operations Guide
# ABCDryBASiN Agricultural Metrics Dashboard
# ============================================================================

## TABLE OF CONTENTS
1. Daily Operations
2. Query Examples & Analytics
3. Maintenance Tasks
4. Monitoring & Alerting
5. Troubleshooting

---

## 1. DAILY OPERATIONS
=====================

### 1.1 Database Health Check

```bash
#!/bin/bash
# Run daily health check

echo "=== PostgreSQL & TimescaleDB Health Check ==="

# Database size
echo -e "\n[Database Size]"
psql -U postgres -d agri_db << 'EOF'
SELECT 
    datname,
    pg_size_pretty(pg_database_size(datname)) as size
FROM pg_database
WHERE datname = 'agri_db';
EOF

# Active connections
echo -e "\n[Active Connections]"
psql -U postgres -d agri_db << 'EOF'
SELECT 
    datname,
    count(*) as connections,
    max(EXTRACT(EPOCH FROM (now() - query_start))) as longest_query_seconds
FROM pg_stat_activity
WHERE datname = 'agri_db'
GROUP BY datname;
EOF

# Hypertable chunk info
echo -e "\n[Hypertable Chunks]"
psql -U postgres -d agri_db << 'EOF'
SELECT 
    h.hypertable_name,
    count(c.chunk_name) as chunk_count,
    pg_size_pretty(sum(pg_total_relation_size(c.chunk_name::regclass))) as total_size
FROM timescaledb_information.hypertables h
LEFT JOIN timescaledb_information.chunks c ON h.hypertable_id = c.hypertable_id
GROUP BY h.hypertable_name
ORDER BY total_size DESC;
EOF

# Check for missing indexes
echo -e "\n[Unused Indexes (may be candidates for removal)]"
psql -U postgres -d agri_db << 'EOF'
SELECT 
    schemaname,
    tablename,
    indexname,
    idx_scan
FROM pg_stat_user_indexes
WHERE idx_scan = 0
AND indexrelname NOT LIKE 'pk_%'
ORDER BY pg_relation_size(indexrelid) DESC;
EOF

# PgBouncer stats
echo -e "\n[PgBouncer Connection Pool]"
psql -h localhost -p 6432 -U pgbouncer -d pgbouncer << 'EOF'
SHOW POOLS;
EOF

echo -e "\n=== Health Check Complete ==="
```

### 1.2 Manual Backup

```bash
# Full backup
sudo -u postgres pgbackrest backup --type=full --stanza=agri_db --verbose

# Differential backup (faster, incremental from last full)
sudo -u postgres pgbackrest backup --type=diff --stanza=agri_db

# Check backup status
sudo -u postgres pgbackrest info --stanza=agri_db
```

### 1.3 Refresh Materialized Views

```bash
# Refresh all materialized views (safe, doesn't lock)
psql -U agri_app_user -d agri_db << 'EOF'
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_daily_climate_summary;
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_weekly_drought_summary;
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_monthly_crop_performance;
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_monthly_vegetation_health;
EOF

# Or via cron for automation:
# 0 1 * * * psql -U postgres -d agri_db -c "REFRESH MATERIALIZED VIEW CONCURRENTLY mv_daily_climate_summary;"
```

---

## 2. QUERY EXAMPLES & ANALYTICS
================================

### 2.1 Historical Drought Analysis

```sql
-- Find regions with severe drought in the last 90 days
SELECT 
    r.name as region,
    di.time as observation_date,
    di.spi_3month,
    di.spei_3month,
    di.drought_severity_class,
    COUNT(*) OVER (PARTITION BY r.region_id ORDER BY di.time) as consecutive_severe_days
FROM drought_indices di
JOIN regions r ON di.region_id = r.region_id
WHERE di.time > NOW() - INTERVAL '90 days'
    AND di.drought_severity_class IN ('Severe Drought', 'Extreme Drought')
ORDER BY di.time DESC;
```

### 2.2 Water Balance by Region

```sql
-- Current water balance status for agricultural planning
SELECT 
    r.name as region,
    time_bucket('1 week', hm.time) as week,
    SUM(hm.precipitation_mm) as weekly_rainfall_mm,
    AVG(hm.evapotranspiration_mm) as avg_et_mm,
    AVG(hm.water_balance_percent) as avg_balance_percent,
    SUM(hm.irrigation_supply_available_m3) as available_water_m3,
    CASE 
        WHEN AVG(hm.water_balance_percent) < -20 THEN 'Critical Deficit'
        WHEN AVG(hm.water_balance_percent) < 0 THEN 'Deficit'
        WHEN AVG(hm.water_balance_percent) < 20 THEN 'Adequate'
        ELSE 'Surplus'
    END as water_status
FROM hydrology_metrics hm
JOIN regions r ON hm.region_id = r.region_id
WHERE hm.time > NOW() - INTERVAL '6 months'
GROUP BY r.name, time_bucket('1 week', hm.time)
ORDER BY r.name, week DESC;
```

### 2.3 Crop Performance Comparison

```sql
-- Compare crop yields and water efficiency across regions
SELECT 
    ct.name as crop,
    r.name as region,
    COUNT(*) as observations,
    AVG(am.crop_water_requirement_mmday) as avg_water_req_mm,
    AVG(am.crop_coefficient_kc) as avg_crop_coefficient,
    AVG(am.yield_reduction_factor) as avg_yield_reduction,
    AVG(am.water_applied_mm) as avg_water_applied_mm,
    ROUND(
        (AVG(am.water_applied_mm) / NULLIF(AVG(am.crop_water_requirement_mmday) * 120, 0)) * 100,
        2
    ) as irrigation_sufficiency_percent
FROM agricultural_metrics am
JOIN crop_types ct ON am.crop_id = ct.crop_id
JOIN regions r ON am.region_id = r.region_id
WHERE am.time > NOW() - INTERVAL '1 year'
GROUP BY ct.name, r.name
ORDER BY ct.name, irrigation_sufficiency_percent DESC;
```

### 2.4 Vegetation Health Trend (NDVI)

```sql
-- Track vegetation health over time
SELECT 
    r.name as region,
    time_bucket('1 month', rs.time) as month,
    AVG(rs.ndvi) as avg_ndvi,
    MIN(rs.ndvi) as min_ndvi,
    MAX(rs.ndvi) as max_ndvi,
    STDDEV(rs.ndvi) as stddev_ndvi,
    COUNT(*) as observations,
    CASE 
        WHEN AVG(rs.ndvi) < 0 THEN 'No Vegetation'
        WHEN AVG(rs.ndvi) < 0.2 THEN 'Sparse'
        WHEN AVG(rs.ndvi) < 0.4 THEN 'Moderate'
        WHEN AVG(rs.ndvi) < 0.6 THEN 'Dense'
        ELSE 'Very Dense'
    END as vegetation_class
FROM remote_sensing_metrics rs
JOIN regions r ON rs.region_id = r.region_id
WHERE rs.time > NOW() - INTERVAL '2 years'
    AND rs.satellite_source IN ('MODIS', 'Sentinel-1')
GROUP BY r.name, time_bucket('1 month', rs.time)
ORDER BY r.name, month DESC;
```

### 2.5 Risk Assessment by Irrigation Method

```sql
-- Identify which irrigation methods reduce risk most effectively
SELECT 
    im.name as irrigation_method,
    AVG(ra.risk_score) as avg_risk_score,
    COUNT(*) as assessments,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ra.risk_score) as median_risk,
    COUNT(CASE WHEN ra.risk_level = 'Critical' THEN 1 END) as critical_count,
    ROUND(
        100.0 * COUNT(CASE WHEN ra.risk_level = 'Low' THEN 1 END) / COUNT(*),
        2
    ) as low_risk_percent
FROM risk_assessments ra
LEFT JOIN irrigation_methods im ON ra.irrigation_id = im.irrigation_id
WHERE ra.created_at > NOW() - INTERVAL '1 year'
GROUP BY im.name
ORDER BY avg_risk_score ASC;
```

### 2.6 Spatial Query - Zones Within Radius

```sql
-- Find all metrics for zones within 50km of a point
SELECT 
    r.name as region,
    r.geometry <-> ST_GeomFromText('POINT(9.15 37.26)', 4326)::geography as distance_km,
    COUNT(DISTINCT cm.metric_id) as climate_observations,
    COUNT(DISTINCT sm.metric_id) as soil_observations,
    MAX(cm.time) as latest_climate_reading
FROM regions r
LEFT JOIN climate_metrics cm ON r.region_id = cm.region_id
LEFT JOIN soil_metrics sm ON r.region_id = sm.region_id
WHERE ST_DWithin(
    r.geometry,
    ST_GeomFromText('POINT(9.15 37.26)', 4326),
    50000  -- 50km in meters
)
GROUP BY r.region_id
ORDER BY distance_km;
```

### 2.7 Data Quality Checks

```sql
-- Identify missing or anomalous data
SELECT 
    'climate_metrics' as table_name,
    time_bucket('1 day', time) as day,
    COUNT(*) as record_count,
    COUNT(CASE WHEN rainfall_mm IS NULL THEN 1 END) as null_rainfall,
    COUNT(CASE WHEN temperature_mean_c IS NULL THEN 1 END) as null_temp,
    CASE 
        WHEN COUNT(*) < 10 THEN 'Low volume'
        WHEN COUNT(CASE WHEN rainfall_mm IS NULL THEN 1 END) > COUNT(*) * 0.2 THEN 'High nulls'
        ELSE 'OK'
    END as data_quality
FROM climate_metrics
WHERE time > NOW() - INTERVAL '30 days'
GROUP BY time_bucket('1 day', time)
HAVING COUNT(*) < 20
ORDER BY day DESC;
```

---

## 3. MAINTENANCE TASKS
======================

### 3.1 Optimize Table Bloat

```bash
# TimescaleDB automatically manages compression, but check for bloat:
psql -U postgres -d agri_db << 'EOF'
-- Estimate bloat in hypertables
SELECT 
    schemaname,
    tablename,
    round(100 * (CASE 
        WHEN otta > 0 THEN sml.relpages - otta 
        ELSE 0 
    END) / sml.relpages) as table_waste_ratio,
    pg_size_pretty((CASE 
        WHEN otta > 0 THEN sml.relpages - otta 
        ELSE 0 
    END) * 8192) as approx_wasted_space
FROM pg_class sml
JOIN pg_namespace ON pg_namespace.oid = sml.relnamespace
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
    AND schemaname LIKE '%timescale%'
ORDER BY table_waste_ratio DESC;
EOF

# If significant bloat, run VACUUM
psql -U postgres -d agri_db -c "VACUUM ANALYZE climate_metrics;"
```

### 3.2 Manage Data Retention

```sql
-- View current retention policies
SELECT * FROM timescaledb_information.data_nodes;

-- Manually delete old data (if needed before retention policy runs)
SELECT delete_expired_chunk_data('climate_metrics', INTERVAL '3 years');

-- Or delete specific time range
DELETE FROM climate_metrics 
WHERE time < NOW() - INTERVAL '3 years';

-- Check what will be deleted before running
SELECT COUNT(*) FROM climate_metrics 
WHERE time < NOW() - INTERVAL '3 years';
```

### 3.3 Manage Compression

```sql
-- View compression status
SELECT * FROM timescaledb_information.compressed_hypertable_stats;

-- Manually compress old chunks
SELECT compress_chunk(chunk_name)
FROM timescaledb_information.chunks
WHERE hypertable_id = (
    SELECT id FROM timescaledb_information.hypertables 
    WHERE hypertable_name = 'climate_metrics'
)
AND range_start < NOW() - INTERVAL '30 days';

-- Decompress for editing (if needed)
SELECT decompress_chunk(chunk_name)
FROM timescaledb_information.chunks
WHERE hypertable_name = 'climate_metrics'
    AND range_start > NOW() - INTERVAL '3 days';
```

### 3.4 Reindex for Performance

```bash
# Reindex specific table
psql -U postgres -d agri_db << 'EOF'
REINDEX TABLE climate_metrics;
EOF

# Reindex specific index
psql -U postgres -d agri_db << 'EOF'
REINDEX INDEX idx_climate_metrics_region_year;
EOF

# Monitor reindex progress
# SELECT * FROM pg_stat_progress_create_index;
```

---

## 4. MONITORING & ALERTING
=============================

### 4.1 Setup Query Monitoring

```sql
-- Enable pg_stat_statements
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- Find slowest queries
SELECT 
    query,
    calls,
    total_exec_time,
    mean_exec_time,
    stddev_exec_time,
    max_exec_time
FROM pg_stat_statements
WHERE datname = 'agri_db'
ORDER BY mean_exec_time DESC
LIMIT 20;

-- Reset stats
SELECT pg_stat_statements_reset();
```

### 4.2 Connection Monitoring

```sql
-- Active connections
SELECT 
    usename,
    application_name,
    client_addr,
    state,
    query_start,
    state_change,
    query
FROM pg_stat_activity
WHERE datname = 'agri_db'
ORDER BY query_start DESC;

-- Kill long-running query
-- SELECT pg_terminate_backend(pid) WHERE pid = <pid>;
```

### 4.3 Setup Email Alerts

```bash
# Create alert script
cat > /usr/local/bin/check_db_health.sh << 'EOF'
#!/bin/bash

# Check if PostgreSQL is running
pg_isready -h localhost -p 5432 -U postgres > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "ALERT: PostgreSQL is down!" | mail -s "DB Alert" admin@example.com
    exit 1
fi

# Check backup age
LAST_BACKUP=$(sudo -u postgres pgbackrest info --stanza=agri_db --output=json | jq '.backup[0].timestamp' 2>/dev/null)
CURRENT_TIME=$(date +%s)
BACKUP_AGE=$((CURRENT_TIME - LAST_BACKUP))

if [ $BACKUP_AGE -gt 86400 ]; then  # 24 hours
    echo "ALERT: Last backup is $(($BACKUP_AGE / 3600)) hours old" | mail -s "Backup Alert" admin@example.com
fi

# Check disk usage
DISK_USAGE=$(df /var/lib/postgresql | tail -1 | awk '{print $5}' | sed 's/%//')
if [ $DISK_USAGE -gt 80 ]; then
    echo "ALERT: Database disk usage is at ${DISK_USAGE}%" | mail -s "Disk Alert" admin@example.com
fi
EOF

chmod +x /usr/local/bin/check_db_health.sh

# Add to crontab
# */5 * * * * /usr/local/bin/check_db_health.sh
```

### 4.4 Prometheus/Grafana Integration

```bash
# Install postgres_exporter
wget https://github.com/prometheus-community/postgres_exporter/releases/download/v0.12.0/postgres_exporter-0.12.0.linux-amd64.tar.gz
tar xzf postgres_exporter-0.12.0.linux-amd64.tar.gz
sudo mv postgres_exporter /usr/local/bin/

# Configure systemd service
sudo tee /etc/systemd/system/postgres-exporter.service > /dev/null << 'EOF'
[Unit]
Description=PostgreSQL Exporter
After=network.target

[Service]
Type=simple
User=postgres
Environment="DATA_SOURCE_NAME=postgresql://postgres:password@localhost:5432/postgres?sslmode=disable"
ExecStart=/usr/local/bin/postgres_exporter --web.listen-address=:9187

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl start postgres-exporter
sudo systemctl enable postgres-exporter

# Add to Prometheus scrape_configs:
# - job_name: 'postgresql'
#   static_configs:
#     - targets: ['localhost:9187']
```

---

## 5. TROUBLESHOOTING
====================

### 5.1 Connection Issues

```bash
# Test direct PostgreSQL connection
psql -U postgres -h localhost -d agri_db -c "SELECT version();"

# Test through PgBouncer
psql -h localhost -p 6432 -U agri_app_user -d agri_db -c "SELECT version();"

# Check PostgreSQL logs
sudo tail -f /var/log/postgresql/postgresql-14-main.log

# Check PgBouncer logs
sudo tail -f /var/log/pgbouncer/pgbouncer.log

# Check firewall
sudo ufw status
sudo iptables -L | grep 5432  # PostgreSQL
sudo iptables -L | grep 6432  # PgBouncer
```

### 5.2 Slow Query Diagnosis

```sql
-- Get query plan for slow query
EXPLAIN ANALYZE SELECT * FROM climate_metrics 
WHERE region_id = 1 AND time > NOW() - INTERVAL '30 days';

-- Check if index is being used
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM climate_metrics 
WHERE region_id = 1 ORDER BY time DESC LIMIT 100;

-- Compare sequential vs index scan
SET enable_seqscan = off;
EXPLAIN SELECT * FROM climate_metrics WHERE region_id = 1;
SET enable_seqscan = on;
```

### 5.3 Out of Memory Issues

```bash
# Check memory usage
free -h

# Check PostgreSQL shared_buffers
psql -U postgres -c "SHOW shared_buffers;"

# Monitor memory in real-time
watch -n 1 'ps aux | grep postgre[s]'

# If out of memory, increase swap
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

### 5.4 TimescaleDB Issues

```bash
# Check hypertable status
psql -U postgres -d agri_db << 'EOF'
SELECT * FROM timescaledb_information.hypertables;
SELECT * FROM _timescaledb_internal._hypertable_chunk_info;
EOF

# Rebuild hypertable if corrupted
-- psql -U postgres -d agri_db -c "SELECT rebuild_chunk('<chunk_name>');"

# Check compression status
psql -U postgres -d agri_db << 'EOF'
SELECT 
    h.hypertable_name,
    c.chunk_name,
    c.is_compressed,
    pg_size_pretty(pg_total_relation_size(c.chunk_name::regclass)) as size
FROM timescaledb_information.hypertables h
JOIN timescaledb_information.chunks c ON h.hypertable_id = c.hypertable_id
ORDER BY h.hypertable_name;
EOF
```

### 5.5 Recovery from Backup

```bash
# If PostgreSQL corrupted, restore from backup

# 1. Stop PostgreSQL
sudo systemctl stop postgresql

# 2. Clear corrupted data
sudo rm -rf /var/lib/postgresql/14/main/*

# 3. Restore from backup
sudo -u postgres pgbackrest restore --stanza=agri_db --delta

# 4. Start PostgreSQL
sudo systemctl start postgresql

# 5. Verify restoration
psql -U postgres -d agri_db -c "SELECT COUNT(*) FROM climate_metrics;"
```

---

**Last Updated:** [Date]  
**Maintained By:** [DBA Name]  
**Support Contact:** [Email/Slack]
