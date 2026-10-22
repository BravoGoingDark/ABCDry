# APWRS / ABCDry Platform & Website User Guide

## 1. Platform Overview and Mission

The **APWRS** (Agricultural Production & Water Resource System), also known as the **ABCDry** (Agricultural Basin Climate Drought Risk and Yield Platform), is an advanced, science-grounded drought monitoring, climate forecasting, and agricultural decision support system designed specifically for Mediterranean agricultural basins, centered on Tunisia (including regions such as Ichkeul, Medjerda, Siliana, Kairouan, Cap Bon, Zaghouan, Bizerte, Jendouba, and Beja).

The platform bridges satellite remote sensing, ground weather stations, machine learning forecasting, and agronomic knowledge to help farmers, agronomists, water basin managers, and policymakers anticipate water stress, optimize irrigation, and prevent crop failure.

---

## 2. Platform Navigation and Main Pages

### 2.1 Landing Page (`/`)
* **URL**: `/`
* **Purpose**: Welcomes visitors with an executive summary of the APWRS platform, key real-time indicators, platform capabilities, and quick access buttons to sign in or explore the live dashboard.

### 2.2 Interactive Drought Dashboard (`/dashboard/`)
* **URL**: `/dashboard/`
* **Core Features**:
  1. **Interactive Leaflet Basin Map**: Displays Tunisian agricultural basins and regions with color-coded risk markers:
     - **Green (Normal Risk, score 0–25)**: Favorable hydrologic balance.
     - **Yellow (Moderate Risk, score 26–50)**: Mild deficit; monitor irrigation closely.
     - **Orange (Severe Risk, score 51–75)**: High water deficit; prepare drought contingency.
     - **Red (Extreme Risk, score 76–100)**: Severe drought emergency; mandatory water rationing.
  2. **Live Weather & Climate Dials**: Displays 30-day cumulative precipitation, reference evapotranspiration ($ET_0$), temperature (mean, min, max), humidity, wind speed, and solar radiation.
  3. **Composite Drought Risk Score Gauge**: A prominent 0–100 risk dial with current drought classification and trend.
  4. **Region Selector**: Allows instant switching between different agricultural regions.
  5. **Floating AgroAI Assistant**: Available in the bottom-right corner across all pages for conversational answers in English, French, or Arabic.

### 2.3 SPEI Outlook & ML Drought Forecasting (`/analysis/spei-outlook/`)
* **URL**: `/analysis/spei-outlook/`
* **Core Features**:
  1. **Multi-Month Forecast Horizon**: Provides forward-looking predictions from T+1 up to T+6 months.
  2. **Multi-Scale SPEI Curves**: Compares SPEI-1 (meteorological drought), SPEI-3 (agricultural drought), SPEI-6, SPEI-12 (hydrological drought), and SPEI-24 (deep groundwater drought).
  3. **Next-Month Drought Probability**: Machine learning estimated probability of entering or remaining in drought next month.
  4. **Driver Importance Analysis**: Highlights top predictive factors driving risk (e.g., rainfall deficit, 30-day temperature anomalies, SPEI lag-1/lag-2, relative humidity).
  5. **Machine Learning Algorithms**: Combines Random Forest, LightGBM, and XGBoost ensemble regressors trained on 30 years of historical climate and hydrological data.

### 2.4 Historical Climate Trends (`/historical/`)
* **URL**: `/historical/`
* **Core Features**:
  1. **30-Year Climatological Baselines**: Continuous records from 1996 to the present day.
  2. **Precipitation Anomalies & Deficits**: Graphical comparison between actual monthly rainfall and 30-year normal rainfall.
  3. **Historical Drought Chronology**: Multi-year heatmaps and timelines showing past drought episodes.

### 2.5 Calculations & Scientific Formulas (`/analysis/calculations/`)
* **URL**: `/analysis/calculations/`
* **Core Features**:
  1. **Reference Evapotranspiration ($ET_0$)**:
     - *Hargreaves-Samani method*: $ET_0 = 0.0023 \cdot R_a \cdot (T_{mean} + 17.8) \cdot \sqrt{T_{max} - T_{min}}$
     - *FAO-56 Penman-Monteith method*: Combines net radiation, soil heat flux, air temperature, wind speed, and vapor pressure deficit.
  2. **Climatic Water Balance**: $D = P - ET_0$ (monthly precipitation minus reference evapotranspiration).
  3. **SPEI Calculation Pipeline**: Fits a 3-parameter log-logistic probability distribution to accumulated water balance series $D$, transformed to standard normal distribution $Z \sim \mathcal{N}(0, 1)$.
  4. **Interactive Formula Explorer**: Explains how every index on the dashboard is mathematically derived.

### 2.6 Analysis Results & Data Export (`/analysis/`)
* **URL**: `/analysis/`
* **Core Features**:
  1. **Multi-Temporal Synthesis**: Detailed breakdown of regional moisture, drought severity, and crop suitability.
  2. **CSV Export (`/api/analysis-export/`)**: Download complete analysis data as a `.csv` file.
  3. **Excel Historical Export (`/api/historical-export/`)**: Download multi-year climate and drought indices in formatted `.xlsx` spreadsheets.
  4. **Executive PDF Reports**: Generates downloadable PDF summaries with figures and risk maps.

### 2.7 Data Ingestion Pipeline (`/data-ingestion/`)
* **URL**: `/data-ingestion/`
* **Core Features**:
  1. **Time-Series File Upload**: Drag-and-drop or click to upload meteorological or soil datasets in Excel (`.xlsx`) or `.csv` format.
  2. **Automated Pipeline**: Performs header normalization, date parsing, duplicate row detection, and database ingestion automatically.
  3. **Template Downloads**: Download pre-formatted sample Excel templates for each metric type.
  4. **Import Logs**: View processing status, successfully imported rows, and validation warnings.
  5. **Manual Parameter Entry (`/parameters/`)**: Form for entering single-day or single-station observations directly.

### 2.8 Metrics Browser & Management (`/metrics/browser/`)
* **URL**: `/metrics/browser/`
* **Dedicated Metric Portals**:
  1. **Soil Metrics (`/metrics/soil/`)**: Soil moisture (%), pH, nitrogen, phosphorus, potassium, organic matter.
  2. **Climate Metrics (`/metrics/climate/`)**: Precipitation, $ET_0$, temperature (mean, min, max), humidity, wind, solar radiation.
  3. **Drought Indices (`/metrics/drought/`)**: SPEI-1, SPEI-3, SPEI-6, SPEI-12, SPEI-24, SPI, PDSI, severity class.
  4. **Agricultural Metrics (`/metrics/agricultural/`)**: Crop types, planted area, crop stage, irrigation volume, expected yield.
  5. **Remote Sensing (`/metrics/remote-sensing/`)**: NDVI (vegetation index), NDWI (water index), VCI (vegetation condition index), Land Surface Temperature (LST), SEBAL actual evapotranspiration.
  6. **Hydrology Metrics (`/metrics/hydrology/`)**: River discharge, groundwater table depth, reservoir capacity, dam storage percentage.
* **Management Operations**:
  - **Add Entry**: Click the `+ Add [Metric]` button on any metric page (e.g., `/metrics/climate/add/`).
  - **Edit Entry**: Click the `Edit` icon on any row (e.g., `/metrics/climate/<id>/edit/`).
  - **Delete Entry**: Click the `Delete` button to remove invalid records.
  - **Bulk Export**: Click `Export to Excel` on any metric table to download the full table.

### 2.9 IoT Sensor Network (`/api/sensors/`)
* **URL**: `/api/sensors/`
* **Core Features**:
  1. **Sensor Inventory**: View active ground sensors, coordinates, status, and battery levels.
  2. **Telemetry Ingestion API (`/api/ingest/`)**: Automated REST endpoint for IoT telemetry loggers (LoRaWAN, 4G, Campbell Scientific).
  3. **Sensor History**: View time-series plots of temperature, soil moisture, and rainfall recorded by individual sensors.

### 2.10 AgroAI Assistant (`/assistant/` & Floating Widget)
* **URL**: `/assistant/` (full page) or the floating chat bubble on any page.
* **Capabilities**:
  1. **Website & Navigation Help**: Explains how to use the website, where features are located, how to upload/export data, and how formulas work.
  2. **Agronomic Advice**: Answers irrigation, crop selection, soil moisture, and drought outlook questions grounded in live database measurements.
  3. **Trilingual Support**: Speaks English, French, and Arabic seamlessly with automatic language detection.
  4. **Voice Mode**: Click the microphone icon to speak questions directly.

### 2.11 User Accounts & Admin Panel (`/login/`, `/admin-panel/`)
* **URL**: `/login/`, `/admin-panel/`
* **Capabilities**: User authentication, role-based access control (Farmer, Agronomist, Manager, Administrator), and user account management.

---

## 3. Key Concepts, Indices, and Terminology

### 3.1 SPEI (Standardized Precipitation Evapotranspiration Index)
* **Definition**: A multi-scalar drought index that accounts for both precipitation (water supply) and temperature-driven evapotranspiration (water demand).
* **Timescales**:
  - `SPEI-1` (1 month): Immediate meteorological moisture anomaly.
  - `SPEI-3` (3 months): Crucial for seasonal agriculture and crop growth stages.
  - `SPEI-6` (6 months): Medium-term reservoir and soil water deficit.
  - `SPEI-12` (12 months): Annual hydrological balance and streamflow trends.
  - `SPEI-24` (24 months): Multi-year deep aquifer recharge status.
* **Classification Scale**:
  - $\ge +2.0$: Extremely wet
  - $+1.5 \text{ to } +1.99$: Very wet
  - $+1.0 \text{ to } +1.49$: Moderately wet
  - $-0.99 \text{ to } +0.99$: Near normal
  - $-1.00 \text{ to } -1.49$: Moderate drought
  - $-1.50 \text{ to } -1.99$: Severe drought
  - $\le -2.00$: Extreme drought

### 3.2 Drought Risk Score (0–100)
* **0 to 25 (Normal)**: Sufficient soil moisture and water balance; normal irrigation schedules.
* **26 to 50 (Moderate)**: Developing soil moisture deficit; reduce non-critical irrigation and monitor closely.
* **51 to 75 (Severe)**: Pronounced hydrological stress; apply deficit irrigation strategies and protect sensitive crops.
* **76 to 100 (Extreme)**: Critical drought emergency; water allocation must be strictly rationed.

### 3.3 Satellite Remote Sensing Metrics
* **NDVI (Normalized Difference Vegetation Index)**: Measures photosynthetic greenness (values 0.2–0.8 in agricultural areas).
* **VCI (Vegetation Condition Index)**: Compares current NDVI to multi-year historical minimum and maximum for the same calendar month ($0–100\%$). Values below 35% indicate vegetative drought.
* **Soil Moisture (%)**: Volumetric soil water content in the top 5–20 cm.
* **LST (Land Surface Temperature)**: Thermal infrared radiometer measurements in °C. Elevated LST combined with low NDVI indicates plant canopy thermal stress.

---

## 4. Frequently Asked Questions (FAQ) & How-To Guides

### Q1: How do I check the drought risk for my region?
* Go to the **Interactive Dashboard** (`/dashboard/`).
* Select your region from the top region dropdown (e.g., Ichkeul, Medjerda, Kairouan).
* The dashboard immediately updates the Leaflet map, current Risk Score gauge (0–100), weather indicators, and 30-day water deficit.

### Q2: How do I view forward-looking drought forecasts?
* Click on **SPEI Outlook** in the navigation bar or visit `/analysis/spei-outlook/`.
* You will see the machine learning predictions for the upcoming months (T+1 to T+6), the probability percentage of drought, and the primary driving climate factors.

### Q3: How do I upload an Excel or CSV file of weather or soil measurements?
* Navigate to **Data Ingestion** (`/data-ingestion/`).
* Scroll to the upload section and drag your `.xlsx` or `.csv` file into the upload zone, or click to browse.
* The system automatically parses headers, runs validation rules, logs any errors, and imports valid rows.
* You can download blank templates from the same page to ensure your file matches the expected column layout.

### Q4: How do I export platform data to Excel or CSV?
* **For Analysis Reports**: Go to **Analysis** (`/analysis/`) and click **Export CSV** (`/api/analysis-export/`) or **Export Excel** (`/api/historical-export/`).
* **For Raw Metric Tables**: Go to **Metrics Browser** (`/metrics/browser/`), select any category (Soil, Climate, Drought, etc.), and click **Export to Excel**.

### Q5: How do I add or edit individual metric entries?
* Visit the **Metrics Browser** (`/metrics/browser/`).
* Choose the relevant category (e.g., `/metrics/climate/`).
* Click `+ Add Climate Metric` to input a new observation.
* To edit an existing record, locate the row and click the `Edit` button.

### Q6: How do I use the AgroAI Assistant?
* Click the chat bubble in the bottom right corner of any page, or visit the full assistant page at `/assistant/`.
* Type any question in English, French, or Arabic.
* You can ask about:
  - **The website**: "How do I upload data?", "Where is the SPEI outlook?", "What does Risk Score mean?"
  - **Agronomy & Drought**: "What is the drought outlook for Ichkeul?", "When should I irrigate wheat?", "How can I reduce water usage?"
* Click the language toggle button (EN / FR / AR) to switch display languages, or click the microphone button for voice questions.

### Q7: What datasets does APWRS use?
* **Precipitation**: CHIRPS (Climate Hazards Group InfraRed Precipitation with Station data) high-resolution 0.05° gridded daily rainfall.
* **Atmospheric Variables**: ECMWF ERA5 reanalysis for temperature, wind, humidity, and solar radiation.
* **Satellite Remote Sensing**: Google Earth Engine (MODIS and Sentinel-2) for NDVI, VCI, and Land Surface Temperature.
* **Ground Stations & IoT**: Local weather stations and deployed telemetry field sensors.
