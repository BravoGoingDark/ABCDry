# Data Ingestion Implementation Guide

## 🎯 Overview

The data ingestion page in ABCDryBASiN allows you to load agricultural metrics into the PostgreSQL database through:
- **Excel/CSV Upload** - Batch import from files
- **Manual Entry** - Single record entry via web form
- **Real-time Tracking** - All imports logged with user info

---

## 📊 Supported Metrics

### 1. **Soil Metrics**
- Moisture content (%)
- Sand/Clay/Silt ratios (%)
- Root zone depth (mm)
- Organic matter (%)
- Infiltration rate (mm/hr)
- Field capacity (%)
- Wilting point (%)
- Salinity (dS/m)
- pH level

**Required Fields:** `region`, `year`, `moisture_content_percent`, `root_zone_depth_mm`, `organic_matter_percent`, `infiltration_rate_mmhr`, `field_capacity_percent`, `wilting_point_percent`, `salinity_ece_dsm`, `ph_level`

---

### 2. **Climate Metrics**
- Temperature (Max, Min, Mean in °C)
- Rainfall (mm)
- Humidity (%)
- Wind speed (m/s)
- Solar radiation (MJ/m²/day)
- Evapotranspiration ET₀ & ETc (mm/day)

**Required Fields:** `region`, `year`, `measurement_date`, `temperature_max_c`, `temperature_min_c`, `temperature_mean_c`, `relative_humidity_percent`, `wind_speed_ms`, `solar_radiation_mjm2day`, `evapotranspiration_et0_mmday`

---

### 3. **Drought Indices**
- SPI (1-month, 3-month, 12-month)
- SPEI (1-month, 3-month, 12-month)
- PDSI value
- Drought severity class

**Severity Classes:** None, Abnormally Dry, Moderate Drought, Severe Drought, Extreme Drought

**Required Fields:** `region`, `year`, `measurement_date`, `drought_severity_class`

---

### 4. **Agricultural Metrics**
- Growth stage
- Crop coefficient (Kc)
- Crop water requirement (mm/day)
- Yield reduction factor
- Irrigation method & efficiency
- Water applied (mm)
- Leaf temperature (°C)
- Stomatal conductance

**Growth Stages:** Germination, Vegetative, Flowering, Grain Filling, Maturity

**Required Fields:** `region`, `year`, `crop`, `measurement_date`, `growth_stage`, `crop_coefficient_kc`, `crop_water_requirement_mmday`, `yield_reduction_factor`, `irrigation_method`, `irrigation_efficiency_percent`, `water_applied_mm`

---

### 5. **Remote Sensing Metrics**
- NDVI (vegetation health -1 to 1)
- NDWI (water content)
- Land surface temperature (°C)
- Satellite soil moisture (%)
- Vegetation condition index
- ET from SEBAL (mm/day)

**Required Fields:** `region`, `year`, `measurement_date`, `ndvi`, `satellite_source`

---

### 6. **Hydrology Metrics**
- Precipitation (mm)
- Evapotranspiration (mm)
- Groundwater depth (m)
- Runoff (mm)
- River flow (m³/s)
- Reservoir storage (m³)
- Irrigation supply (m³)
- Water balance (%)

**Required Fields:** `region`, `year`, `measurement_date`, `precipitation_mm`, `evapotranspiration_mm`, `groundwater_depth_m`, `runoff_mm`, `river_flow_m3s`

---

## 📁 Excel/CSV File Format

### Template Structure

All files should have headers matching the database column names. Use this format:

```
region,year,measurement_date,soil_metric1,soil_metric2,...
Tunisia,2024,2024-01-15,25.5,40.2,...
Morocco,2024,2024-01-16,22.3,35.8,...
```

### File Types Supported
- `.xlsx` (Excel 2007+)
- `.xls` (Excel 97-2003)
- `.csv` (comma-separated)
- `.json` (JSON arrays)

### Example CSV for Climate Metrics

```csv
region,year,measurement_date,temperature_max_c,temperature_min_c,temperature_mean_c,relative_humidity_percent,rainfall_mm,wind_speed_ms,solar_radiation_mjm2day,evapotranspiration_et0_mmday
Tunisia,2024,2024-01-15,28.5,15.2,21.9,65,2.3,3.5,18.5,4.2
Tunisia,2024,2024-01-16,29.1,16.0,22.6,62,0.0,4.1,19.2,4.5
Morocco,2024,2024-01-15,26.3,14.0,20.2,70,5.5,2.8,17.3,3.9
```

### Example for Soil Metrics

```csv
region,year,moisture_content_percent,sand_ratio,clay_ratio,silt_ratio,root_zone_depth_mm,organic_matter_percent,infiltration_rate_mmhr,field_capacity_percent,wilting_point_percent,salinity_ece_dsm,ph_level
Tunisia,2024,25.5,40.0,25.0,35.0,600,2.5,25.0,32.0,15.0,0.5,7.2
Morocco,2024,28.0,45.0,20.0,35.0,650,3.0,20.0,30.0,14.0,0.3,7.5
```

---

## 🚀 How to Use Data Ingestion

### **Method 1: Upload Excel/CSV File**

1. Go to **Data** → **Data Ingestion**
2. Scroll to "Upload Time-Series Data" section
3. Click upload area or drag-drop your Excel/CSV file
4. File is automatically validated and imported
5. Check import logs for status

### **Method 2: Manual Single Entry**

1. Go to **Data** → **Data Ingestion**
2. Select **Region**, **Year**, **Crop** (if applicable) from dropdowns
3. Set **Measurement Timestamp** using date picker
4. Enter **Latitude**, **Longitude**, **Altitude**
5. Expand metric sections:
   - **Soil Metrics** - Enter soil parameters
   - **Climate Metrics** - Enter weather data
   - **Agricultural Metrics** - Enter crop data
   - **Remote Sensing** - Enter satellite indices
   - **Hydrology** - Enter water metrics
6. Click **Submit** at bottom
7. Confirmation message appears

### **Method 3: Bulk Import (Advanced)**

```python
# Python script to import via API
import requests
import pandas as pd

df = pd.read_excel('metrics_data.xlsx')
data = df.to_dict('records')

response = requests.post(
    'http://localhost:8000/metrics/import/excel/',
    json={'records': data, 'metric_type': 'climate'}
)
print(response.json())
```

---

## 🛰️ Method 4: Google Earth Engine (Real Satellite Data)

The `pull_satellite` command pulls real free satellite/reanalysis data into the metric
tables (no Excel needed):

| Dataset | Collection | Populates |
|---------|-----------|-----------|
| CHIRPS rainfall | `UCSB-CHG/CHIRPS/DAILY` | `ClimateMetrics.rainfall_mm` |
| ERA5-Land climate | `ECMWF/ERA5_LAND/DAILY_AGGR` | Climate: Tmax/Tmin/Tmean, RH, wind, solar |
| MODIS NDVI | `MODIS/061/MOD13Q1` | `RemoteSensingMetrics.ndvi` |
| MODIS LST | `MODIS/061/MOD11A1` | `RemoteSensingMetrics.land_surface_temperature_c` |
| SMAP soil moisture | `NASA/SMAP/SPL4SMGP` | `RemoteSensingMetrics.satellite_soil_moisture_percent` |

It then recomputes SPI-1/3/12 and VCI into `DroughtIndices`.

### Step 1 — Create a Google Earth Engine service account (one-time)

1. Go to the [Google Cloud Console](https://console.cloud.google.com) and create a project
   (e.g. `abcdry-basin`).
2. In the console, enable the **Earth Engine API**:
   APIs & Services → Library → search "Earth Engine API" → Enable.
3. Sign up the project for Earth Engine:
   https://signup.earthengine.google.com → sign in → **Get started** → select your project.
4. Create a service account:
   IAM & Admin → **Service accounts** → Create service account → grant it any role
   (e.g. *Earth Engine > Viewer*).
5. Create a key for that service account: select it → **Keys** → Add key → **JSON**.
   This downloads `xxx.json`.
6. **Optional but recommended:** give that service account's email
   `projects/earthengine-legacy/roles/earthengine.viewer` on the project so it can read
   public datasets (public collections are readable by all signed-up projects, so this is
   usually unnecessary).

### Step 2 — Configure credentials

1. Move the downloaded JSON to a safe path, e.g. `C:\Users\you\keys\gee-service-account.json`.
2. Add it to `.env`:

```
GEE_CREDENTIALS_FILE=C:\Users\you\keys\gee-service-account.json
```

3. Install dependencies: `pip install earthengine-api google-auth` (already in requirements.txt).

### Step 3 — Run the pull

```bash
# Last 90 days, all regions (every 5 days)
python manage.py pull_satellite

# One region, full year, daily
python manage.py pull_satellite --region-id 8 --start-date 2025-01-01 --end-date 2025-12-31 --every 1 --verbose

# See what would happen without writing
python manage.py pull_satellite --dry-run
```

> Runs are idempotent: re-running overwrites the same (region, year, date) rows.
> SMAP has ~3-day latency, MODIS LST ~1 day, CHIRPS ~1-2 weeks — the most recent days
> may return `None` until the upstream data is published.

### Troubleshooting

- **"Earth Engine auth failed"** → the JSON path is wrong, the service account has no key,
  or the project isn't signed up for Earth Engine. Re-check Steps 1-2.
- **401 / "Not Authorized"** → confirm the Earth Engine API is enabled and the account is
  in the project's registered users.
- **Everything is `None`** → the region point may be outside the dataset's coverage, or
  the data isn't published yet for that date. Test with `--dry-run --verbose`.

### Units & sampling notes

- **SMAP soil moisture is stored as volume fraction (m³/m³, 0–0.9)**, not kg/m².
  `pull_satellite` multiplies by 100 to store percent. Rows imported before this fix
  are ~50× too small — repair them with `repair_satellite --fix-soil-moisture` below.
- **NDVI is sampled as the max over a ~3 km basin radius** (`NDVI_SAMPLE_RADIUS_M`), not
  a single point. For basins whose coordinates sit on open water (e.g. a lake inside the
  basin), a point sample returns water, not vegetation. NDVI < 0.1 (water) is written as
  `NULL` rather than a negative number.

### Repairing existing rows (`repair_satellite`)

Fixes mis-scaled/contaminated values already in the DB (idempotent, safe to re-run):

```bash
# Rescale mis-scaled SMAP soil moisture (values <= 5) by x50
python manage.py repair_satellite --region-id 4 --fix-soil-moisture

# Replace water-like NDVI (< 0.1) with NULL
python manage.py repair_satellite --region-id 4 --clear-water-ndvi

# Re-pull NDVI from GEE using the basin sampler (needs valid GEE credentials)
python manage.py repair_satellite --region-id 4 --re-pull-ndvi --start-date 2015-01-01

# Preview only, no writes
python manage.py repair_satellite --region-id 4 --fix-soil-moisture --dry-run
```

---

## ✅ Data Validation

All imports validate against database constraints:

- **Ranges**: Temperature (-50 to 60°C), Humidity (0-100%), NDVI (-1 to 1)
- **Existence**: Region, Year, Crop must exist in reference tables
- **Formats**: Dates must be YYYY-MM-DD, decimals with proper precision
- **Not Null**: Required fields cannot be empty

---

## 📊 Import Logs & Tracking

### View Import History

1. Go to **Data** → **Import Logs**
2. See all imports with:
   - Source (Excel, Manual, API)
   - Filename
   - Metric type
   - Records imported
   - Status (Success, Partial, Failed)
   - Timestamp & user

### Database Tracking

All imports are recorded in:
- `data_import_logs` - Import metadata
- `audit_logs` - Row-level change tracking
- `user_activity_log` - User actions (with login tracking)

---

## 🔧 Troubleshooting

### "File format not supported"
- Ensure file is .xlsx, .xls, or .csv
- Check file isn't corrupted

### "Column not found"
- Verify column names match database fields exactly
- Excel column headers must be lowercase with underscores

### "Region/Year not found"
- Create region/year in reference data first
- Use exact names: "Tunisia", "2024" (case-sensitive)

### "Invalid value in column X"
- Check data types (dates as YYYY-MM-DD)
- Verify numeric values are within valid ranges
- No text in numeric columns

### "Import stuck or slow"
- Large files (>10,000 rows) may take time
- Check PostgreSQL connection status
- Monitor server resources

---

## 📈 Best Practices

1. **Organize by Metric Type** - One file per metric type for better tracking
2. **Include Metadata** - Always include region, year, and timestamp
3. **Quality Check** - Remove duplicates before importing
4. **Backup First** - Export before major imports
5. **Test Small** - Try with 5-10 rows first
6. **Documentation** - Note source and measurement method

---

## 🔐 Data Security

- All imports logged with user/timestamp
- Changes tracked in audit log
- Geographic data stored (lat/long)
- No automatic deletions (only manual)
- PostgreSQL access controlled via .env

---

## 📞 Support

For import issues:
1. Check import logs for error details
2. Validate Excel file format
3. Verify reference data exists
4. Check PostgreSQL connection
5. Review audit logs for tracking

---

## 🎯 Next Steps

After importing data:
1. ✅ Run Dashboard to view metrics
2. ✅ View Analysis for trends
3. ✅ Check Historical for comparisons
4. ✅ Generate Risk Assessment

