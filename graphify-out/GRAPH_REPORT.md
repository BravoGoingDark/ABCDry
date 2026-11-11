# Graph Report - CURSORAGRI - Copy - Copy  (2026-11-11)

## Corpus Check
- 214 files · ~304,368 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 48 file(s) not represented in the graph (top: .csv 15, .nc 13, .css 5)

## Summary
- 3138 nodes · 6615 edges · 190 communities (129 shown, 61 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 432 edges (avg confidence: 0.88)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `325cdf64`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- turf.min.js
- admin_views.py
- models.py
- os
- ingestion_views.py
- station_climate.py
- seasonal_validation.py
- l
- crop_suitability.py
- temp_views.py
- views/__init__.py
- convert_stations.py
- Agricultural Metrics Dashboard - Quick Start Guide
- Command
- farmer_service.py
- Data Ingestion Implementation Guide
- XGBoostDroughtRiskPredictor
- Agricultural Metrics Dashboard - Implementation Guide
- numpy
- Database Setup Guide
- o
- ============================================================================
- ============================================================================
- 2. QUERY EXAMPLES & ANALYTICS
- experiment_spei_improvements.py
- jd
- ============================================================================
- map_tiles.py
- 2. Platform Navigation and Main Pages
- pathlib
- Implementation Summary - Agricultural Metrics Dashboard
- require_http_methods
- numpy
- test_assistant_brain.py
- PDF
- ============================================================================
- leaflet.js
- .submit_form_data
- dashboard_view
- a
- datetime
- assistant_nlu.py
- ajax_upload_file
- tasks.py
- _deny_data_access
- spei_outlook_weather.js
- sentinel_tiles.py
- verify_spei_forecasts.py
- je
- TestCase
- Comprehensive Agronomic & Drought Management Field Guide
- Automated Data Gathering Setup Guide
- retrieval.py
- How the Drought Risk Score Works (Simple Terms)
- assistant_brain.py
- SimpleTestCase
- spei_from_balance
- t
- train_xgboost_quick.py
- Automated Data Gathering - QUICK START
- answer_question
- gather
- DocumentIndex
- oi
- rag_config
- train_lstm_quick.py
- smartfarm.py
- _is_admin_user
- Command
- RetrievalIndexTests
- drought_grid_map.js
- services
- Jt
- g
- Command
- SentinelTileTests
- mn
- ba
- sys
- Command
- DroughtLLMExplainer
- FarmerRoleTests
- PHASE 2: DATABASE CREATION & CONFIGURATION
- ClimateLayerTests
- FormulaReport
- e
- p
- farmer_views.py
- ._fetch
- TABLE OF CONTENTS
- 11. APPENDIX: FORMULA REFERENCE
- 2. METRIC GROUP 1: SOIL METRICS
- F
- rt
- tests.py
- climate_indices.py
- export_render_fixture.py
- 3. METRIC GROUP 2: CLIMATE METRICS
- 6. METRIC GROUP 5: REMOTE SENSING METRICS
- ============================================================================
- validate_numbers
- data_digests
- historical_observations_api
- 7. METRIC GROUP 6: HYDROLOGY METRICS
- 8. HOW AI PREDICTS DROUGHT
- 1.1 Environment Setup
- _haversine_distance
- build_assistant_index.py
- drought_warning
- parse_reading
- 0025_dedupe_speiforecasts.py
- dashboard/urls.py
- _access_token
- 5. METRIC GROUP 4: AGRICULTURAL METRICS
- ============================================================================
- PHASE 3: CONNECTION POOLING SETUP
- django_db_models_deletion
- d
- json
- DashboardDataContractTests
- 4. METRIC GROUP 3: DROUGHT INDICES
- PHASE 4: BACKUP & RECOVERY SETUP
- PHASE 5: DJANGO CONFIGURATION
- PHASE 6: PERFORMANCE OPTIMIZATION
- CURSORAGRI
- analysis_export_csv
- analysis_results
- i
- fe
- middleware.py
- UserRoleTests
- embed_texts
- sync
- PHASE 7: VERIFICATION & TESTING
- PHASE 8: CUTOVER & GO-LIVE
- fallback_answer
- calculations_view
- bi
- Gridded drought forecast — Ichkeul basin (29 cells)
- historical_export_excel
- CLAUDE.md
- .handle
- startup_automation.sh
- configured
- drought_prediction_api
- WeatherForecastServiceTests
- SoilProbeReading
- train_spei_models
- train_spei_models.py
- _score_from_spei
- _Model
- resolve_model
- NoFakeSensorTests
- Command
- analytics_views.py
- LSTMDroughtForecaster
- Farm
- StationClimateTests
- DroughtPredictionPipeline
- Command
- _fit_monthly_loglogistic
- weather_forecast.py
- fao56_et0
- _spei_from_cdf
- manage.py
- .forecast_spi_risk
- Command
- Command

## God Nodes (most connected - your core abstractions)
1. `Region` - 84 edges
2. `DroughtPredictionPipeline` - 57 edges
3. `ClimateMetrics` - 54 edges
4. `ObservationYear` - 44 edges
5. `DroughtIndices` - 39 edges
6. `RemoteSensingMetrics` - 39 edges
7. `a()` - 36 edges
8. `SoilMetrics` - 34 edges
9. `l()` - 34 edges
10. `o()` - 32 edges

## Surprising Connections (you probably didn't know these)
- `3. Model` --references--> `promote_scenarios()`  [INFERRED]
  docs/DROUGHT_GRID_FORECAST.md → dashboard/prediction_engine/drought_grid.py
- `4. Verification protocol` --references--> `DroughtGridTests`  [INFERRED]
  docs/DROUGHT_GRID_FORECAST.md → dashboard/tests.py
- `2. Data (per cell, monthly, Jan 1981 → last complete CHIRPS month)` --references--> `fao56_et0()`  [INFERRED]
  docs/DROUGHT_GRID_FORECAST.md → dashboard/prediction_engine/physical_helpers.py
- `8. Operations` --references--> `DroughtGridForecast`  [INFERRED]
  docs/DROUGHT_GRID_FORECAST.md → dashboard/models.py
- `🛰️ Method 4: Google Earth Engine (Real Satellite Data)` --references--> `DroughtIndices`  [INFERRED]
  docs/DATAINGEST_GUIDE.md → dashboard/models.py

## Import Cycles
- None detected.

## Communities (190 total, 61 thin omitted)

### Community 0 - "turf.min.js"
Cohesion: 0.03
Nodes (58): au(), Bg(), bs(), ca(), Ct(), ds(), dt(), du() (+50 more)

### Community 1 - "admin_views.py"
Cohesion: 0.10
Nodes (17): UserCreateForm, Meta, admin_confirm_user(), admin_delete_user(), admin_edit_user(), admin_farms(), admin_panel(), _farm_in_ichkeul() (+9 more)

### Community 2 - "models.py"
Cohesion: 0.07
Nodes (32): create_reference_data(), Command, AgriculturalMetrics, Meta, ClimateMetrics, Meta, CropType, Meta (+24 more)

### Community 3 - "os"
Cohesion: 0.03
Nodes (21): Migration, Migration, Migration, Migration, Migration, Migration, Migration, Migration (+13 more)

### Community 4 - "ingestion_views.py"
Cohesion: 0.06
Nodes (25): DataIngestionError, ExcelImportForm, ajax_upload_file(), api_submit_metrics(), download_metric_template(), export_metrics_excel(), _get_or_create_crop(), _get_or_create_year() (+17 more)

### Community 5 - "station_climate.py"
Cohesion: 0.12
Nodes (17): Command, apply_calibration(), build_days(), calibrate(), _chunks(), _dataset_frame(), _day(), _ee() (+9 more)

### Community 6 - "seasonal_validation.py"
Cohesion: 0.11
Nodes (7): Region, Meta, download(), extract_region_series(), main(), observed_monthly_mm(), skill_gate()

### Community 7 - "l"
Cohesion: 0.08
Nodes (60): r(), aa(), ay(), be(), bi(), bt(), bu(), c() (+52 more)

### Community 8 - "crop_suitability.py"
Cohesion: 0.13
Nodes (10): annual_kc(), effective_rain(), rank_crops(), region_soil(), salinity_factor(), score_crop(), simulate_season(), texture_class() (+2 more)

### Community 9 - "temp_views.py"
Cohesion: 0.04
Nodes (23): agricultural_metrics_view(), _build_browser_row(), _build_browser_section(), calculations_chart_api(), calculations_data(), climate_metrics_view(), data_ingestion(), _degree_to_compass() (+15 more)

### Community 10 - "views/__init__.py"
Cohesion: 0.05
Nodes (33): get_region_forecast(), region_point(), regions_with_coordinates(), live_metrics_api(), metrics_browser(), assistant_chat_api(), assistant_page_view(), calculations_chart_api() (+25 more)

### Community 11 - "convert_stations.py"
Cohesion: 0.17
Nodes (15): cell_xml(), esc(), load_sheet(), rowxml(), T(), write_xlsx(), xldate(), cell_xml() (+7 more)

### Community 12 - "Agricultural Metrics Dashboard - Quick Start Guide"
Cohesion: 0.05
Nodes (42): 1. Install Dependencies, 1. **Soil Metrics** 🌍, 2. Apply Database Migrations, 2. **Climate Metrics** ☀️, 3. Create Admin User, 3. **Drought Indices** 💧, 4. **Agricultural Metrics** 🌱, 4. Run Development Server (+34 more)

### Community 14 - "farmer_service.py"
Cohesion: 0.20
Nodes (7): apply_boundary(), clean_polygon(), FarmGeometryError, haversine_km(), nearest_region(), polygon_area_centroid(), _project()

### Community 15 - "Data Ingestion Implementation Guide"
Cohesion: 0.05
Nodes (39): 1. **Soil Metrics**, 2. **Climate Metrics**, 3. **Drought Indices**, 4. **Agricultural Metrics**, 5. **Remote Sensing Metrics**, 6. **Hydrology Metrics**, 📈 Best Practices, "Column not found" (+31 more)

### Community 17 - "Agricultural Metrics Dashboard - Implementation Guide"
Cohesion: 0.05
Nodes (36): 1. Soil Metrics 🌍, 2. Climate Metrics ☀️, 3. Drought Indices 💧, 4. Agricultural Metrics 🌱, 5. Remote Sensing Metrics 🛰️, 6. Hydrology Metrics 💧, Add Metrics, Agricultural Metrics Dashboard - Implementation Guide (+28 more)

### Community 18 - "numpy"
Cohesion: 0.08
Nodes (21): calculate_spei(), _aggregate_monthly(), _build_features(), build_spei_dataset(), _compute_et0_from_monthly(), _compute_monthly_spei(), _expanding_month_climatology(), _load_all_points() (+13 more)

### Community 19 - "Database Setup Guide"
Cohesion: 0.06
Nodes (35): 1. Create Database, 1. Create Indexes, 2. Create Database User, 2. Enable Query Logging, 3. Configure Django Settings, 4. Install Required Python Packages, Additional Resources, Backup and Restore (+27 more)

### Community 20 - "o"
Cohesion: 0.10
Nodes (34): Ar(), b(), d(), M(), N(), P(), de(), Dr() (+26 more)

### Community 21 - "============================================================================"
Cohesion: 0.06
Nodes (34): ============================================================================, 1. **database_schema_timescaledb.sql** (700+ lines), 2. **settings_production.py** (250+ lines), 3. **pgbouncer.ini** (180+ lines), ============================================================================, 4. **pgbouncer_userlist.txt**, 5. **pgbackrest.conf** (250+ lines), 6. **.env.production** (+26 more)

### Community 22 - "============================================================================"
Cohesion: 0.06
Nodes (33): ============================================================================, 10. **DATABASE_IMPLEMENTATION_SUMMARY.md** (500 lines), 1. **database_schema_timescaledb.sql** (700 lines), 2. **settings_production.py** (250 lines), 3. **pgbouncer.ini** (180 lines), ============================================================================, 4. **pgbouncer_userlist.txt**, 5. **pgbackrest.conf** (250 lines) (+25 more)

### Community 23 - "2. QUERY EXAMPLES & ANALYTICS"
Cohesion: 0.06
Nodes (33): ============================================================================, 1.1 Database Health Check, 1.2 Manual Backup, 1.3 Refresh Materialized Views, 1. DAILY OPERATIONS, 2.1 Historical Drought Analysis, 2.2 Water Balance by Region, 2.3 Crop Performance Comparison (+25 more)

### Community 24 - "experiment_spei_improvements.py"
Cohesion: 0.22
Nodes (9): _month_ordinal(), _severity_class(), class_metrics(), main(), class_metrics(), main(), make_model(), persistence_cm() (+1 more)

### Community 25 - "jd"
Cohesion: 0.09
Nodes (22): bd(), cd(), dd(), Ed(), s(), fd(), gd(), hd() (+14 more)

### Community 26 - "============================================================================"
Cohesion: 0.07
Nodes (29): ============================================================================, 1. Create Django Models, 1. Find Failed Login Attempts (Security), 1. LOGIN_ATTEMPTS (Compliance & Security), 2. Create Custom Authentication Backend, 2. User Activity Timeline, 2. USER_SESSIONS (Session Management), 3. Activity Logging Middleware (+21 more)

### Community 27 - "map_tiles.py"
Cohesion: 0.09
Nodes (10): _build_providers(), _configured_provider(), _disk_path(), _disk_read(), _disk_write(), _fetch_tile(), map_tile_proxy(), _placeholder_tile() (+2 more)

### Community 28 - "2. Platform Navigation and Main Pages"
Cohesion: 0.07
Nodes (27): 1. Platform Overview and Mission, 2.10 AgroAI Assistant (`/assistant/` & Floating Widget), 2.11 User Accounts & Admin Panel (`/login/`, `/admin-panel/`), 2.1 Landing Page (`/`), 2.2 Interactive Drought Dashboard (`/dashboard/`), 2.3 Prediction & Climate Forecasting Engine (`/analysis/spei-outlook/`), 2.4 Adaptive Planting Window Calendar (`/calendar/`), 2.5 Calculations & Scientific Formulas (`/analysis/calculations/`) (+19 more)

### Community 30 - "Implementation Summary - Agricultural Metrics Dashboard"
Cohesion: 0.07
Nodes (26): 1. Database Models (7 new models), 2. Forms (7 comprehensive forms), 3. Views (23 new views), 4. Templates (5 new templates), 5. URL Routing, 6. Navigation & Navbar, 7. Dependencies, 8. Settings Configuration (+18 more)

### Community 31 - "require_http_methods"
Cohesion: 0.09
Nodes (13): api_submit_metrics(), delete_all_metrics(), delete_metric_table(), _haversine_distance(), _is_subadmin_user(), _is_viewer_user(), resolve_region_api(), sensor_delete_api() (+5 more)

### Community 32 - "numpy"
Cohesion: 0.07
Nodes (28): add_indices(), _add_months(), basin_geojson_path(), _class(), design(), _driver_group(), _event_scores(), features_for() (+20 more)

### Community 33 - "test_assistant_brain.py"
Cohesion: 0.13
Nodes (6): classify_intent(), prewarm_answers(), suggestions(), get_assistant_answer(), prewarm_answers(), suggestions()

### Community 35 - "============================================================================"
Cohesion: 0.08
Nodes (24): ============================================================================, ============================================================================, ABCDryBASiN Database Quick Reference Card, ADDITIONAL RESOURCES, Backup Failed, Backup Operations, Connect to Database, CRITICAL INFORMATION (+16 more)

### Community 36 - "leaflet.js"
Cohesion: 0.09
Nodes (6): a(), Ci(), He(), Ki(), l(), x()

### Community 38 - "dashboard_view"
Cohesion: 0.12
Nodes (14): _calculate_risk(), chart_data_api(), _chart_months(), _chart_series(), _dashboard_js_i18n(), dashboard_view(), _lakes_by_region(), _month_labels() (+6 more)

### Community 39 - "a"
Cohesion: 0.15
Nodes (21): a(), as(), bn(), Br(), en(), es(), gs(), Ko() (+13 more)

### Community 40 - "datetime"
Cohesion: 0.13
Nodes (8): crop_calendar(), crop_plan(), default_sowing_date(), _next_month_date(), weather_alerts(), _weather_flags(), farm_weather(), CropManagementTests

### Community 41 - "assistant_nlu.py"
Cohesion: 0.06
Nodes (23): clarification(), classify_intent(), conversation_state(), history_mentions_region(), is_followup(), keyword_score(), _keyword_table(), match_crop() (+15 more)

### Community 42 - "ajax_upload_file"
Cohesion: 0.13
Nodes (11): ajax_upload_file(), _batch_calculate_spi(), _import_agricultural_metrics(), _import_climate_metrics(), _build_record(), _safe_val(), _import_drought_indices(), import_excel_metrics() (+3 more)

### Community 43 - "tasks.py"
Cohesion: 0.21
Nodes (5): generate_daily_risk_assessments(), pull_satellite_and_retrain(), refresh_materialized_views(), update_station_climate(), validate_spi_forecast()

### Community 44 - "_deny_data_access"
Cohesion: 0.15
Nodes (10): add_agricultural_metrics(), add_climate_metrics(), add_drought_indices(), add_hydrology_metrics(), add_remote_sensing_metrics(), add_soil_metrics(), _check_data_permission(), delete_metric_entry() (+2 more)

### Community 45 - "spei_outlook_weather.js"
Cohesion: 0.28
Nodes (18): buildDailyStrip(), buildPrecipChart(), buildPrecipTable(), buildTempChart(), buildTempHeatmap(), clearWeatherViews(), fmt(), hasValues() (+10 more)

### Community 46 - "sentinel_tiles.py"
Cohesion: 0.10
Nodes (26): f(), basin_outline(), _build(), _day_dir(), day_meta(), cached(), _drop_old_days(), _drought_class() (+18 more)

### Community 47 - "verify_spei_forecasts.py"
Cohesion: 0.11
Nodes (9): Command, _month_end(), _observed_spei(), SpeiForecast, Meta, SpeiVerification, Meta, _level_from_score() (+1 more)

### Community 48 - "je"
Cohesion: 0.25
Nodes (17): je(), a(), b(), c(), d(), E(), f(), g() (+9 more)

### Community 49 - "TestCase"
Cohesion: 0.15
Nodes (3): AssistantClarificationTests, DashboardChartFallbackTests, WeatherForecastApiTests

### Community 50 - "Comprehensive Agronomic & Drought Management Field Guide"
Cohesion: 0.12
Nodes (16): 1.1 Durum Wheat (*Triticum durum*) & Barley (*Hordeum vulgare*), 1.2 Olive Orchards (*Olea europaea*), 1.3 Tomatoes & Open-Field Solanaceous Vegetables (*Solanum lycopersicum*), 1.4 Citrus Orchards (*Citrus sinensis*, *Citrus clementina*), 1. Crop-Specific Irrigation & Phenological Water Demand, 2.1 Available Water Capacity (AWC), 2.2 Irrigation Trigger Thresholds (Management Allowed Depletion - MAD), 2. Soil Physics & Soil Moisture Management (+8 more)

### Community 51 - "Automated Data Gathering Setup Guide"
Cohesion: 0.08
Nodes (24): Automated Data Gathering Setup Guide, Automation Timeline (Daily), "broker connection refused", Check Scheduled Tasks, Configuration, Default Broker (In-Memory, Development Only), Disabling Automation, GEE authentication error during satellite pull (+16 more)

### Community 52 - "retrieval.py"
Cohesion: 0.24
Nodes (4): _crop_kb_chunks(), _docs_dir(), load_corpus(), _markdown_chunks()

### Community 53 - "How the Drought Risk Score Works (Simple Terms)"
Cohesion: 0.12
Nodes (15): 1. Soil moisture risk (0-100), 2. Vegetation stress penalty (0-20), 3. Drought index penalty (0-33), How the Drought Risk Score Works (Simple Terms), One-line summary of every formula, Step 1 — Gather the last 30 days of data, Step 2 — Calculate the derived values, Step 3 — Read today's numbers (+7 more)

### Community 54 - "assistant_brain.py"
Cohesion: 0.13
Nodes (14): build_facts(), _daily_climate(), _daily_rs(), _extreme(), _f(), _mean(), _requested_period(), _resolve_region() (+6 more)

### Community 55 - "SimpleTestCase"
Cohesion: 0.31
Nodes (3): ensure_soil(), FarmGeometryTests, FarmSoilLookupTests

### Community 56 - "spei_from_balance"
Cohesion: 0.16
Nodes (6): _loglogistic(), _monthly_balance(), severity_class(), spei_from_balance(), update_spei(), StationSpeiTests

### Community 57 - "t"
Cohesion: 0.16
Nodes (11): t(), ae(), s(), ge(), Re(), a(), i(), s() (+3 more)

### Community 58 - "train_xgboost_quick.py"
Cohesion: 0.17
Nodes (6): compute_partial_dependence(), main(), generate_sample_drought_data(), main(), load_and_prepare(), main()

### Community 59 - "Automated Data Gathering - QUICK START"
Cohesion: 0.15
Nodes (12): Automated Data Gathering - QUICK START, 📊 Check Task Execution, Linux/Mac, 📝 Logs, 🔍 Monitor (Optional - Flower Dashboard), 🚀 Production Setup (with Redis), ⚡ Start Automation (Right Now), 🎯 Status (+4 more)

### Community 60 - "answer_question"
Cohesion: 0.14
Nodes (7): answer_question(), apply_rules(), _clarify(), data_signature(), detect_language(), _json_safe(), _tidy()

### Community 61 - "gather"
Cohesion: 0.22
Nodes (3): context_numbers(), gather(), reset_index_cache()

### Community 62 - "DocumentIndex"
Cohesion: 0.23
Nodes (3): DocumentIndex, _embed_query(), _rag_chunks()

### Community 63 - "oi"
Cohesion: 0.18
Nodes (14): S(), hi(), Jo(), jr(), li(), nt(), oi(), B() (+6 more)

### Community 64 - "rag_config"
Cohesion: 0.27
Nodes (6): build_index(), corpus_signature(), embedding_model_installed(), get_index(), _index_dir(), rag_config()

### Community 65 - "train_lstm_quick.py"
Cohesion: 0.26
Nodes (3): DroughtLSTM, build_sequences(), main()

### Community 66 - "smartfarm.py"
Cohesion: 0.23
Nodes (8): fetch_probe(), _float_or_none(), _get(), _json(), _login(), _nearest_region(), _refresh(), SmartFarmError

### Community 67 - "_is_admin_user"
Cohesion: 0.21
Nodes (6): admin_delete_user(), admin_edit_user(), admin_panel(), _deny_admin_access(), _is_admin_user(), _user_can_access_region()

### Community 68 - "Command"
Cohesion: 0.12
Nodes (4): Command, _month_starts(), DroughtGridForecast, Meta

### Community 69 - "RetrievalIndexTests"
Cohesion: 0.20
Nodes (4): prompt_block(), sources_for(), _split_long(), RetrievalIndexTests

### Community 70 - "drought_grid_map.js"
Cohesion: 0.25
Nodes (15): cellValue(), classOf(), colorFor(), initMap(), paint(), renderBasin(), renderCell(), renderControls() (+7 more)

### Community 71 - "services"
Cohesion: 0.17
Nodes (11): generateValue, key, value, services, buildCommand, env, envVars, name (+3 more)

### Community 72 - "Jt"
Cohesion: 0.18
Nodes (12): Ae(), be(), h(), Ie(), Jt(), ke(), Le(), O() (+4 more)

### Community 73 - "g"
Cohesion: 0.26
Nodes (12): Ad(), a(), b(), i(), o(), s(), u(), w() (+4 more)

### Community 75 - "SentinelTileTests"
Cohesion: 0.10
Nodes (9): Command, basin_bounds(), lonlat_to_tile(), tile_in_basin(), value_at(), SentinelTileTests, s2_legend_api(), s2_tile() (+1 more)

### Community 76 - "mn"
Cohesion: 0.27
Nodes (11): an(), cn(), hn(), jn(), kn(), ln(), mn(), on() (+3 more)

### Community 77 - "ba"
Cohesion: 0.33
Nodes (11): ba(), da(), ea(), ga(), ia(), ma(), sa(), ta() (+3 more)

### Community 78 - "sys"
Cohesion: 0.11
Nodes (6): create_default_superuser(), DashboardConfig, Command, ensure_user_profile(), UserProfile, Meta

### Community 82 - "PHASE 2: DATABASE CREATION & CONFIGURATION"
Cohesion: 0.20
Nodes (10): 2.1 Create PostgreSQL Database & User, 2.2 Apply TimescaleDB Schema, 2.3 Enable Required PostgreSQL Extensions, 2.4 Configure PostgreSQL Performance, 2.5 Migrate Data from SQLite to PostgreSQL, 2.6 Verify Data Migration, Option A: Django dumpdata/loaddata (Simpler, for small datasets), Option B: Direct SQL Migration (Better for large datasets) (+2 more)

### Community 85 - "e"
Cohesion: 0.27
Nodes (10): c(), e(), hi(), m(), q(), Qe(), ve(), xe() (+2 more)

### Community 86 - "p"
Cohesion: 0.22
Nodes (10): De(), ei(), ii(), Je(), ni(), oi(), p(), pe() (+2 more)

### Community 87 - "farmer_views.py"
Cohesion: 0.20
Nodes (13): serialize_farm(), _apply_fields(), _can_use_farmer_space(), farm_advice_api(), farm_crop_plan_api(), farm_detail_api(), farm_weather_api(), farmer_home() (+5 more)

### Community 88 - "._fetch"
Cohesion: 0.18
Nodes (4): Command, _month_list(), fetch_cell_months(), last_complete_chirps_month()

### Community 89 - "TABLE OF CONTENTS"
Cohesion: 0.22
Nodes (8): 10. END-TO-END PREDICTION FLOW, 1. SYSTEM OVERVIEW, 9. THE LLM EXPLAINER, Agricultural Drought Risk Monitoring & Prediction System, Analysis Dashboard: The 6 Real-Time Metric Widgets, APWRS — Deep Analysis Document, TABLE OF CONTENTS, Why 6 Metric Categories?

### Community 90 - "11. APPENDIX: FORMULA REFERENCE"
Cohesion: 0.22
Nodes (9): 11. APPENDIX: FORMULA REFERENCE, Crop Evapotranspiration, Daily Water Balance, Heuristic Drought Risk (Fallback), LSTM Risk Conversion, Saxton & Rawls Pedotransfer Functions, Simplified Penman-Monteith (FAO-56), Standardized Precipitation Index (SPI) (+1 more)

### Community 91 - "2. METRIC GROUP 1: SOIL METRICS"
Cohesion: 0.22
Nodes (9): 2.1 moisture_content_percent, 2.2 sand_ratio, clay_ratio, silt_ratio, 2.3 root_zone_depth_mm, 2.4 organic_matter_percent, 2.5 infiltration_rate_mmhr, 2.6 field_capacity_percent & wilting_point_percent, 2.7 salinity_ece_dsm, 2.8 ph_level (+1 more)

### Community 92 - "F"
Cohesion: 0.28
Nodes (9): F(), G(), j(), k(), me(), Oe(), s(), Se() (+1 more)

### Community 93 - "rt"
Cohesion: 0.25
Nodes (9): ci(), fn(), ii(), ni(), Pi(), g(), rt(), Si() (+1 more)

### Community 94 - "tests.py"
Cohesion: 0.06
Nodes (20): Command, _risk_from_spi(), ObservationYear, Meta, _calc_prob_zero(), calculate_available_water_capacity(), calculate_et0(), calculate_etc() (+12 more)

### Community 95 - "climate_indices.py"
Cohesion: 0.27
Nodes (3): fetch_or_load_nao(), get_climate_data_dir(), merge_nao_features()

### Community 97 - "3. METRIC GROUP 2: CLIMATE METRICS"
Cohesion: 0.25
Nodes (8): 3.1 rainfall_mm, 3.2 seasonal_rainfall_variability, 3.3 temperature_max_c, temperature_min_c, temperature_mean_c, 3.4 relative_humidity_percent, 3.5 wind_speed_ms, 3.6 solar_radiation_mjm2day, 3.7 evapotranspiration_et0_mmday & evapotranspiration_etc_mmday, 3. METRIC GROUP 2: CLIMATE METRICS

### Community 98 - "6. METRIC GROUP 5: REMOTE SENSING METRICS"
Cohesion: 0.25
Nodes (8): 6.1 ndvi (Normalized Difference Vegetation Index), 6.2 ndwi (Normalized Difference Water Index), 6.3 land_surface_temperature_c (LST), 6.4 satellite_soil_moisture_percent, 6.5 satellite_source, 6.6 vegetation_condition_index (VCI), 6.7 evapotranspiration_sebal_mmday, 6. METRIC GROUP 5: REMOTE SENSING METRICS

### Community 99 - "============================================================================"
Cohesion: 0.25
Nodes (8): ============================================================================, Connection Issues, MAINTENANCE SCHEDULE, Performance Problems, ROLLBACK PROCEDURE, SUPPORT & REFERENCES, TimescaleDB Issues, TROUBLESHOOTING

### Community 100 - "validate_numbers"
Cohesion: 0.33
Nodes (3): allowed_numbers(), _collect_numbers(), validate_numbers()

### Community 101 - "data_digests"
Cohesion: 0.22
Nodes (6): data_digests(), _describe(), _digest_cache_key(), _month_label(), _round(), RetrievalDataDigestTests

### Community 102 - "historical_observations_api"
Cohesion: 0.17
Nodes (5): HistoricalObservationsApiTests, _generate_synthetic_historical_observations(), historical_export_excel(), historical_observations_api(), historical_view()

### Community 103 - "7. METRIC GROUP 6: HYDROLOGY METRICS"
Cohesion: 0.29
Nodes (7): 7.1 precipitation_mm & evapotranspiration_mm, 7.2 groundwater_depth_m, 7.3 runoff_mm & river_flow_m3s, 7.4 reservoir_storage_m3 & irrigation_supply_available_m3, 7.5 soil_water_deficit_index_mm, 7.6 water_balance_percent, 7. METRIC GROUP 6: HYDROLOGY METRICS

### Community 104 - "8. HOW AI PREDICTS DROUGHT"
Cohesion: 0.29
Nodes (7): 8.1 The Three-Layer Prediction Architecture, 8.2 XGBoost — The Risk Scorer, 8.3 LSTM — The Soil Moisture Forecaster, 8.4 Heuristic (Physics-Based) Fallback, 8.5 The Penman-Monteith ET0 Engine, 8.6 The Daily Water Balance, 8. HOW AI PREDICTS DROUGHT

### Community 105 - "1.1 Environment Setup"
Cohesion: 0.29
Nodes (7): 1.1 Environment Setup, 1.2 Backup Current SQLite Database, 1.3 Install Python Dependencies, Linux (Production - Ubuntu/Debian), macOS (Intel/Apple Silicon), PHASE 1: PRE-MIGRATION PREPARATION, Windows (Development)

### Community 106 - "_haversine_distance"
Cohesion: 0.17
Nodes (6): delete_all_metrics(), delete_metric_table(), resolve_region_api(), _haversine_distance(), _is_subadmin_user(), _user_can_access_region()

### Community 108 - "drought_warning"
Cohesion: 0.12
Nodes (8): _features(), _predict(), drought_flag_from_probability(), drought_probability_band(), drought_warning(), get_recommendations(), spei_to_risk(), DroughtWarningRuleTests

### Community 109 - "parse_reading"
Cohesion: 0.14
Nodes (10): _moisture(), parse_reading(), _parse_time(), _temperature(), _fake_jwt(), _sf_env(), _sf_row(), SmartFarmParsingTests (+2 more)

### Community 110 - "0025_dedupe_speiforecasts.py"
Cohesion: 0.33
Nodes (3): dedupe_speiforecasts(), Migration, noop_reverse()

### Community 111 - "dashboard/urls.py"
Cohesion: 0.06
Nodes (14): FarmerSignupForm, agricultural_metrics_view(), climate_metrics_view(), drought_indices_view(), hydrology_metrics_view(), remote_sensing_view(), soil_metrics_view(), _home_for() (+6 more)

### Community 112 - "_access_token"
Cohesion: 0.23
Nodes (4): _access_token(), credential_problem(), _jwt_payload(), SmartFarmPasswordLoginTests

### Community 113 - "5. METRIC GROUP 4: AGRICULTURAL METRICS"
Cohesion: 0.33
Nodes (6): 5.1 growth_stage & crop_coefficient_kc, 5.2 crop_water_requirement_mmday (CWR), 5.3 yield_reduction_factor, 5.4 irrigation_method, irrigation_efficiency_percent, water_applied_mm, 5.5 leaf_temperature_c & stomatal_conductance, 5. METRIC GROUP 4: AGRICULTURAL METRICS

### Community 114 - "============================================================================"
Cohesion: 0.33
Nodes (6): ============================================================================, ============================================================================, Migration Guide: SQLite → PostgreSQL + TimescaleDB + PostGIS, PostGIS for geospatial data, and PgBouncer for connection pooling., PostgreSQL 14+ database with TimescaleDB for time-series optimization,, This guide covers the complete migration from SQLite to a production-grade

### Community 115 - "PHASE 3: CONNECTION POOLING SETUP"
Cohesion: 0.33
Nodes (6): 3.1 Install and Configure PgBouncer, 3.2 Configure Django to Use PgBouncer, 3.3 Test PgBouncer Connection, Linux:, macOS:, PHASE 3: CONNECTION POOLING SETUP

### Community 116 - "django_db_models_deletion"
Cohesion: 0.10
Nodes (9): Migration, Migration, Migration, Migration, Migration, Migration, Migration, Migration (+1 more)

### Community 117 - "d"
Cohesion: 0.33
Nodes (6): at(), d(), ht(), Li(), v(), W()

### Community 118 - "json"
Cohesion: 0.16
Nodes (4): _default_region(), navbar(), analysis_results(), sensor_network_view()

### Community 120 - "4. METRIC GROUP 3: DROUGHT INDICES"
Cohesion: 0.40
Nodes (5): 4.1 spi_1month, spi_3month, spi_12month, 4.2 spei_1month, spei_3month, spei_12month, 4.3 pdsi_value, 4.4 drought_severity_class, 4. METRIC GROUP 3: DROUGHT INDICES

### Community 121 - "PHASE 4: BACKUP & RECOVERY SETUP"
Cohesion: 0.40
Nodes (5): 4.1 Install and Configure pgBackRest, 4.2 Create Backup Schedule (Crontab), 4.3 Test Backup & Recovery, Linux:, PHASE 4: BACKUP & RECOVERY SETUP

### Community 122 - "PHASE 5: DJANGO CONFIGURATION"
Cohesion: 0.40
Nodes (5): 5.1 Update Django Settings, 5.2 Create .env File, 5.3 Run Django Migrations, 5.4 Test Application, PHASE 5: DJANGO CONFIGURATION

### Community 123 - "PHASE 6: PERFORMANCE OPTIMIZATION"
Cohesion: 0.40
Nodes (5): 6.1 Create Indexes, 6.2 Analyze Database Statistics, 6.3 Monitor Slow Queries, 6.4 Setup Query Monitoring, PHASE 6: PERFORMANCE OPTIMIZATION

### Community 124 - "CURSORAGRI"
Cohesion: 0.40
Nodes (4): Common commands, CURSORAGRI, Guidelines, Project layout

### Community 127 - "i"
Cohesion: 0.50
Nodes (5): i(), Mi(), ne(), e(), zi()

### Community 129 - "middleware.py"
Cohesion: 0.14
Nodes (3): FarmerScopeMiddleware, LoginRequiredMiddleware, NoCacheHTMLMiddleware

### Community 131 - "embed_texts"
Cohesion: 0.29
Nodes (3): _embed_batch(), _embed_legacy(), embed_texts()

### Community 133 - "PHASE 7: VERIFICATION & TESTING"
Cohesion: 0.50
Nodes (4): 7.1 Migration Verification Checklist, 7.2 Performance Testing, 7.3 Disaster Recovery Drill, PHASE 7: VERIFICATION & TESTING

### Community 134 - "PHASE 8: CUTOVER & GO-LIVE"
Cohesion: 0.50
Nodes (4): 8.1 Pre-Cutover Checklist, 8.2 Cutover Steps, 8.3 Post-Cutover Monitoring, PHASE 8: CUTOVER & GO-LIVE

### Community 135 - "fallback_answer"
Cohesion: 0.17
Nodes (9): _context_lines(), _facts_for_prompt(), fallback_answer(), _headline(), _knowledge_text(), llm_answer(), _loc(), _website_guide_answer() (+1 more)

### Community 138 - "bi"
Cohesion: 0.50
Nodes (4): bi(), Pi(), Ti(), u()

### Community 139 - "Gridded drought forecast — Ichkeul basin (29 cells)"
Cohesion: 0.11
Nodes (14): GridCellClimate, Meta, monthly_spei_forecast(), 1. Target variable, 2. Data (per cell, monthly, Jan 1981 → last complete CHIRPS month), 3. Model, 4. Verification protocol, 5. How far ahead — and why it stops there (+6 more)

### Community 142 - ".handle"
Cohesion: 0.25
Nodes (3): Command, credentials(), _env()

### Community 152 - "configured"
Cohesion: 0.29
Nodes (4): configured(), missing_settings(), sync_if_stale(), sync_smartfarm_probe()

### Community 160 - "train_spei_models.py"
Cohesion: 0.11
Nodes (4): Command, _severity_class(), _year_for(), Command

### Community 164 - "resolve_model"
Cohesion: 0.40
Nodes (3): installed_models(), llm_config(), resolve_model()

### Community 167 - "analytics_views.py"
Cohesion: 0.06
Nodes (38): AgriculturalMetricsForm, Meta, ClimateMetricsForm, Meta, DroughtIndicesForm, Meta, HydrologyMetricsForm, Meta (+30 more)

### Community 169 - "Farm"
Cohesion: 0.25
Nodes (5): Farm, Meta, schedule_soil_lookup(), start(), _soil_worker()

### Community 172 - "DroughtPredictionPipeline"
Cohesion: 0.12
Nodes (3): Command, Command, DroughtPredictionPipeline

### Community 175 - "weather_forecast.py"
Cohesion: 0.19
Nodes (7): _climatology(), _condition(), _daily_humidity(), _error_payload(), fetch_region_forecast(), _monthly_normals(), _num()

### Community 176 - "fao56_et0"
Cohesion: 0.18
Nodes (5): fao56_et0(), drought_scenario(), region_climatology(), farm_advice(), _region_point()

### Community 180 - ".forecast_spi_risk"
Cohesion: 0.15
Nodes (4): build_next_days_rain(), climatological_daily_rain(), fetch_daily_rain_forecast(), ForecastSpiRiskTests

## Knowledge Gaps
- **61 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Region` connect `seasonal_validation.py` to `admin_views.py`, `models.py`, `os`, `ingestion_views.py`, `station_climate.py`, `views/__init__.py`, `farmer_service.py`, `numpy`, `experiment_spei_improvements.py`, `WeatherForecastServiceTests`, `train_spei_models.py`, `analytics_views.py`, `assistant_nlu.py`, `tasks.py`, `DroughtPredictionPipeline`, `Command`, `weather_forecast.py`, `assistant_brain.py`, `smartfarm.py`, `Command`, `Command`, `Command`, `tests.py`, `json`?**
  _High betweenness centrality (0.050) - this node is a cross-community bridge._
- **Are the 32 inferred relationships involving `Region` (e.g. with `ExcelImportForm` and `RiskSimulationForm`) actually correct?**
  _`Region` has 32 INFERRED edges - model-reasoned connections that need verification._
- **Should `turf.min.js` be split into smaller, more focused modules?**
  _Cohesion score 0.027982326951399118 - nodes in this community are weakly interconnected._
- **Why does `DataImporter` connect `.submit_form_data` to `models.py`, `ingestion_views.py`, `seasonal_validation.py`, `require_http_methods`?**
  _High betweenness centrality (0.025) - this node is a cross-community bridge._
- **Should `admin_views.py` be split into smaller, more focused modules?**
  _Cohesion score 0.09803921568627451 - nodes in this community are weakly interconnected._
- **Why does `DroughtPredictionPipeline` connect `DroughtPredictionPipeline` to `._collapse_to_daily`, `models.py`, `_score_from_spei`, `LSTMDroughtForecaster`, `views/__init__.py`, `tasks.py`, `Command`, `DroughtLLMExplainer`, `.forecast_spi_risk`, `drought_prediction_api`, `analysis_export_csv`, `tests.py`, `Command`?**
  _High betweenness centrality (0.025) - this node is a cross-community bridge._
- **Should `models.py` be split into smaller, more focused modules?**
  _Cohesion score 0.07199529826623567 - nodes in this community are weakly interconnected._