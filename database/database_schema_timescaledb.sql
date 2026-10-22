-- ============================================================================
-- ABCDryBASiN Agricultural Metrics Dashboard - TimescaleDB Schema
-- ============================================================================
-- Database: Agricultural monitoring system for North Africa
-- Engine: PostgreSQL 14+ with TimescaleDB 2.x and PostGIS 3.x
-- Purpose: Time-series climate, soil, drought, and agricultural metrics
-- ============================================================================

-- ============================================================================
-- 1. EXTENSIONS
-- ============================================================================
-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- Enable PostGIS for geospatial queries (location-based analytics)
CREATE EXTENSION IF NOT EXISTS postgis;

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Enable pl/python for advanced analytics (optional)
-- CREATE EXTENSION IF NOT EXISTS plpython3u;

-- ============================================================================
-- 2. DIMENSION TABLES (Reference Data - NOT hypertables)
-- ============================================================================

-- Regions/Zones for spatial monitoring
CREATE TABLE IF NOT EXISTS regions (
    region_id BIGSERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    country VARCHAR(100),
    latitude DECIMAL(10, 6),
    longitude DECIMAL(10, 6),
    geometry GEOMETRY(Point, 4326) GENERATED ALWAYS AS (
        ST_GeomFromText('POINT(' || longitude || ' ' || latitude || ')', 4326)
    ) STORED,  -- PostGIS geometry for spatial queries
    elevation_m INTEGER,
    area_km2 DECIMAL(10, 2),
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT valid_coordinates CHECK (latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180)
);

-- Observation years (for multi-year comparative analysis)
CREATE TABLE IF NOT EXISTS observation_years (
    year_id BIGSERIAL PRIMARY KEY,
    label VARCHAR(30) UNIQUE NOT NULL,
    start_date DATE,
    end_date DATE,
    season VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Crop types managed in the regions
CREATE TABLE IF NOT EXISTS crop_types (
    crop_id BIGSERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    scientific_name VARCHAR(100),
    crop_family VARCHAR(100),
    water_requirement_mm_season DECIMAL(7, 2),
    growing_period_days INTEGER,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Irrigation methods used
CREATE TABLE IF NOT EXISTS irrigation_methods (
    irrigation_id BIGSERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    efficiency_percent DECIMAL(5, 2),
    water_application_uniformity DECIMAL(5, 2),
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- 3. TIME-SERIES HYPERTABLES (Core Metrics)
-- ============================================================================

-- ===== 3.1 ENVIRONMENTAL SNAPSHOT (Mixed metrics for quick dashboard view)
CREATE TABLE IF NOT EXISTS environmental_snapshots (
    snapshot_id BIGSERIAL,
    region_id BIGINT NOT NULL,
    year_id BIGINT NOT NULL,
    time TIMESTAMP WITH TIME ZONE NOT NULL,
    
    -- Wind
    wind_speed_kmh DECIMAL(5, 1),
    wind_gust_kmh DECIMAL(5, 1),
    wind_direction VARCHAR(10),
    
    -- Rainfall
    rainfall_mm DECIMAL(6, 1),
    rainfall_delta_percent INTEGER,
    
    -- Soil
    ph_level DECIMAL(3, 1),
    npk_index VARCHAR(20),
    
    -- Temperature & Humidity
    temperature_c DECIMAL(4, 1),
    humidity_percent INTEGER,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    PRIMARY KEY (snapshot_id, time),
    FOREIGN KEY (region_id) REFERENCES regions(region_id),
    FOREIGN KEY (year_id) REFERENCES observation_years(year_id)
);

-- Convert to hypertable with time as time column (compressed after 7 days)
SELECT create_hypertable(
    'environmental_snapshots',
    'time',
    if_not_exists => TRUE,
    time_partitioning_func => 'date_trunc(''1 day'', time)'
);

-- ===== 3.2 SOIL METRICS HYPERTABLE (High-frequency soil data)
CREATE TABLE IF NOT EXISTS soil_metrics (
    metric_id BIGSERIAL,
    region_id BIGINT NOT NULL,
    year_id BIGINT NOT NULL,
    time TIMESTAMP WITH TIME ZONE NOT NULL,
    
    -- Moisture Content
    moisture_content_percent DECIMAL(5, 2),
    
    -- Texture & Structure
    sand_ratio DECIMAL(5, 2),
    clay_ratio DECIMAL(5, 2),
    silt_ratio DECIMAL(5, 2),
    
    -- Depth & Root Zone
    root_zone_depth_mm INTEGER,
    
    -- Organic Matter
    organic_matter_percent DECIMAL(5, 2),
    
    -- Infiltration
    infiltration_rate_mmhr DECIMAL(6, 2),
    
    -- Soil Water Thresholds
    field_capacity_percent DECIMAL(5, 2),
    wilting_point_percent DECIMAL(5, 2),
    
    -- Salinity & pH
    salinity_ece_dsm DECIMAL(5, 3),
    ph_level DECIMAL(3, 1),
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    PRIMARY KEY (metric_id, time),
    FOREIGN KEY (region_id) REFERENCES regions(region_id),
    FOREIGN KEY (year_id) REFERENCES observation_years(year_id),
    CONSTRAINT valid_moisture CHECK (moisture_content_percent BETWEEN 0 AND 100),
    CONSTRAINT valid_salinity CHECK (salinity_ece_dsm >= 0)
);

-- Convert to hypertable with automatic compression
SELECT create_hypertable(
    'soil_metrics',
    'time',
    if_not_exists => TRUE,
    time_partitioning_func => 'date_trunc(''1 day'', time)'
);

-- ===== 3.3 CLIMATE METRICS HYPERTABLE (Daily weather observations)
CREATE TABLE IF NOT EXISTS climate_metrics (
    metric_id BIGSERIAL,
    region_id BIGINT NOT NULL,
    year_id BIGINT NOT NULL,
    time TIMESTAMP WITH TIME ZONE NOT NULL,
    
    -- Rainfall
    rainfall_mm DECIMAL(6, 1),
    seasonal_rainfall_variability VARCHAR(50),
    
    -- Temperature
    temperature_max_c DECIMAL(4, 1),
    temperature_min_c DECIMAL(4, 1),
    temperature_mean_c DECIMAL(4, 1),
    
    -- Humidity
    relative_humidity_percent INTEGER,
    
    -- Wind
    wind_speed_ms DECIMAL(4, 2),
    
    -- Solar Radiation
    solar_radiation_mjm2day DECIMAL(6, 2),
    
    -- Evapotranspiration
    evapotranspiration_et0_mmday DECIMAL(5, 2),
    evapotranspiration_etc_mmday DECIMAL(5, 2),
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    PRIMARY KEY (metric_id, time),
    FOREIGN KEY (region_id) REFERENCES regions(region_id),
    FOREIGN KEY (year_id) REFERENCES observation_years(year_id),
    CONSTRAINT valid_humidity CHECK (relative_humidity_percent BETWEEN 0 AND 100),
    CONSTRAINT valid_rainfall CHECK (rainfall_mm >= 0)
);

-- Convert to hypertable
SELECT create_hypertable(
    'climate_metrics',
    'time',
    if_not_exists => TRUE,
    time_partitioning_func => 'date_trunc(''1 day'', time)'
);

-- ===== 3.4 DROUGHT INDICES HYPERTABLE (Drought monitoring)
CREATE TABLE IF NOT EXISTS drought_indices (
    metric_id BIGSERIAL,
    region_id BIGINT NOT NULL,
    year_id BIGINT NOT NULL,
    time TIMESTAMP WITH TIME ZONE NOT NULL,
    
    -- SPI - Standardized Precipitation Index
    spi_1month DECIMAL(5, 2),
    spi_3month DECIMAL(5, 2),
    spi_12month DECIMAL(5, 2),
    
    -- SPEI - Standardized Precipitation-Evapotranspiration Index
    spei_1month DECIMAL(5, 2),
    spei_3month DECIMAL(5, 2),
    spei_12month DECIMAL(5, 2),
    
    -- PDSI - Palmer Drought Severity Index
    pdsi_value DECIMAL(5, 2),
    
    -- Drought Classification
    drought_severity_class VARCHAR(20) DEFAULT 'None',
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    PRIMARY KEY (metric_id, time),
    FOREIGN KEY (region_id) REFERENCES regions(region_id),
    FOREIGN KEY (year_id) REFERENCES observation_years(year_id),
    CONSTRAINT valid_severity_class CHECK (
        drought_severity_class IN ('None', 'Abnormally Dry', 'Moderate Drought', 'Severe Drought', 'Extreme Drought')
    )
);

-- Convert to hypertable
SELECT create_hypertable(
    'drought_indices',
    'time',
    if_not_exists => TRUE,
    time_partitioning_func => 'date_trunc(''1 day'', time)'
);

-- ===== 3.5 AGRICULTURAL METRICS HYPERTABLE (Crop-specific metrics)
CREATE TABLE IF NOT EXISTS agricultural_metrics (
    metric_id BIGSERIAL,
    region_id BIGINT NOT NULL,
    year_id BIGINT NOT NULL,
    crop_id BIGINT NOT NULL,
    time TIMESTAMP WITH TIME ZONE NOT NULL,
    
    -- Crop Stage
    growth_stage VARCHAR(20),
    
    -- Crop Coefficient
    crop_coefficient_kc DECIMAL(4, 2),
    
    -- Crop Water Requirement
    crop_water_requirement_mmday DECIMAL(5, 2),
    
    -- Yield Reduction Factors
    yield_reduction_factor DECIMAL(5, 3),
    
    -- Irrigation
    irrigation_id BIGINT,
    irrigation_efficiency_percent INTEGER,
    water_applied_mm DECIMAL(6, 2),
    
    -- Plant Stress
    leaf_temperature_c DECIMAL(4, 1),
    stomatal_conductance DECIMAL(6, 3),
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    PRIMARY KEY (metric_id, time),
    FOREIGN KEY (region_id) REFERENCES regions(region_id),
    FOREIGN KEY (year_id) REFERENCES observation_years(year_id),
    FOREIGN KEY (crop_id) REFERENCES crop_types(crop_id),
    FOREIGN KEY (irrigation_id) REFERENCES irrigation_methods(irrigation_id),
    CONSTRAINT valid_kc CHECK (crop_coefficient_kc BETWEEN 0 AND 2),
    CONSTRAINT valid_efficiency CHECK (irrigation_efficiency_percent BETWEEN 0 AND 100)
);

-- Convert to hypertable
SELECT create_hypertable(
    'agricultural_metrics',
    'time',
    if_not_exists => TRUE,
    time_partitioning_func => 'date_trunc(''1 day'', time)'
);

-- ===== 3.6 REMOTE SENSING METRICS HYPERTABLE (Satellite observations)
CREATE TABLE IF NOT EXISTS remote_sensing_metrics (
    metric_id BIGSERIAL,
    region_id BIGINT NOT NULL,
    year_id BIGINT NOT NULL,
    time TIMESTAMP WITH TIME ZONE NOT NULL,
    
    -- NDVI - Vegetation Index
    ndvi DECIMAL(4, 3),
    
    -- NDWI - Water Index
    ndwi DECIMAL(4, 3),
    
    -- LST - Land Surface Temperature
    land_surface_temperature_c DECIMAL(5, 2),
    
    -- Satellite Soil Moisture
    satellite_soil_moisture_percent DECIMAL(5, 2),
    satellite_source VARCHAR(50),
    
    -- VCI - Vegetation Condition Index
    vegetation_condition_index DECIMAL(5, 2),
    
    -- ET from SEBAL/METRIC
    evapotranspiration_sebal_mmday DECIMAL(5, 2),
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    PRIMARY KEY (metric_id, time),
    FOREIGN KEY (region_id) REFERENCES regions(region_id),
    FOREIGN KEY (year_id) REFERENCES observation_years(year_id),
    CONSTRAINT valid_ndvi CHECK (ndvi BETWEEN -1 AND 1),
    CONSTRAINT valid_ndwi CHECK (ndwi BETWEEN -1 AND 1)
);

-- Convert to hypertable
SELECT create_hypertable(
    'remote_sensing_metrics',
    'time',
    if_not_exists => TRUE,
    time_partitioning_func => 'date_trunc(''1 day'', time)'
);

-- ===== 3.7 HYDROLOGY METRICS HYPERTABLE (Water balance & flow)
CREATE TABLE IF NOT EXISTS hydrology_metrics (
    metric_id BIGSERIAL,
    region_id BIGINT NOT NULL,
    year_id BIGINT NOT NULL,
    time TIMESTAMP WITH TIME ZONE NOT NULL,
    
    -- Precipitation vs Evapotranspiration
    precipitation_mm DECIMAL(6, 1),
    evapotranspiration_mm DECIMAL(6, 1),
    
    -- Groundwater
    groundwater_depth_m DECIMAL(6, 2),
    
    -- Runoff & River Flow
    runoff_mm DECIMAL(6, 1),
    river_flow_m3s DECIMAL(10, 2),
    
    -- Reservoir & Irrigation Supply
    reservoir_storage_m3 DECIMAL(15, 0),
    irrigation_supply_available_m3 DECIMAL(15, 0),
    
    -- Soil Water Deficit
    soil_water_deficit_index_mm DECIMAL(6, 2),
    
    -- Water Balance
    water_balance_percent DECIMAL(6, 2),
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    PRIMARY KEY (metric_id, time),
    FOREIGN KEY (region_id) REFERENCES regions(region_id),
    FOREIGN KEY (year_id) REFERENCES observation_years(year_id),
    CONSTRAINT valid_groundwater CHECK (groundwater_depth_m >= 0)
);

-- Convert to hypertable
SELECT create_hypertable(
    'hydrology_metrics',
    'time',
    if_not_exists => TRUE,
    time_partitioning_func => 'date_trunc(''1 day'', time)'
);

-- ============================================================================
-- 4. ANALYSIS TABLES
-- ============================================================================

-- Risk Assessment (one-to-many with region/crop combinations)
CREATE TABLE IF NOT EXISTS risk_assessments (
    assessment_id BIGSERIAL PRIMARY KEY,
    region_id BIGINT NOT NULL,
    year_id BIGINT NOT NULL,
    crop_id BIGINT NOT NULL,
    irrigation_id BIGINT,
    
    risk_level VARCHAR(30),  -- Low, Medium, High, Critical
    risk_score DECIMAL(5, 2),  -- 0-100
    recommendation TEXT,
    
    factors JSONB,  -- JSON array of contributing factors
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (region_id) REFERENCES regions(region_id),
    FOREIGN KEY (year_id) REFERENCES observation_years(year_id),
    FOREIGN KEY (crop_id) REFERENCES crop_types(crop_id),
    FOREIGN KEY (irrigation_id) REFERENCES irrigation_methods(irrigation_id)
);

-- ============================================================================
-- 5. DATA IMPORT & AUDIT LOGS
-- ============================================================================

-- Data import tracking
CREATE TABLE IF NOT EXISTS data_import_logs (
    log_id BIGSERIAL PRIMARY KEY,
    source VARCHAR(20),  -- Excel, API, Manual
    filename VARCHAR(255),
    metric_type VARCHAR(50),
    records_imported INTEGER DEFAULT 0,
    status VARCHAR(20),  -- Success, Failed, Partial
    import_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    imported_by VARCHAR(100),
    notes TEXT,
    error_details TEXT,
    
    CONSTRAINT valid_status CHECK (status IN ('Success', 'Failed', 'Partial'))
);

-- Audit log for data changes (compliance & traceability)
CREATE TABLE IF NOT EXISTS audit_logs (
    audit_id BIGSERIAL PRIMARY KEY,
    table_name VARCHAR(100),
    record_id BIGINT,
    action VARCHAR(20),  -- INSERT, UPDATE, DELETE
    user_id VARCHAR(100),
    old_values JSONB,
    new_values JSONB,
    change_timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    ip_address INET
);

-- ============================================================================
-- 5.1 USER AUTHENTICATION & SESSION TRACKING
-- ============================================================================

-- Login attempts log (for security & compliance)
CREATE TABLE IF NOT EXISTS login_attempts (
    attempt_id BIGSERIAL PRIMARY KEY,
    username VARCHAR(255),
    status VARCHAR(50),  -- success, failed_wrong_password, user_not_found, account_locked
    ip_address INET,
    user_agent TEXT,
    attempted_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    session_id VARCHAR(255),
    error_message TEXT,
    
    CONSTRAINT valid_login_status CHECK (
        status IN ('success', 'failed_wrong_password', 'user_not_found', 'account_locked', 'mfa_required', 'mfa_failed')
    )
);

-- User sessions (track active sessions & login history)
CREATE TABLE IF NOT EXISTS user_sessions (
    session_id VARCHAR(255) PRIMARY KEY,
    user_id BIGINT,
    username VARCHAR(255),
    login_time TIMESTAMP WITH TIME ZONE NOT NULL,
    last_activity TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    logout_time TIMESTAMP WITH TIME ZONE,
    ip_address INET,
    user_agent TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    session_duration_minutes INTEGER,
    
    CONSTRAINT valid_session CHECK (logout_time IS NULL OR logout_time > login_time)
);

-- User activity log (time-series, high-volume data)
CREATE TABLE IF NOT EXISTS user_activity_log (
    activity_id BIGSERIAL,
    user_id BIGINT NOT NULL,
    time TIMESTAMP WITH TIME ZONE NOT NULL,
    session_id VARCHAR(255),
    action VARCHAR(100),  -- page_view, data_export, data_import, config_change, report_generated, etc
    resource_type VARCHAR(100),  -- dashboard, analysis, data_ingestion, settings, admin, etc
    resource_name VARCHAR(255),  -- specific page/report name
    details JSONB,  -- Additional context (parameters, filters, results count, etc)
    ip_address INET,
    status VARCHAR(20),  -- success, failure
    response_time_ms INTEGER,
    
    PRIMARY KEY (activity_id, time),
    FOREIGN KEY (user_id) REFERENCES auth_user(id) ON DELETE CASCADE,
    FOREIGN KEY (session_id) REFERENCES user_sessions(session_id) ON DELETE SET NULL
);

-- Convert user_activity_log to hypertable for efficient time-series queries
SELECT create_hypertable(
    'user_activity_log',
    'time',
    if_not_exists => TRUE,
    time_partitioning_func => 'date_trunc(''1 day'', time)'
);

-- ============================================================================
-- 6. INDEXES FOR PERFORMANCE
-- ============================================================================

-- Spatial index for geospatial queries
CREATE INDEX IF NOT EXISTS idx_regions_geometry ON regions USING GIST(geometry);

-- Region & Year indexes for hypertables (faster filtering)
CREATE INDEX IF NOT EXISTS idx_environmental_snapshots_region_year 
    ON environmental_snapshots (region_id, year_id DESC) 
    WHERE time > CURRENT_DATE - INTERVAL '2 years';

CREATE INDEX IF NOT EXISTS idx_soil_metrics_region_year 
    ON soil_metrics (region_id, year_id DESC);

CREATE INDEX IF NOT EXISTS idx_climate_metrics_region_year 
    ON climate_metrics (region_id, year_id DESC);

CREATE INDEX IF NOT EXISTS idx_drought_indices_severity 
    ON drought_indices (region_id, drought_severity_class) 
    WHERE drought_severity_class != 'None';

CREATE INDEX IF NOT EXISTS idx_agricultural_metrics_crop 
    ON agricultural_metrics (crop_id, region_id, time DESC);

CREATE INDEX IF NOT EXISTS idx_remote_sensing_ndvi 
    ON remote_sensing_metrics (region_id, ndvi DESC)
    WHERE ndvi > 0;

-- Composite indexes for common queries
CREATE INDEX IF NOT EXISTS idx_climate_metrics_rainfall 
    ON climate_metrics (region_id, rainfall_mm DESC, time DESC);

CREATE INDEX IF NOT EXISTS idx_hydrology_water_balance 
    ON hydrology_metrics (region_id, water_balance_percent, time DESC);

-- Authentication & Session indexes
CREATE INDEX IF NOT EXISTS idx_login_attempts_username_time 
    ON login_attempts (username, attempted_at DESC);

CREATE INDEX IF NOT EXISTS idx_login_attempts_ip_address 
    ON login_attempts (ip_address, attempted_at DESC);

CREATE INDEX IF NOT EXISTS idx_login_attempts_failed 
    ON login_attempts (attempted_at DESC) 
    WHERE status != 'success';

CREATE INDEX IF NOT EXISTS idx_user_sessions_user_active 
    ON user_sessions (user_id, is_active) 
    WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_user_sessions_login_time 
    ON user_sessions (login_time DESC, logout_time);

CREATE INDEX IF NOT EXISTS idx_user_activity_user_time 
    ON user_activity_log (user_id, time DESC);

CREATE INDEX IF NOT EXISTS idx_user_activity_resource 
    ON user_activity_log (resource_type, time DESC);

CREATE INDEX IF NOT EXISTS idx_user_activity_session 
    ON user_activity_log (session_id, time DESC);

CREATE INDEX IF NOT EXISTS idx_audit_logs_table_record 
    ON audit_logs (table_name, record_id, change_timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_audit_logs_user 
    ON audit_logs (user_id, change_timestamp DESC);

-- ============================================================================
-- 7. VIEWS FOR ANALYTICS & DASHBOARD
-- ============================================================================

-- Current drought status by region
CREATE OR REPLACE VIEW v_current_drought_status AS
SELECT 
    r.region_id,
    r.name as region_name,
    ST_AsGeoJSON(r.geometry) as location,
    di.time as observation_date,
    di.spi_3month,
    di.spei_3month,
    di.pdsi_value,
    di.drought_severity_class,
    oy.label as year
FROM drought_indices di
JOIN regions r ON di.region_id = r.region_id
JOIN observation_years oy ON di.year_id = oy.year_id
WHERE di.time = (
    SELECT MAX(time) FROM drought_indices di2 
    WHERE di2.region_id = di.region_id
)
ORDER BY di.time DESC;

-- Vegetation health trend (last 30 days)
CREATE OR REPLACE VIEW v_vegetation_health_trend AS
SELECT 
    r.name as region_name,
    date_trunc('day', rs.time)::date as observation_date,
    AVG(rs.ndvi) as avg_ndvi,
    MIN(rs.ndvi) as min_ndvi,
    MAX(rs.ndvi) as max_ndvi,
    COUNT(*) as observations
FROM remote_sensing_metrics rs
JOIN regions r ON rs.region_id = r.region_id
WHERE rs.time > CURRENT_DATE - INTERVAL '30 days'
GROUP BY r.name, date_trunc('day', rs.time)
ORDER BY observation_date DESC;

-- Crop water requirement vs available water
CREATE OR REPLACE VIEW v_water_balance_summary AS
SELECT 
    r.name as region_name,
    ct.name as crop_name,
    date_trunc('day', am.time)::date as observation_date,
    AVG(am.crop_water_requirement_mmday) as avg_water_requirement_mm,
    AVG(hm.irrigation_supply_available_m3) as available_irrigation_m3,
    AVG(hm.water_balance_percent) as water_balance_percent
FROM agricultural_metrics am
JOIN regions r ON am.region_id = r.region_id
JOIN crop_types ct ON am.crop_id = ct.crop_id
LEFT JOIN hydrology_metrics hm ON am.region_id = hm.region_id 
    AND am.time = hm.time
WHERE am.time > CURRENT_DATE - INTERVAL '90 days'
GROUP BY r.name, ct.name, date_trunc('day', am.time)
ORDER BY observation_date DESC;

-- Regional risk scorecard
CREATE OR REPLACE VIEW v_risk_scorecard AS
SELECT 
    r.name as region_name,
    ct.name as crop_name,
    ra.risk_level,
    ra.risk_score,
    ra.recommendation,
    ra.updated_at,
    oy.label as year
FROM risk_assessments ra
JOIN regions r ON ra.region_id = r.region_id
JOIN crop_types ct ON ra.crop_id = ct.crop_id
JOIN observation_years oy ON ra.year_id = oy.year_id
ORDER BY ra.risk_score DESC;

-- ============================================================================
-- 8. CONTINUOUS AGGREGATES (Automatic downsampling for dashboards)
-- ============================================================================

-- Daily climate summary (aggregated from finer-grained observations)
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_daily_climate_summary AS
SELECT 
    time_bucket('1 day', time) as day,
    region_id,
    year_id,
    AVG(temperature_mean_c) as avg_temp_c,
    MAX(temperature_max_c) as max_temp_c,
    MIN(temperature_min_c) as min_temp_c,
    SUM(rainfall_mm) as total_rainfall_mm,
    AVG(relative_humidity_percent) as avg_humidity_percent,
    AVG(solar_radiation_mjm2day) as avg_solar_radiation,
    AVG(evapotranspiration_et0_mmday) as avg_et0_mmday
FROM climate_metrics
GROUP BY day, region_id, year_id;

-- Weekly drought status
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_weekly_drought_summary AS
SELECT 
    time_bucket('7 days', time) as week,
    region_id,
    year_id,
    AVG(spi_3month) as avg_spi_3m,
    AVG(spei_3month) as avg_spei_3m,
    MODE() WITHIN GROUP (ORDER BY drought_severity_class) as dominant_severity
FROM drought_indices
GROUP BY week, region_id, year_id;

-- Monthly agricultural performance
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_monthly_crop_performance AS
SELECT 
    time_bucket('1 month', time) as month,
    region_id,
    crop_id,
    year_id,
    COUNT(*) as observations,
    AVG(crop_water_requirement_mmday) as avg_water_req_mm,
    AVG(crop_coefficient_kc) as avg_kc,
    AVG(yield_reduction_factor) as avg_yield_reduction,
    AVG(water_applied_mm) as avg_water_applied_mm
FROM agricultural_metrics
GROUP BY month, region_id, crop_id, year_id;

-- Monthly vegetation health
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_monthly_vegetation_health AS
SELECT 
    time_bucket('1 month', time) as month,
    region_id,
    year_id,
    AVG(ndvi) as avg_ndvi,
    AVG(ndwi) as avg_ndwi,
    AVG(vegetation_condition_index) as avg_vci,
    MIN(land_surface_temperature_c) as min_lst_c,
    MAX(land_surface_temperature_c) as max_lst_c
FROM remote_sensing_metrics
GROUP BY month, region_id, year_id;

-- Create indexes on materialized views
CREATE INDEX IF NOT EXISTS idx_mv_daily_climate_day_region ON mv_daily_climate_summary(day, region_id);
CREATE INDEX IF NOT EXISTS idx_mv_weekly_drought_week_region ON mv_weekly_drought_summary(week, region_id);
CREATE INDEX IF NOT EXISTS idx_mv_monthly_crop_month_crop ON mv_monthly_crop_performance(month, crop_id);
CREATE INDEX IF NOT EXISTS idx_mv_monthly_veg_month_region ON mv_monthly_vegetation_health(month, region_id);

-- ============================================================================
-- 9. COMPRESSION POLICIES (for automatic data compression after aging)
-- ============================================================================
-- Compress data older than 30 days to save space
ALTER TABLE environmental_snapshots SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'time DESC',
    timescaledb.compress_segmentby = 'region_id'
);
SELECT add_compression_policy('environmental_snapshots', INTERVAL '30 days', if_not_exists => TRUE);

ALTER TABLE soil_metrics SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'time DESC',
    timescaledb.compress_segmentby = 'region_id'
);
SELECT add_compression_policy('soil_metrics', INTERVAL '30 days', if_not_exists => TRUE);

ALTER TABLE climate_metrics SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'time DESC',
    timescaledb.compress_segmentby = 'region_id'
);
SELECT add_compression_policy('climate_metrics', INTERVAL '30 days', if_not_exists => TRUE);

ALTER TABLE drought_indices SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'time DESC',
    timescaledb.compress_segmentby = 'region_id'
);
SELECT add_compression_policy('drought_indices', INTERVAL '30 days', if_not_exists => TRUE);

ALTER TABLE agricultural_metrics SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'time DESC',
    timescaledb.compress_segmentby = 'region_id,crop_id'
);
SELECT add_compression_policy('agricultural_metrics', INTERVAL '30 days', if_not_exists => TRUE);

ALTER TABLE remote_sensing_metrics SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'time DESC',
    timescaledb.compress_segmentby = 'region_id'
);
SELECT add_compression_policy('remote_sensing_metrics', INTERVAL '30 days', if_not_exists => TRUE);

ALTER TABLE hydrology_metrics SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'time DESC',
    timescaledb.compress_segmentby = 'region_id'
);
SELECT add_compression_policy('hydrology_metrics', INTERVAL '30 days', if_not_exists => TRUE);

-- User activity log compression (compress after 90 days, keep activity logs longer for audit)
ALTER TABLE user_activity_log SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'time DESC',
    timescaledb.compress_segmentby = 'user_id'
);
SELECT add_compression_policy('user_activity_log', INTERVAL '90 days', if_not_exists => TRUE);

-- ============================================================================
-- 10. RETENTION POLICIES (automatic data deletion after retention period)
-- ============================================================================
-- Keep detailed data for 2 years, then delete
SELECT add_retention_policy('environmental_snapshots', INTERVAL '2 years', if_not_exists => TRUE);
SELECT add_retention_policy('soil_metrics', INTERVAL '2 years', if_not_exists => TRUE);
SELECT add_retention_policy('climate_metrics', INTERVAL '2 years', if_not_exists => TRUE);
SELECT add_retention_policy('drought_indices', INTERVAL '2 years', if_not_exists => TRUE);
SELECT add_retention_policy('agricultural_metrics', INTERVAL '2 years', if_not_exists => TRUE);
SELECT add_retention_policy('remote_sensing_metrics', INTERVAL '3 years', if_not_exists => TRUE);  -- Keep longer for trend analysis
SELECT add_retention_policy('hydrology_metrics', INTERVAL '2 years', if_not_exists => TRUE);

-- User activity logs: keep for 1 year for audit compliance (longer than metrics)
SELECT add_retention_policy('user_activity_log', INTERVAL '1 year', if_not_exists => TRUE);

-- Login attempts: keep for 90 days for security audit
-- (not a hypertable, so use manual cleanup via trigger or cron)

-- User sessions: keep for 30 days (after logout is set, can be deleted)
-- (can be managed via Django session backend or PostgreSQL trigger)

-- ============================================================================
-- 11. GRANTS & SECURITY (PostgreSQL role-based access)
-- ============================================================================
-- Create application user (with limited privileges)
-- CREATE ROLE agri_app_user WITH LOGIN PASSWORD 'secure_password';
-- GRANT CONNECT ON DATABASE agri_db TO agri_app_user;
-- GRANT USAGE ON SCHEMA public TO agri_app_user;
-- GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO agri_app_user;
-- GRANT SELECT, USAGE ON ALL SEQUENCES IN SCHEMA public TO agri_app_user;

-- Create read-only analytics user
-- CREATE ROLE agri_analyst WITH LOGIN PASSWORD 'analyst_password';
-- GRANT CONNECT ON DATABASE agri_db TO agri_analyst;
-- GRANT USAGE ON SCHEMA public TO agri_analyst;
-- GRANT SELECT ON ALL TABLES IN SCHEMA public TO agri_analyst;

-- ============================================================================
-- 12. PARTITIONING STRATEGY (already handled by TimescaleDB hypertables)
-- ============================================================================
-- TimescaleDB automatically partitions time-series tables:
-- - Default: 1 month partitions for 1-day data
-- - Can be adjusted per hypertable if needed
-- SELECT set_chunk_time_interval('climate_metrics', INTERVAL '1 week');

-- ============================================================================
-- 13. SAMPLE DATA FOR TESTING
-- ============================================================================
-- Insert test regions
INSERT INTO regions (name, country, latitude, longitude, elevation_m, area_km2) 
VALUES 
    ('Ichkeul', 'Tunisia', 37.2694, 9.1585, 8, 225),
    ('Kairouan', 'Tunisia', 35.6713, 9.5191, 80, 2650),
    ('Meknes', 'Morocco', 33.8869, -5.5454, 505, 2790),
    ('Skhira', 'Tunisia', 35.2397, 8.6612, 11, 550)
ON CONFLICT DO NOTHING;

-- Insert observation years
INSERT INTO observation_years (label, start_date, end_date, season)
VALUES 
    ('2024', '2024-01-01', '2024-12-31', 'Full Year'),
    ('2025', '2025-01-01', '2025-12-31', 'Full Year'),
    ('2026', '2026-01-01', '2026-12-31', 'Full Year')
ON CONFLICT DO NOTHING;

-- Insert crop types
INSERT INTO crop_types (name, scientific_name, crop_family, water_requirement_mm_season, growing_period_days)
VALUES 
    ('Wheat', 'Triticum aestivum', 'Poaceae', 400, 150),
    ('Barley', 'Hordeum vulgare', 'Poaceae', 350, 140),
    ('Olive', 'Olea europaea', 'Oleaceae', 500, 365),
    ('Date Palm', 'Phoenix dactylifera', 'Arecaceae', 1200, 365),
    ('Alfalfa', 'Medicago sativa', 'Fabaceae', 800, 180)
ON CONFLICT DO NOTHING;

-- Insert irrigation methods
INSERT INTO irrigation_methods (name, efficiency_percent, water_application_uniformity)
VALUES 
    ('Drip Irrigation', 90, 95),
    ('Sprinkler', 75, 85),
    ('Flood/Basin', 50, 60),
    ('Furrow', 60, 70),
    ('Center Pivot', 85, 90)
ON CONFLICT DO NOTHING;

-- ============================================================================
-- 14. BACKUP & RECOVERY NOTES
-- ============================================================================
-- For production backups, use:
--
-- Full backup (base + WAL):
--   pg_basebackup -D /backup/base -F tar -z
--   
-- Point-in-time recovery (pgBackRest):
--   pgbackrest backup
--   pgbackrest restore --delta --type=time --target='2024-05-26 14:30:00'
--
-- Continuous archiving:
--   archive_command = 'pgbackrest archive-push %p'
--   archive_timeout = 300
--
-- ============================================================================
-- 15. PERFORMANCE TUNING FOR PRODUCTION
-- ============================================================================
-- Recommended postgresql.conf settings:
--
-- For 32GB RAM server:
--   shared_buffers = 8GB
--   effective_cache_size = 24GB
--   maintenance_work_mem = 2GB
--   checkpoint_completion_target = 0.9
--   wal_buffers = 16MB
--   default_statistics_target = 100
--   random_page_cost = 1.1
--
-- For TimescaleDB:
--   max_connections = 200
--   max_parallel_workers_per_gather = 4
--   max_parallel_workers = 8
--
-- ============================================================================

COMMIT;

-- ============================================================================
-- VERIFICATION QUERIES
-- ============================================================================
-- To verify schema after creation, run:
--
-- SELECT hypertable_name FROM timescaledb_information.hypertables;
-- SELECT * FROM regions;
-- SELECT * FROM observation_years;
-- SELECT * FROM crop_types;
-- SELECT COUNT(*) FROM climate_metrics;
--
-- ============================================================================
-- NEW: USER TRACKING & AUTHENTICATION TABLES
-- ============================================================================
-- The following tables have been added for comprehensive user tracking:
--
-- 1. login_attempts - Track all login attempts (success/failure)
--    SELECT COUNT(*) FROM login_attempts;
--
-- 2. user_sessions - Track active and historical user sessions
--    SELECT * FROM user_sessions WHERE is_active = TRUE;
--
-- 3. user_activity_log - TimescaleDB hypertable for all user activities
--    SELECT COUNT(*) FROM user_activity_log;
--    SELECT * FROM timescaledb_information.hypertables WHERE hypertable_name = 'user_activity_log';
--
-- 4. audit_logs (enhanced) - Track all data changes with user attribution
--    SELECT * FROM audit_logs ORDER BY change_timestamp DESC LIMIT 10;
--
-- For complete user tracking setup, see: USER_TRACKING_GUIDE.md
--
-- ============================================================================
