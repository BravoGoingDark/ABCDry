# Agricultural Metrics Dashboard - Quick Start Guide

## ✅ Installation Completed

Your agricultural metrics dashboard has been successfully expanded with comprehensive soil, climate, crop, remote sensing, and hydrology tracking capabilities. Here's how to get started:

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Apply Database Migrations
```bash
python manage.py makemigrations dashboard
python manage.py migrate
```

### 3. Create Admin User
```bash
python manage.py createsuperuser
```

### 4. Run Development Server
```bash
python manage.py runserver
```

### 5. Access Dashboard
- **Main Dashboard**: http://localhost:8000/
- **Metrics Hub**: http://localhost:8000/metrics/
- **Admin Panel**: http://localhost:8000/admin/

## 📊 Available Metrics

### 1. **Soil Metrics** 🌍
- Moisture content (volumetric %)
- Texture & structure (sand/clay/silt ratios)
- Root zone depth & capacity
- Organic matter content
- Infiltration rate
- Field capacity & wilting point
- Salinity (ECe) & pH

**Access**: `http://localhost:8000/metrics/soil/`

### 2. **Climate Metrics** ☀️
- Rainfall amount & variability
- Temperature (max/min/mean)
- Humidity
- Wind speed
- Solar radiation
- Evapotranspiration (ET₀ & ETc)

**Access**: `http://localhost:8000/metrics/climate/`

### 3. **Drought Indices** 💧
- SPI (Standardized Precipitation Index)
- SPEI (Precipitation-Evapotranspiration Index)
- PDSI (Palmer Drought Severity Index)
- Drought severity classification

**Access**: `http://localhost:8000/metrics/drought/`

### 4. **Agricultural Metrics** 🌱
- Crop type & growth stage
- Crop coefficient (Kc)
- Crop water requirement
- Yield reduction factors
- Irrigation methods & efficiency
- Plant stress indicators

**Access**: `http://localhost:8000/metrics/agricultural/`

### 5. **Remote Sensing Metrics** 🛰️
- NDVI (vegetation health)
- NDWI (water content)
- Land surface temperature
- Satellite soil moisture
- Vegetation condition index

**Access**: `http://localhost:8000/metrics/remote_sensing/`

### 6. **Hydrology Metrics** 💧
- Precipitation vs evapotranspiration
- Groundwater levels
- Runoff & river flow
- Reservoir storage
- Soil water deficit index
- Water balance percent

**Access**: `http://localhost:8000/metrics/hydrology/`

## 📈 Data Entry Methods

### Manual Entry
1. Navigate to desired metrics page
2. Click "Add [Metric Type]" button
3. Fill in the form with data
4. Select region and year
5. Click "Save Metrics"

### Excel Import
1. Go to: Metrics Dashboard → Data Management → Import Excel
2. Upload prepared Excel file
3. Select metric type
4. Click "Import Data"
5. View results in Import Logs

### Filtering & Search
- Filter by region across all views
- Filter by crop type in agricultural metrics
- Search functionality available on metric lists

## 📁 File Structure

```
CURSORAGRI - Copy/
├── dashboard/
│   ├── models.py                 # All metric models
│   ├── views.py                  # Metrics views & Excel handling
│   ├── forms.py                  # Data entry forms
│   ├── urls.py                   # URL routing
│   ├── admin.py
│   └── migrations/
├── Templates/
│   ├── base.html                 # Main template with navbar
│   └── dashboard/
│       ├── metrics_dashboard.html # Hub overview
│       ├── metrics_list.html      # Metric lists
│       ├── metrics_form.html      # Data entry forms
│       ├── excel_import.html      # Excel upload interface
│       └── import_logs.html       # Import history
├── agri_dashboard/
│   ├── settings.py               # Updated with PostGIS config
│   ├── urls.py
│   └── wsgi.py
├── requirements.txt              # Updated dependencies
├── DATABASE_SETUP.md             # PostgreSQL + PostGIS guide
├── METRICS_GUIDE.md              # Detailed metrics documentation
└── QUICKSTART.md                 # This file

```

## 🗄️ Database Setup

### Using SQLite (Default - Development)
No additional setup needed! Database works out of the box.

### Using PostgreSQL + PostGIS (Recommended - Production)

1. **Install PostgreSQL & PostGIS**:
   - See DATABASE_SETUP.md for detailed instructions

2. **Configure .env**:
   ```env
   DB_ENGINE=django.contrib.gis.db.backends.postgis
   DB_NAME=agri_dashboard
   DB_USER=agri_user
   DB_PASSWORD=your_password
   DB_HOST=localhost
   DB_PORT=5432
   ```

3. **Run Migrations**:
   ```bash
   python manage.py migrate
   ```

Benefits of PostgreSQL + PostGIS:
- Geospatial data support
- Better performance with large datasets
- Support for concurrent users
- Time-series data optimization
- Advanced spatial queries

## 📤 Excel Template Format

When importing data, ensure Excel files have these columns:

**Soil Metrics**:
region, year, moisture_content_percent, sand_ratio, clay_ratio, silt_ratio, root_zone_depth_mm, organic_matter_percent, infiltration_rate_mmhr, field_capacity_percent, wilting_point_percent, salinity_ece_dsm, ph_level

**Climate Metrics**:
region, year, measurement_date, rainfall_mm, temperature_max_c, temperature_min_c, temperature_mean_c, relative_humidity_percent, wind_speed_ms, solar_radiation_mjm2day, evapotranspiration_et0_mmday

**Example Values**:
- region: Tunisia, Morocco, Algeria
- year: 2024 (Current), 2023, 2022
- measurement_date: 2024-05-23
- numeric fields: 25.5, 100.0, 0.85

## 🔗 Navigation Guide

### Navbar Menus

**Metrics Dropdown**:
- View Data section with all metric types
- Add Data section for quick entry

**Data Dropdown**:
- Import Excel
- Import Logs

**Quick Action Buttons**:
- Upload icon → Direct to import page

## 🛠️ Customization

### Add New Metric Type

1. **Create Model** in `dashboard/models.py`
2. **Create Form** in `dashboard/forms.py`
3. **Create View** in `dashboard/views.py`
4. **Create Template** in `Templates/dashboard/`
5. **Update URL** in `dashboard/urls.py`
6. **Update Navbar** in `Templates/base.html`

### Modify Existing Models

```python
# In dashboard/models.py
# Edit the metric class
# Add/remove fields as needed
# Create migration: python manage.py makemigrations
# Apply: python manage.py migrate
```

## 📊 Admin Panel

Access admin at: http://localhost:8000/admin/

Manage:
- Reference data (Regions, Years, Crops, Irrigation Methods)
- View all metrics
- Monitor import logs
- User permissions

## 🔍 Monitoring & Logs

**Import Logs**: Track all data imports with:
- Import date & time
- Source (Excel, Manual, API)
- Metric type
- Records imported
- Success/Failure status
- Error details

**Django Logs**: Stored in `logs/django.log`

## 🚨 Troubleshooting

### Missing Region Error
```
Error: Region matching query does not exist
```
**Solution**: Add region in Admin panel first

### Database Connection Error
```
Error: could not connect to server
```
**Solution**: 
- Check PostgreSQL is running
- Verify credentials in .env
- See DATABASE_SETUP.md

### File Upload Limit
```
Error: File size exceeds maximum
```
**Solution**: 
- Max size is 50MB (configurable in settings.py)
- Split large files into multiple uploads

### Import Errors
- Check Excel column names match template
- Verify date format (YYYY-MM-DD)
- Ensure numeric fields contain numbers
- Check for missing required fields

## 📚 Documentation

- **DATABASE_SETUP.md**: Detailed PostgreSQL + PostGIS setup
- **METRICS_GUIDE.md**: Comprehensive metrics documentation
- **Django Docs**: https://docs.djangoproject.com/
- **PostgreSQL Docs**: https://www.postgresql.org/docs/
- **PostGIS Docs**: https://postgis.net/documentation/

## 🎯 Next Steps

1. ✅ Install dependencies: `pip install -r requirements.txt`
2. ✅ Run migrations: `python manage.py migrate`
3. ✅ Create superuser: `python manage.py createsuperuser`
4. ✅ Start server: `python manage.py runserver`
5. ✅ Access metrics dashboard at `/metrics/`
6. ✅ Begin entering or importing data

## 💡 Tips & Best Practices

1. **Use PostgreSQL for production** - Better performance and scalability
2. **Regularly backup data** - Use pg_dump for PostgreSQL
3. **Monitor import logs** - Track data quality issues
4. **Use bulk import for large datasets** - Faster than manual entry
5. **Filter data by region** - Easier navigation in reports
6. **Validate data before import** - Prevents errors and inconsistencies

## 🤝 Support

Need help?
1. Check the troubleshooting section above
2. Review DATABASE_SETUP.md for database issues
3. Check Django admin panel for data status
4. Review application logs in logs/django.log

## 📝 Sample Data Entry

To test the system:

1. Go to: http://localhost:8000/metrics/soil/add/
2. Select Region: Tunisia
3. Select Year: 2024 (Current)
4. Enter values:
   - Moisture Content: 25.5%
   - Sand Ratio: 40
   - Clay Ratio: 30
   - Silt Ratio: 30
   - Root Zone Depth: 500mm
   - Organic Matter: 2.5%
   - Infiltration Rate: 15mm/hr
   - Field Capacity: 35%
   - Wilting Point: 15%
   - Salinity: 1.5 dS/m
   - pH: 7.2
5. Click "Save Metrics"

## 🎉 Congratulations!

Your agricultural metrics dashboard is now ready to track comprehensive soil, climate, and crop data for sustainable agriculture management!

For detailed metrics definitions and use cases, see **METRICS_GUIDE.md**.
