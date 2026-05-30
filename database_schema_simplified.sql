-- ============================================================================
-- ABCDryBASiN Agricultural Metrics Dashboard - PostgreSQL Schema (Simplified)
-- ============================================================================
-- Database: Agricultural monitoring system for North Africa
-- Engine: PostgreSQL 14+ with PostGIS 3.x (NO TimescaleDB - simpler setup)
-- Purpose: Time-series climate, soil, drought, and agricultural metrics
-- ============================================================================

-- ============================================================================
-- 1. EXTENSIONS
-- ============================================================================
-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- 2. DIMENSION TABLES (Reference Data)
-- ============================================================================

-- Regions/Zones for spatial monitoring
CREATE TABLE IF NOT EXISTS regions (
    region_id BIGSERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    country VARCHAR(100),
    latitude DECIMAL(10, 6),
    longitude DECIMAL(10, 6),
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
-- 3. REGULAR TABLES FOR METRICS (Not hypertables - regular PostgreSQL)
-- ============================================================================

-- Environmental Snapshot (Mixed metrics for quick dashboard view)
CREATE TABLE IF NOT EXISTS environmental_snapshots (
    snapshot_id BIGSERIAL PRIMARY KEY,
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
    
    FOREIGN KEY (region_id) REFERENCES regions(region_id),
    FOREIGN KEY (year_id) REFERENCES observation_years(year_id)
);

-- Soil Metrics
CREATE TABLE IF NOT EXISTS soil_metrics (
    metric_id BIGSERIAL PRIMARY KEY,
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
    
    FOREIGN KEY (region_id) REFERENCES regions(region_id),
    FOREIGN KEY (year_id) REFERENCES observation_years(year_id),
    CONSTRAINT valid_moisture CHECK (moisture_content_percent BETWEEN 0 AND 100),
    CONSTRAINT valid_salinity CHECK (salinity_ece_dsm >= 0)
);

-- Climate Metrics (Daily weather observations)
CREATE TABLE IF NOT EXISTS climate_metrics (
    metric_id BIGSERIAL PRIMARY KEY,
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
    
    FOREIGN KEY (region_id) REFERENCES regions(region_id),
    FOREIGN KEY (year_id) REFERENCES observation_years(year_id),
    CONSTRAINT valid_humidity CHECK (relative_humidity_percent BETWEEN 0 AND 100),
    CONSTRAINT valid_rainfall CHECK (rainfall_mm >= 0)
);

-- Drought Indices (Drought monitoring)
CREATE TABLE IF NOT EXISTS drought_indices (
    metric_id BIGSERIAL PRIMARY KEY,
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
    
    FOREIGN KEY (region_id) REFERENCES regions(region_id),
    FOREIGN KEY (year_id) REFERENCES observation_years(year_id),
    CONSTRAINT valid_severity_class CHECK (
        drought_severity_class IN ('None', 'Abnormally Dry', 'Moderate Drought', 'Severe Drought', 'Extreme Drought')
    )
);

-- Agricultural Metrics (Crop-specific metrics)
CREATE TABLE IF NOT EXISTS agricultural_metrics (
    metric_id BIGSERIAL PRIMARY KEY,
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
    
    FOREIGN KEY (region_id) REFERENCES regions(region_id),
    FOREIGN KEY (year_id) REFERENCES observation_years(year_id),
    FOREIGN KEY (crop_id) REFERENCES crop_types(crop_id),
    FOREIGN KEY (irrigation_id) REFERENCES irrigation_methods(irrigation_id),
    CONSTRAINT valid_kc CHECK (crop_coefficient_kc BETWEEN 0 AND 2),
    CONSTRAINT valid_efficiency CHECK (irrigation_efficiency_percent BETWEEN 0 AND 100)
);

-- Remote Sensing Metrics (Satellite observations)
CREATE TABLE IF NOT EXISTS remote_sensing_metrics (
    metric_id BIGSERIAL PRIMARY KEY,
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
    
    FOREIGN KEY (region_id) REFERENCES regions(region_id),
    FOREIGN KEY (year_id) REFERENCES observation_years(year_id),
    CONSTRAINT valid_ndvi CHECK (ndvi BETWEEN -1 AND 1),
    CONSTRAINT valid_ndwi CHECK (ndwi BETWEEN -1 AND 1)
);

-- Hydrology Metrics (Water balance & flow)
CREATE TABLE IF NOT EXISTS hydrology_metrics (
    metric_id BIGSERIAL PRIMARY KEY,
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
    
    FOREIGN KEY (region_id) REFERENCES regions(region_id),
    FOREIGN KEY (year_id) REFERENCES observation_years(year_id),
    CONSTRAINT valid_groundwater CHECK (groundwater_depth_m >= 0)
);

-- ============================================================================
-- 4. ANALYSIS TABLES
-- ============================================================================

-- Risk Assessment
CREATE TABLE IF NOT EXISTS risk_assessments (
    assessment_id BIGSERIAL PRIMARY KEY,
    region_id BIGINT NOT NULL,
    year_id BIGINT NOT NULL,
    crop_id BIGINT NOT NULL,
    irrigation_id BIGINT,
    
    risk_level VARCHAR(30),
    risk_score DECIMAL(5, 2),
    recommendation TEXT,
    factors JSONB,
    
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
    source VARCHAR(20),
    filename VARCHAR(255),
    metric_type VARCHAR(50),
    records_imported INTEGER DEFAULT 0,
    status VARCHAR(20),
    import_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    imported_by VARCHAR(100),
    notes TEXT,
    error_details TEXT,
    
    CONSTRAINT valid_status CHECK (status IN ('Success', 'Failed', 'Partial'))
);

-- Audit log for data changes
CREATE TABLE IF NOT EXISTS audit_logs (
    audit_id BIGSERIAL PRIMARY KEY,
    table_name VARCHAR(100),
    record_id BIGINT,
    action VARCHAR(20),
    user_id VARCHAR(100),
    old_values JSONB,
    new_values JSONB,
    change_timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    ip_address INET
);

-- ============================================================================
-- 5.1 USER AUTHENTICATION & SESSION TRACKING
-- ============================================================================

-- Login attempts log
CREATE TABLE IF NOT EXISTS login_attempts (
    attempt_id BIGSERIAL PRIMARY KEY,
    username VARCHAR(255),
    status VARCHAR(50),
    ip_address INET,
    user_agent TEXT,
    attempted_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    session_id VARCHAR(255),
    error_message TEXT,
    
    CONSTRAINT valid_login_status CHECK (
        status IN ('success', 'failed_wrong_password', 'user_not_found', 'account_locked', 'mfa_required', 'mfa_failed')
    )
);

-- User sessions
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

-- User activity log
CREATE TABLE IF NOT EXISTS user_activity_log (
    activity_id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    time TIMESTAMP WITH TIME ZONE NOT NULL,
    session_id VARCHAR(255),
    action VARCHAR(100),
    resource_type VARCHAR(100),
    resource_name VARCHAR(255),
    details JSONB,
    ip_address INET,
    status VARCHAR(20),
    response_time_ms INTEGER,
    
    FOREIGN KEY (session_id) REFERENCES user_sessions(session_id) ON DELETE SET NULL
    -- Note: user_id references Django's auth_user(id), constraint added after Django migrations
);

-- ============================================================================
-- 6. INDEXES FOR PERFORMANCE
-- ============================================================================

-- Time-based indexes (for faster queries on time field)
CREATE INDEX IF NOT EXISTS idx_environmental_snapshots_time 
    ON environmental_snapshots (time DESC);

CREATE INDEX IF NOT EXISTS idx_soil_metrics_time 
    ON soil_metrics (time DESC);

CREATE INDEX IF NOT EXISTS idx_climate_metrics_time 
    ON climate_metrics (time DESC);

CREATE INDEX IF NOT EXISTS idx_drought_indices_time 
    ON drought_indices (time DESC);

CREATE INDEX IF NOT EXISTS idx_agricultural_metrics_time 
    ON agricultural_metrics (time DESC);

CREATE INDEX IF NOT EXISTS idx_remote_sensing_metrics_time 
    ON remote_sensing_metrics (time DESC);

CREATE INDEX IF NOT EXISTS idx_hydrology_metrics_time 
    ON hydrology_metrics (time DESC);

-- Region & Year indexes
CREATE INDEX IF NOT EXISTS idx_environmental_snapshots_region_year 
    ON environmental_snapshots (region_id, year_id DESC);

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

CREATE INDEX IF NOT EXISTS idx_user_sessions_user_active 
    ON user_sessions (user_id, is_active) 
    WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_user_activity_user_time 
    ON user_activity_log (user_id, time DESC);

CREATE INDEX IF NOT EXISTS idx_user_activity_resource 
    ON user_activity_log (resource_type, time DESC);

CREATE INDEX IF NOT EXISTS idx_audit_logs_table_record 
    ON audit_logs (table_name, record_id, change_timestamp DESC);

-- ============================================================================
-- 7. VIEWS FOR ANALYTICS & DASHBOARD
-- ============================================================================

-- Current drought status by region
CREATE OR REPLACE VIEW v_current_drought_status AS
SELECT 
    r.region_id,
    r.name as region_name,
    CONCAT('{"type":"Point","coordinates":[', r.longitude, ',', r.latitude, ']}') as location_geojson,
    r.latitude,
    r.longitude,
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
    DATE(rs.time) as observation_date,
    AVG(rs.ndvi) as avg_ndvi,
    MIN(rs.ndvi) as min_ndvi,
    MAX(rs.ndvi) as max_ndvi,
    COUNT(*) as observations
FROM remote_sensing_metrics rs
JOIN regions r ON rs.region_id = r.region_id
WHERE rs.time > NOW() - INTERVAL '30 days'
GROUP BY r.name, DATE(rs.time)
ORDER BY observation_date DESC;

-- Crop water requirement vs available water
CREATE OR REPLACE VIEW v_water_balance_summary AS
SELECT 
    r.name as region_name,
    ct.name as crop_name,
    DATE(am.time) as observation_date,
    AVG(am.crop_water_requirement_mmday) as avg_water_requirement_mm,
    AVG(hm.irrigation_supply_available_m3) as available_irrigation_m3,
    AVG(hm.water_balance_percent) as water_balance_percent
FROM agricultural_metrics am
JOIN regions r ON am.region_id = r.region_id
JOIN crop_types ct ON am.crop_id = ct.crop_id
LEFT JOIN hydrology_metrics hm ON am.region_id = hm.region_id 
    AND DATE(am.time) = DATE(hm.time)
WHERE am.time > NOW() - INTERVAL '90 days'
GROUP BY r.name, ct.name, DATE(am.time)
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
-- 8. SAMPLE DATA FOR TESTING
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
-- VERIFICATION QUERIES
-- ============================================================================
-- To verify schema after creation, run:
--
-- SELECT table_name FROM information_schema.tables 
-- WHERE table_schema = 'public' ORDER BY table_name;
--
-- SELECT * FROM regions;
-- SELECT * FROM observation_years;
-- SELECT * FROM crop_types;
-- SELECT COUNT(*) FROM climate_metrics;
--
-- ============================================================================
-- NOTES: SIMPLIFIED SCHEMA (NO TIMESCALEDB, NO POSTGIS)
-- ============================================================================
-- This schema uses regular PostgreSQL tables instead of TimescaleDB hypertables
-- Geospatial features use simple latitude/longitude decimals (not PostGIS geometry)
--
-- Regular tables are:
-- - climate_metrics
-- - soil_metrics
-- - drought_indices
-- - agricultural_metrics
-- - remote_sensing_metrics
-- - hydrology_metrics
-- - environmental_snapshots
-- - user_activity_log
--
-- Benefits of this simplified approach:
-- ✓ Works immediately (no extensions needed)
-- ✓ All indexes for fast queries
-- ✓ All constraints and validations
-- ✓ Can upgrade to TimescaleDB later
-- ✓ Can add PostGIS later for advanced geospatial queries
--
-- Trade-offs:
-- - No automatic compression (use manual VACUUM if needed)
-- - No automatic data retention (delete old records manually if needed)
-- - Slower with very large datasets (100M+ records)
-- - Basic location storage (no spatial indexes, use PostGIS for advanced geo queries)
--
-- For production with large datasets or advanced GIS, can upgrade later
-- ============================================================================

COMMIT;
