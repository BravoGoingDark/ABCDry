# Agricultural Metrics Dashboard - Implementation Guide

## Overview

This document describes the comprehensive agricultural metrics system that has been integrated into the Ichkeul Ag-Intel dashboard. The system tracks soil, climate, crop, remote sensing, and hydrology data across regions and time periods.

## Features

### 1. Soil Metrics 🌍
Track comprehensive soil characteristics:
- **Moisture Content**: Volumetric water content (%)
- **Texture & Structure**: Sand, clay, silt ratios
- **Root Zone Capacity**: Available water depth (mm)
- **Organic Matter**: Soil carbon content (%)
- **Infiltration Rate**: Water absorption speed (mm/hr)
- **Water Thresholds**: Field capacity and wilting point
- **Salinity & pH**: Electrical conductivity and pH levels

### 2. Climate Metrics ☀️
Monitor weather and atmospheric conditions:
- **Rainfall**: Amount and seasonal variability (mm)
- **Temperature**: Daily max, min, mean (°C)
- **Humidity**: Relative humidity (%)
- **Wind**: Wind speed at 2m height (m/s)
- **Solar Radiation**: Net radiation (MJ/m²/day)
- **Evapotranspiration**: Reference ET₀ and crop ET (mm/day)

### 3. Drought Indices 💧
Track drought severity and risk:
- **SPI**: Standardized Precipitation Index (1, 3, 12 months)
- **SPEI**: Precipitation-Evapotranspiration Index
- **PDSI**: Palmer Drought Severity Index
- **Drought Classification**: None, Abnormally Dry, Moderate, Severe, Extreme

### 4. Agricultural Metrics 🌱
Monitor crop performance and water management:
- **Crop Type & Growth Stage**: Germination through maturity
- **Crop Coefficient (Kc)**: Water requirement factor
- **Crop Water Requirement (CWR)**: Daily water need (mm)
- **Yield Reduction Factors**: Sensitivity to water stress
- **Irrigation Details**: Method and efficiency
- **Plant Stress Indicators**: Leaf temperature and stomatal conductance

### 5. Remote Sensing Metrics 🛰️
Integrate satellite-derived data:
- **NDVI**: Normalized Difference Vegetation Index (vegetation health)
- **NDWI**: Normalized Difference Water Index
- **Land Surface Temperature (LST)**: Crop heat stress
- **Satellite Soil Moisture**: From SMAP, Sentinel-1, etc.
- **Vegetation Condition Index (VCI)**: Compare to historical norms
- **Evapotranspiration (SEBAL/METRIC)**: Energy balance ET

### 6. Hydrology Metrics 💧
Monitor water resources:
- **Precipitation vs Evapotranspiration**: Water balance
- **Groundwater Levels**: Depth (m)
- **Runoff & River Flow**: Surface water (mm, m³/s)
- **Reservoir Storage**: Available irrigation supply (m³)
- **Soil Water Deficit Index**: Supply-demand difference
- **Water Balance Percent**: Overall availability

## Database Schema

### Core Models

```
Region
├── SoilMetrics
├── ClimateMetrics
├── DroughtIndices
├── RemoteSensingMetrics
└── HydrologyMetrics

Crop
├── AgriculturalMetrics
└── RiskAssessment

DataImportLog (tracks all data imports)
```

## API Endpoints

### View Metrics
- `GET /metrics/` - Metrics dashboard
- `GET /metrics/soil/` - Soil metrics list
- `GET /metrics/climate/` - Climate metrics list
- `GET /metrics/drought/` - Drought indices list
- `GET /metrics/agricultural/` - Agricultural metrics list
- `GET /metrics/remote-sensing/` - Remote sensing metrics
- `GET /metrics/hydrology/` - Hydrology metrics

### Add Metrics
- `GET/POST /metrics/soil/add/` - Add soil metrics
- `GET/POST /metrics/climate/add/` - Add climate metrics
- `GET/POST /metrics/drought/add/` - Add drought indices
- `GET/POST /metrics/agricultural/add/` - Add agricultural metrics
- `GET/POST /metrics/remote-sensing/add/` - Add remote sensing metrics
- `GET/POST /metrics/hydrology/add/` - Add hydrology metrics

### Data Management
- `GET/POST /metrics/import/excel/` - Import from Excel
- `GET /metrics/export/<type>/` - Export to Excel
- `GET /metrics/import-logs/` - View import history

## Data Import/Export

### Excel Import

1. **Navigate to**: Metrics Dashboard → Data Management → Import Excel
2. **Select File**: Choose properly formatted Excel file
3. **Select Type**: Choose metric type to import
4. **Verify**: Review mapping and any warnings
5. **Import**: Confirm and import data

### Excel Export

1. **Navigate to**: Any metrics list view
2. **Click**: Export button
3. **Format**: Downloads .xlsx file with all records
4. **Fields**: All model fields included

### Template Columns

Each metric type has specific required columns:

**Soil Metrics**:
- region, year, moisture_content_percent, sand_ratio, clay_ratio, silt_ratio, root_zone_depth_mm, organic_matter_percent, infiltration_rate_mmhr, field_capacity_percent, wilting_point_percent, salinity_ece_dsm, ph_level

**Climate Metrics**:
- region, year, measurement_date, rainfall_mm, seasonal_rainfall_variability, temperature_max_c, temperature_min_c, temperature_mean_c, relative_humidity_percent, wind_speed_ms, solar_radiation_mjm2day, evapotranspiration_et0_mmday, evapotranspiration_etc_mmday

**Drought Indices**:
- region, year, measurement_date, spi_1month, spi_3month, spi_12month, spei_1month, spei_3month, spei_12month, pdsi_value, drought_severity_class

## User Interface

### Navigation
- **Navbar**: Top navigation with metrics menu and data management options
- **Metrics Dashboard**: Overview of all metric types with quick stats
- **Metrics Lists**: Filterable, searchable views of each metric type
- **Data Entry Forms**: User-friendly forms for manual data input
- **Import Interface**: Drag-and-drop Excel file upload
- **Import Logs**: Track all data imports with status and records

### Filtering
- Filter by region across most views
- Filter by crop type in agricultural metrics
- Filter by date range in time-series metrics
- Search functionality for text fields

## Configuration

### Environment Variables

Add to `.env` file:

```env
# Database - PostgreSQL with PostGIS (recommended)
DB_ENGINE=django.contrib.gis.db.backends.postgis
DB_NAME=agri_dashboard
DB_USER=agri_user
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432

# Or keep SQLite for development
DB_ENGINE=django.db.backends.sqlite3
DB_NAME=db.sqlite3
```

### Settings Configuration

Database configuration in `agri_dashboard/settings.py`:
- Automatic selection between SQLite and PostgreSQL
- PostGIS support for geospatial queries
- REST Framework configured for API endpoints
- CORS enabled for cross-origin requests
- File upload limits increased to 50MB

## Installation Steps

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Create Migrations**:
   ```bash
   python manage.py makemigrations
   ```

3. **Apply Migrations**:
   ```bash
   python manage.py migrate
   ```

4. **Create Admin User**:
   ```bash
   python manage.py createsuperuser
   ```

5. **Run Development Server**:
   ```bash
   python manage.py runserver
   ```

6. **Access Dashboard**:
   - Main: http://localhost:8000/
   - Metrics: http://localhost:8000/metrics/
   - Admin: http://localhost:8000/admin/

## Data Entry Workflow

### Manual Entry
1. Go to desired metrics page
2. Click "Add [Metric Type]"
3. Fill in form fields
4. Select region and year
5. Verify data
6. Save

### Bulk Import
1. Prepare Excel file with data
2. Go to Metrics → Import Excel
3. Select file and metric type
4. Review import preview
5. Confirm import
6. Check Import Logs for results

## Performance Optimization

- **Database Indexes**: Automatically created on region, date, and type fields
- **Query Optimization**: Select_related used for foreign key lookups
- **Caching**: Django cache framework enabled
- **Pagination**: 50 records per page by default
- **File Size Limits**: 10MB for individual imports, 50MB for bulk

## Security Considerations

- **Authentication**: All data entry requires user login
- **CSRF Protection**: Enabled on all forms
- **SQL Injection**: Protected via ORM
- **File Upload Validation**: Excel format and size validation
- **Field Validation**: All model fields validated
- **Error Handling**: Graceful error messages without exposing internal details

## Troubleshooting

### Common Issues

1. **"Region does not exist" during import**
   - Ensure region name matches exactly (case-sensitive)
   - Add regions first via Admin panel

2. **"Year does not exist" during import**
   - Add year to ObservationYear model first

3. **Upload size limit exceeded**
   - Check FILE_UPLOAD_MAX_MEMORY_SIZE in settings
   - Split large files into multiple uploads

4. **PostgreSQL connection error**
   - Verify PostgreSQL is running
   - Check credentials in .env file
   - Ensure port 5432 is accessible

5. **PostGIS extension not found**
   - Install PostGIS extension: CREATE EXTENSION PostGIS;
   - Verify PostGIS installation

## Future Enhancements

- Real-time data streaming from IoT sensors
- Advanced analytics and trend analysis
- Predictive models for crop yield
- Integration with satellite imagery APIs
- Mobile app for field data collection
- GIS visualization layer
- Weather forecasting integration
- Multi-language support expansion

## Support

For issues or questions:
1. Check DATABASE_SETUP.md for database configuration
2. Review Django and PostgreSQL documentation
3. Check application logs in logs/django.log
4. Review import logs in admin panel

## References

- [Django GIS Documentation](https://docs.djangoproject.com/en/4.2/ref/contrib/gis/)
- [PostGIS Documentation](https://postgis.net/documentation/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [REST Framework Documentation](https://www.django-rest-framework.org/)
