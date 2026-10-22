# APWRS — Deep Analysis Document
## Agricultural Drought Risk Monitoring & Prediction System

---

# TABLE OF CONTENTS

1. **System Overview**
2. **Metric Group 1: Soil Metrics** — The Foundation
3. **Metric Group 2: Climate Metrics** — The Driver
4. **Metric Group 3: Drought Indices** — The Benchmark
5. **Metric Group 4: Agricultural Metrics** — The Crop Perspective
6. **Metric Group 5: Remote Sensing Metrics** — The Satellite View
7. **Metric Group 6: Hydrology Metrics** — The Water Balance
8. **How AI Predicts Drought** — XGBoost, LSTM & Heuristics
9. **The LLM Explainer**
10. **End-to-End Prediction Flow**
11. **Appendix: Formula Reference**

---

## 1. SYSTEM OVERVIEW

**APWRS** is a drought early warning system. It ingests **6 categories of environmental data** and uses **3 prediction methods** (XGBoost, LSTM neural networks, physics-based heuristics) to forecast drought risk 7 and 30 days ahead.

### Why 6 Metric Categories?

Agriculture is a multi-dimensional system. No single metric tells the full story:

| Category | What It Captures | Why It's Essential |
|----------|-----------------|-------------------|
| **Soil** | Water storage capacity & availability | The "fuel tank" for crops |
| **Climate** | Weather inputs (rain, temperature, etc.) | The "fuel pump" |
| **Drought Indices** | Standardized historical drought context | The "baseline comparison" |
| **Agricultural** | Crop-specific water demand & stress | The "engine load" |
| **Remote Sensing** | Actual vegetation health from space | The "objective measurement" |
| **Hydrology** | Overall water resources balance | The "regional water budget" |

### Analysis Dashboard: The 6 Real-Time Metric Widgets

The analysis page displays 6 real-time metric cards giving an instant snapshot of current conditions:

| Icon | Label | Source | Meaning |
|------|-------|--------|---------|
| `humidity_percentage` | **Soil Moisture** | `SoilMetrics.moisture_content_percent` | Current volumetric water content (%). 0% = bone dry, 100% = fully saturated. |
| `rainy` | **Rainfall (30d)** | `ClimateMetrics.rainfall_mm` (summed over 30 days) | Total precipitation in the last 30 days in mm. Key medium-term water supply indicator. |
| `eco` | **NDVI Index** | `RemoteSensingMetrics.ndvi` | Satellite vegetation health index (-1 to 1). Below 0.3 = stressed vegetation. |
| `air` | **ETc (Daily)** | `ClimateMetrics.evapotranspiration_etc_mmday` | Actual crop water consumption in mm/day. Formula: `ETc = ET0 × Kc`. Higher values = more water demand. |
| `waves` | **Soil Water** | Computed: `(moisture / field_capacity) × 100` | Current soil water as a % of field capacity. 100% = full, lower values = depletion. Calculated from the daily soil water balance. |
| `potted_plant` | **Crop Stress** | `AgriculturalMetrics.yield_reduction_factor` × 100 | Plant stress level (0-100%). Higher = more stress. Based on crop sensitivity to water deficit (FAO Ky values). |

These widgets are populated from the most recent data in each metric table and updated via the prediction pipeline or direct API calls.

---

## 2. METRIC GROUP 1: SOIL METRICS

### 2.1 moisture_content_percent

| Aspect | Detail |
|--------|--------|
| **Why chosen** | Direct measure of water available to plants. The single most important soil drought indicator. |
| **What it means** | Percentage of soil volume occupied by water. 0% = bone dry, 100% = fully saturated. |
| **How measured** | Gravimetric method (weigh wet soil, dry at 105°C, re-weigh) or time-domain reflectometry (TDR) sensors, or satellite microwave sensors. |
| **Effect on drought** | Below ~30% = plants begin to stress. Below ~15% = permanent wilting. |
| **Calculation** | `(weight_wet - weight_dry) / volume_soil × 100` |
| **AI usage** | Primary input for XGBoost (latest value + 7-day trend). LSTM uses it as the target variable to predict (soil moisture 7/30 days out). Heuristic: `soil_risk = (1 - moisture/field_capacity) × 100`. |

### 2.2 sand_ratio, clay_ratio, silt_ratio

| Aspect | Detail |
|--------|--------|
| **Why chosen** | Soil texture determines water holding capacity, drainage, and infiltration. Sand drains fast, clay holds water, silt is intermediate. |
| **What it means** | Percentage of each particle size in the soil. Must sum to 100%. |
| **How measured** | Hydrometer method or laser diffraction. |
| **Effect on drought** | Sandy soil = low water holding → faster drought onset. Clay soil = higher holding but slower recharge. |
| **AI usage** | Used to **calculate** field capacity & wilting point via Saxton-Rawls pedotransfer functions (see Section 11). These are then used to normalize soil moisture into risk percentages. |

### 2.3 root_zone_depth_mm

| Aspect | Detail |
|--------|--------|
| **Why chosen** | Defines the volume of soil from which plants can extract water. Deep roots access more stored water. |
| **What it means** | Depth in mm of the effective root zone (typically 300-1200mm for field crops). |
| **How measured** | Soil pit excavation, root coring, or estimation by crop type. |
| **Effect on drought** | Deeper root zone = more total available water = longer drought survival. |
| **Calculation** | `Available Water Capacity (mm) = (FC - WP) / 100 × root_zone_depth_mm` |
| **AI usage** | Determines `available_water_capacity_mm` which scales all risk calculations. |

### 2.4 organic_matter_percent

| Aspect | Detail |
|--------|--------|
| **Why chosen** | Organic matter improves water retention (can hold 20x its weight in water). |
| **What it means** | Percentage of soil mass that is decomposed plant/animal material. |
| **How measured** | Loss on ignition (burn at 550°C, measure weight loss) or Walkley-Black wet oxidation. |
| **Effect on drought** | Higher OM = better structure, more infiltration, more water storage = reduced drought impact. |
| **AI usage** | Influences field capacity calculation in Saxton-Rawls. |

### 2.5 infiltration_rate_mmhr

| Aspect | Detail |
|--------|--------|
| **Why chosen** | Determines how quickly rainwater enters the soil vs. running off. |
| **What it means** | Millimeters of water that can enter per hour. Sandy soil: 50+ mm/hr. Clay soil: 1-10 mm/hr. |
| **How measured** | Double-ring infiltrometer or rainfall simulator. |
| **Effect on drought** | Low infiltration = more runoff = less water stored for dry periods. |
| **AI usage** | Used indirectly in the water balance for runoff estimation. |

### 2.6 field_capacity_percent & wilting_point_percent

| Aspect | Detail |
|--------|--------|
| **Why chosen** | These two thresholds define the **plant-available water window**. FC = upper limit (gravity has drained), WP = lower limit (plants can no longer extract). |
| **What it means** | FC: ~30-40% for clay, ~10-15% for sand. WP: ~15-20% for clay, ~4-6% for sand. |
| **How measured** | Pressure plate apparatus, or **estimated** via Saxton-Rawls from texture: `FC = 20 + 0.3×clay + 0.1×silt - 0.05×sand` / `WP = 8 + 0.2×clay + 0.05×silt - 0.03×sand` |
| **Effect on drought** | When moisture falls below FC = stress begins. At WP = plant death. The danger zone is FC → WP. |
| **AI usage** | **Critical**: All three models normalize soil moisture against field capacity to compute risk. `risk = (1 - moisture/FC) × 100`. |

### 2.7 salinity_ece_dsm

| Aspect | Detail |
|--------|--------|
| **Why chosen** | High salinity causes "physiological drought" — water is present but plants cannot absorb it. |
| **What it means** | Electrical conductivity in deciSiemens per meter. 0-2 = normal, 2-4 = slight, 4-8 = moderate, 8+ = severe. |
| **How measured** | EC meter on soil-water slurry. |
| **Effect on drought** | Saline soils reduce effective water availability, increasing drought sensitivity. |
| **AI usage** | Secondary input. Not directly in current models but affects interpretation. |

### 2.8 ph_level

| Aspect | Detail |
|--------|--------|
| **Why chosen** | pH controls nutrient availability. Extreme pH stresses crops even with adequate water. |
| **What it means** | 1-14 scale. 6.0-7.5 = optimal for most crops. |
| **How measured** | pH meter on soil-water suspension. |
| **Effect on drought** | Indirect — stressed crops from poor pH are more vulnerable to drought impact. |
| **AI usage** | Informational secondary metric. |

---

## 3. METRIC GROUP 2: CLIMATE METRICS

### 3.1 rainfall_mm

| Aspect | Detail |
|--------|--------|
| **Why chosen** | Primary water input to the system. Without rain, drought is inevitable. |
| **What it means** | Depth of precipitation in millimeters over a 24-hour period. |
| **How measured** | Tipping-bucket rain gauge, weighing gauge, or satellite (TRMM/GPM). |
| **Effect on drought** | Direct inverse: more rain = less drought. But timing matters — 100mm in one day vs. spread over 2 weeks have very different impacts. |
| **AI usage** | **Critical**. XGBoost uses `rainfall_30d_mm` (sum over 30 days) and `rainfall_7d_mm` (sum over 7 days). Also computes `days_since_last_rain` (>1mm threshold). LSTM includes it as one of 10 input features. Heuristics use it for water balance. |

### 3.2 seasonal_rainfall_variability

| Aspect | Detail |
|--------|--------|
| **Why chosen** | Captures the distribution pattern — same total rain but different arrival timing. |
| **What it means** | Classification like "Normal", "Erratic", "Late onset", "Early cessation". |
| **How measured** | Historical comparison of rainfall timing vs. long-term averages. |
| **Effect on drought** | Late rains delay planting. Early cessation cuts short the growing season. Both cause crop water stress even if total rainfall is normal. |
| **AI usage** | Informational / metadata field. |

### 3.3 temperature_max_c, temperature_min_c, temperature_mean_c

| Aspect | Detail |
|--------|--------|
| **Why chosen** | Temperature controls evapotranspiration rate (the "thirst" of the atmosphere). Higher = more water loss. |
| **What it means** | Daily maximum, minimum, and mean air temperature in °C at 2m height. |
| **How measured** | Thermometer in a Stevenson screen (standard weather station). |
| **Effect on drought** | Higher temps = higher ET0 = faster soil drying. Daily max > 40°C causes direct heat stress on crops. |
| **AI usage** | **Critical**. XGBoost computes `temp_anomaly_c = current_temp - 30_day_avg_temp`. This captures heat waves. LSTM uses all three. Mean temp is used to calculate ET0 via Penman-Monteith. |

### 3.4 relative_humidity_percent

| Aspect | Detail |
|--------|--------|
| **Why chosen** | Humidity controls the drying power of air. Low humidity = faster evaporation. |
| **What it means** | Percentage of water vapor in air relative to saturation. 20% = very dry, 80% = humid. |
| **How measured** | Hygrometer or psychrometer (wet/dry bulb thermometer). |
| **Effect on drought** | Low humidity accelerates soil and plant water loss. Combined with high wind and temp = extreme ET. |
| **AI usage** | Input to Penman-Monteith ET0 calculation. Also an LSTM feature. |

### 3.5 wind_speed_ms

| Aspect | Detail |
|--------|--------|
| **Why chosen** | Wind removes the humid boundary layer near leaves, accelerating transpiration. |
| **What it means** | Average wind speed in meters per second at 2m height. |
| **How measured** | Anemometer at 2m or 10m standard height (then adjusted). |
| **Effect on drought** | Strong wind = more ET = faster soil drying. Especially dangerous when combined with heat. |
| **AI usage** | Input to Penman-Monteith ET0 calculation and LSTM feature. |

### 3.6 solar_radiation_mjm2day

| Aspect | Detail |
|--------|--------|
| **Why chosen** | Solar radiation is the energy source for evaporation. More sun = more water loss. |
| **What it means** | Megajoules per square meter per day. ~5-10 MJ/m²/day in winter, ~25-30 in summer. |
| **How measured** | Pyranometer (measures incoming shortwave radiation). |
| **Effect on drought** | Higher radiation = higher potential ET = faster depletion of soil moisture. |
| **AI usage** | Converted to W/m² (`SR_wm2 = SR_mjm2day / 0.0864`) and used in Penman-Monteith. Also an LSTM feature. |

### 3.7 evapotranspiration_et0_mmday & evapotranspiration_etc_mmday

| Aspect | Detail |
|--------|--------|
| **Why chosen** | ET0 is the "atmospheric demand" — how much water would evaporate from a reference grass surface. ETc is the actual crop-specific demand. |
| **What it means** | ET0: 3-7 mm/day typical. ETc: varies by crop coefficient (Kc × ET0). |
| **How measured** | **Calculated** (not directly measured): Penman-Monteith FAO-56 equation (see Section 11). Lysimeters can directly measure. |
| **Calculation** | `ET0 = (0.408 × Δ × Rn + γ × (900/(T+273)) × u2 × (es-ea)) / (Δ + γ×(1+0.34×u2))` then `ETc = ET0 × Kc` |
| **Effect on drought** | When ETc > rainfall + available soil water = deficit = drought. |
| **AI usage** | **Critical**. XGBoost uses `etc_7d_avg_mm` and `etc_30d_avg_mm` as drought drivers. High ET = high risk. LSTM includes `etc_mm` as a feature. |

---

## 4. METRIC GROUP 3: DROUGHT INDICES

### 4.1 spi_1month, spi_3month, spi_12month

| Aspect | Detail |
|--------|--------|
| **Why chosen** | SPI (Standardized Precipitation Index) is the World Meteorological Organization's recommended drought index. It compares current rainfall to historical norms at different timescales. |
| **What it means** | A unitless value from -3 to +3. Negative = dry, Positive = wet. -1 to -1.5 = Moderate drought, -1.5 to -2 = Severe, < -2 = Extreme. |
| **How calculated** | `SPI = (current_rainfall - historical_mean) / historical_std_dev` |
| **Why 3 timescales** | SPI-1 captures short-term (soil moisture), SPI-3 captures seasonal (crop stress), SPI-12 captures long-term (groundwater/reservoir). |
| **Effect on drought** | SPI < -1: agricultural drought likely. SPI < -2: severe, widespread crop failure. |
| **AI usage** | XGBoost includes SPI in its heuristic target calculation (lower SPI = higher penalty). Also used in the heuristic fallback risk formula. Auto-calculated when climate data is ingested. |

### 4.2 spei_1month, spei_3month, spei_12month

| Aspect | Detail |
|--------|--------|
| **Why chosen** | SPEI adds the effect of temperature (via ET) to SPI. Climate change makes this increasingly important — even with normal rain, higher temps = more drought. |
| **What it means** | Same scale as SPI (-3 to +3) but incorporates water demand (ET) not just supply (rainfall). |
| **How calculated** | `SPEI = (P - PET_climatic_balance - mean) / std_dev` using a log-logistic probability distribution. |
| **Effect on drought** | More sensitive to warming than SPI. Can show "drought" even with normal rainfall if temperatures are high. |
| **AI usage** | Used alongside SPI in heuristic risk calculations. Provides temperature-aware drought context. |

### 4.3 pdsi_value

| Aspect | Detail |
|--------|--------|
| **Why chosen** | Palmer Drought Severity Index incorporates soil moisture storage, runoff, and ET in a water balance model. More comprehensive than SPI. |
| **What it means** | -4 = Extreme drought, -3 = Severe, -2 = Moderate, -1 = Mild, 0 = Normal. |
| **How calculated** | Complex water balance model using P, ET, soil moisture storage, and runoff with climate coefficients calibrated to local conditions. |
| **Effect on drought** | PDSI < -3 indicates serious, prolonged drought requiring intervention. |
| **AI usage** | Included in the prediction frame as contextual data. |

### 4.4 drought_severity_class

| Aspect | Detail |
|--------|--------|
| **Why chosen** | A human-readable classification that translates numerical indices into actionable categories. |
| **What it means** | None → Abnormally Dry → Moderate → Severe → Extreme. |
| **How determined** | Based on SPI/SPEI/PDSI thresholds combined. |
| **AI usage** | Output of the system (generated by prediction). Also useful for training classification models. |

---

## 5. METRIC GROUP 4: AGRICULTURAL METRICS

### 5.1 growth_stage & crop_coefficient_kc

| Aspect | Detail |
|--------|--------|
| **Why chosen** | Water demand changes dramatically through the growing season. The same crop needs 3x more water at flowering than at germination. |
| **What it means** | Kc is a multiplier applied to ET0 to get ETc. Kc = 0.3-0.4 (initial), 1.0-1.2 (mid-season), 0.3-0.5 (late). |
| **How determined** | FAO-56 tables provide Kc curves for each crop by growth stage. Or measured by lysimeter. |
| **Effect on drought** | Mid-season (flowering/grain fill) is most sensitive to water stress. A drought during this phase causes maximum yield loss. |
| **AI usage** | Kc is used to compute ETc = ET0 × Kc, which drives the water balance model. The growth stage helps contextualize risk severity. |

### 5.2 crop_water_requirement_mmday (CWR)

| Aspect | Detail |
|--------|--------|
| **Why chosen** | The actual daily water needed by the crop to avoid stress. Direct comparison against available water. |
| **What it means** | Typically 3-8 mm/day for most crops at peak season. |
| **How calculated** | `CWR = ET0 × Kc` or more specifically `CWR = ETc - effective_rainfall` |
| **Effect on drought** | When CWR > water supply (rain + irrigation + soil storage), deficit = drought stress. |
| **AI usage** | Used in water balance computation. Gap between CWR and supply drives risk. |

### 5.3 yield_reduction_factor

| Aspect | Detail |
|--------|--------|
| **Why chosen** | Quantifies the crop-specific sensitivity to water stress. Some crops (maize) are very sensitive, others (olive) are drought-tolerant. |
| **What it means** | FAO Ky value: 0 (no sensitivity) to 1.5+ (very sensitive). Ky = 1.25 for maize, 1.0 for wheat, 0.85 for barley. |
| **How** | Determined from FAO-66 tables (yield response to water). |
| **Effect on drought** | Higher Ky = more yield loss per unit of water deficit. |
| **AI usage** | Helps contextualize risk — same moisture deficit causes more damage to high-Ky crops. |

### 5.4 irrigation_method, irrigation_efficiency_percent, water_applied_mm

| Aspect | Detail |
|--------|--------|
| **Why chosen** | Irrigation is the primary human intervention to mitigate drought. Method and efficiency determine how much water actually reaches the crop. |
| **What it means** | Drip: 90% efficient. Flood: 40-60%. Center pivot: 75-85%. Water applied: actual volume delivered. |
| **How measured** | Flow meters, or estimated from pump hours × flow rate. |
| **Effect on drought** | Efficient irrigation can compensate for rainfall deficits. But if irrigation supply is limited, drought hits harder. |
| **AI usage** | Water balance includes `irrigation_mm` as an input. The pipeline can model "what-if" irrigation scenarios. |

### 5.5 leaf_temperature_c & stomatal_conductance

| Aspect | Detail |
|--------|--------|
| **Why chosen** | Plant stress indicators that precede visible wilting. Canopy temperature > air temperature = stomatal closure = stress. |
| **What it means** | Stomatal conductance (mol CO₂/m²/s): 0.05-0.5 normal, <0.05 = stressed. Leaf temperature: typically within 2-3°C of air temp; >5°C above = heat stress. |
| **How measured** | Infrared thermometer (leaf temp), porometer (stomatal conductance). |
| **Effect on drought** | Early warning — stomata close to conserve water, reducing photosynthesis. Leaf temp rises because evaporative cooling stops. |
| **AI usage** | Advanced warning features. Not currently primary model inputs but validate risk levels. |

---

## 6. METRIC GROUP 5: REMOTE SENSING METRICS

### 6.1 ndvi (Normalized Difference Vegetation Index)

| Aspect | Detail |
|--------|--------|
| **Why chosen** | NDVI is the gold standard satellite vegetation health metric. Measures greenness/chlorophyll activity. |
| **What it means** | -1 to 1. Barren: 0-0.1. Sparse: 0.1-0.3. Moderate: 0.3-0.5. Dense/healthy: 0.5-0.9. |
| **How measured** | Satellite: `NDVI = (NIR - Red) / (NIR + Red)`. NIR reflects healthy vegetation, Red is absorbed by chlorophyll. Sentinel-2, MODIS, Landsat. |
| **Effect on drought** | NDVI declining over time = vegetation stress = drought impact. NDVI < 0.3 in growing season = serious concern. |
| **AI usage** | **Critical**. XGBoost uses `ndvi` (latest value) and `ndvi_trend` (linear fit over 14 days). Declining NDVI = vegetation stress = higher risk. LSTM includes NDVI as one of 10 features. Heuristic: `ndvi_penalty = max(0, (0.8 - NDVI)/0.8 × 20)`. |

### 6.2 ndwi (Normalized Difference Water Index)

| Aspect | Detail |
|--------|--------|
| **Why chosen** | NDWI detects water content in vegetation and open water bodies. More sensitive to plant water status than NDVI. |
| **What it means** | `(Green - NIR) / (Green + NIR)`. Values > 0 = water, < 0 = dry. |
| **How measured** | Satellite sensors with green and NIR bands (e.g., Sentinel-2). |
| **Effect on drought** | NDWI drops before NDVI in water stress — earlier warning signal. |
| **AI usage** | Informational / cross-validation metric. Not a primary model input. |

### 6.3 land_surface_temperature_c (LST)

| Aspect | Detail |
|--------|--------|
| **Why chosen** | LST measures actual ground/vegetation temperature from space. Crop water stress causes temperature to rise. |
| **What it means** | Can be 10-20°C hotter than air temperature in dry conditions. Healthy vegetation stays cooler via transpiration. |
| **How measured** | Thermal infrared bands (e.g., MODIS band 31/32, Landsat TIRS, Sentinel-3 SLSTR). Split-window algorithm. |
| **Effect on drought** | Rising LST + constant or falling NDVI = severe crop water stress. LST anomaly > 5°C = alert. |
| **AI usage** | **Critical**. XGBoost uses `lst_c` (latest value). LSTM includes it as a feature. High LST = high ET = high risk. |

### 6.4 satellite_soil_moisture_percent

| Aspect | Detail |
|--------|--------|
| **Why chosen** | Satellite-based soil moisture provides spatially continuous measurements without field sensors. |
| **What it means** | Percentage of soil water content in the top 5 cm (SMAP) or deeper. |
| **How measured** | SMAP (L-band microwave, 0-5cm), Sentinel-1 (C-band SAR), or MODIS thermal inertia. |
| **Effect on drought** | Direct soil moisture measurement complements ground data. Gradient between satellite and ground = insight. |
| **AI usage** | Used as a fallback when ground-based `soil_moisture_pct` is missing. The pipeline fills gaps with satellite data. |

### 6.5 satellite_source

| Aspect | Detail |
|--------|--------|
| **Why chosen** | Different satellites have different resolutions, revisit times, and accuracy. Knowing the source helps assess data reliability. |
| **What it means** | SMAP (36km), Sentinel-1 (10m, 6-day revisit), MODIS (250m, daily), Landsat (30m, 8-day). |
| **AI usage** | Metadata for data quality weighting. |

### 6.6 vegetation_condition_index (VCI)

| Aspect | Detail |
|--------|--------|
| **Why chosen** | VCI normalizes NDVI against historical range — shows how current vegetation compares to "normal" for that time of year. |
| **What it means** | 0-100%. <35% = drought, 35-50% = moderate, >50% = normal. |
| **How calculated** | `VCI = (NDVI_current - NDVI_min_historical) / (NDVI_max_historical - NDVI_min_historical) × 100` |
| **Effect on drought** | VCI < 35% even with normal rainfall indicates a problem (maybe pest, disease, or soil issue). |
| **AI usage** | Included as contextual data in the prediction frame. |

### 6.7 evapotranspiration_sebal_mmday

| Aspect | Detail |
|--------|--------|
| **Why chosen** | SEBAL/METRIC are satellite-based energy balance models that map actual ET across large areas. |
| **What it means** | Actual ET in mm/day derived from satellite thermal imagery, not just potential/reference. |
| **How measured** | SEBAL: Surface Energy Balance Algorithm for Land. Uses LST, NDVI, and weather data to solve the energy balance. |
| **Effect on drought** | Actual ET < potential ET = crops are conserving water (stomatal closure) = stress. |
| **AI usage** | Cross-validation with ground-based ETc. |

---

## 7. METRIC GROUP 6: HYDROLOGY METRICS

### 7.1 precipitation_mm & evapotranspiration_mm

| Aspect | Detail |
|--------|--------|
| **Why chosen** | The two sides of the water balance equation. P - ET = net gain or loss. |
| **What it means** | Direct hydrological measurements (may differ from climate rainfall/ET because they're collected from hydrometeorological stations). |
| **Effect on drought** | Prolonged P < ET = accumulating water deficit = hydrological drought. |
| **AI usage** | Used in water balance and as cross-check on climate metrics. |

### 7.2 groundwater_depth_m

| Aspect | Detail |
|--------|--------|
| **Why chosen** | Groundwater is the reserve tank. Declining water table = long-term drought signal. |
| **What it means** | Depth in meters from surface to water table. Rising = good (recharge), falling = bad (depletion). |
| **How measured** | Piezometer / observation well. |
| **Effect on drought** | Shallow water tables (< 5m) can support crops via capillary rise. Deep tables (> 20m) = no benefit. Rapid decline = chronic overdraft. |
| **AI usage** | Contextual — informs long-term water availability. |

### 7.3 runoff_mm & river_flow_m3s

| Aspect | Detail |
|--------|--------|
| **Why chosen** | Runoff and river flow determine water available for reservoir storage and irrigation diversions. |
| **What it means** | Runoff: water flowing over/through soil into streams. River flow: actual discharge in cubic meters per second. |
| **How measured** | Runoff: weirs/flumes or model estimation. River flow: stage-discharge rating curve at gauging station. |
| **Effect on drought** | Low river flow = reduced irrigation supply = increased drought impact on agriculture. |
| **AI usage** | Used to model water availability for irrigation in the water balance. |

### 7.4 reservoir_storage_m3 & irrigation_supply_available_m3

| Aspect | Detail |
|--------|--------|
| **Why chosen** | Reservoirs store water from wet season for dry season. Storage level directly indicates drought resilience. |
| **What it means** | Current volume of water in reservoirs. % of total capacity. |
| **How measured** | Stage (water level) to volume conversion using bathymetric curves. |
| **Effect on drought** | Low reservoir storage = limited irrigation capacity = high drought risk even if rain is normal. |
| **AI usage** | Used to constrain irrigation supply in water balance scenarios. |

### 7.5 soil_water_deficit_index_mm

| Aspect | Detail |
|--------|--------|
| **Why chosen** | Direct supply-demand gap: how much more water is needed vs. available. |
| **What it means** | `Deficit = ETc - (rainfall + irrigation + available_soil_water)`. Positive = shortage. |
| **Effect on drought** | Deficit > 50mm cumulative = serious crop water stress. |
| **AI usage** | Direct drought indicator. Included in prediction frame. |

### 7.6 water_balance_percent

| Aspect | Detail |
|--------|--------|
| **Why chosen** | Single-number summary of the regional water situation. Easy to communicate. |
| **What it means** | `(supply / demand) × 100`. 100% = balanced, < 100% = deficit, > 100% = surplus. |
| **Effect on drought** | < 70% = drought conditions requiring monitoring. < 40% = crisis. |
| **AI usage** | Output-like metric that helps validate risk scores. |

---

## 8. HOW AI PREDICTS DROUGHT

### 8.1 The Three-Layer Prediction Architecture

```
+--------------------------------------------------------+
|                    DROUGHT PREDICTION                    |
+--------------------------------------------------------+
|                                                        |
|   +-------------------+  +--------------------------+   |
|   |   XGBoost         |  |   LSTM Neural Network    |   |
|   |   (Gradient       |  |   (Time Series           |   |
|   |    Boosting)      |  |    Forecasting)          |   |
|   |                   |  |                          |   |
|   | Input: 30-day     |  | Input: 30-60 day        |   |
|   | feature window    |  | sequences of 10 metrics  |   |
|   | Output: Risk 0-100|  | Output: Soil moisture    |   |
|   +--------+----------+  +------------+-------------+   |
|            |                           |                |
|            v                           v                |
|   +--------+---------------------------+-----------+   |
|   |           FALLBACK: Heuristic                     |   |
|   |           (Physics-based formulas)                |   |
|   |           Used when no trained model exists       |   |
|   +--------------------------------------------------+   |
|                                                        |
|   +--------------------------------------------------+   |
|   |  LLM Explainer (Ollama - Llama 3.2)              |   |
|   |  Converts numbers to natural language            |   |
|   +--------------------------------------------------+   |
+--------------------------------------------------------+
```

### 8.2 XGBoost — The Risk Scorer

**Algorithm**: Gradient-boosted decision trees (150 trees, max-depth 5, learning rate 0.05)

**Why XGBoost?**
- Handles mixed data types (continuous + categorical) naturally
- Robust to missing values
- Feature importance gives interpretable "driver" attribution
- Fast training and inference
- State-of-the-art for tabular data

**How features are extracted from 30-day window:**

```
30-day data window:
┌──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┐
│  D1  │  D2  │  D3  │ ...  │ D28  │ D29  │ D30  │      │
└──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┘
    │                                                 │
    └───── Latest values ─────────────────────────────┘
          soil_moisture_pct (D30)
          ndvi (D30)
          lst_c (D30)
    
    └───── 7-day aggregations ────────────────────────┘
          rainfall_7d_mm = sum(D24:D30)
          etc_7d_avg_mm = mean(D24:D30)
          soil_moisture_trend = linear fit(D24:D30)
    
    └───── 14-day aggregations ───────────────────────┘
          ndvi_trend = linear fit(D17:D30)
    
    └───── 30-day aggregations ───────────────────────┘
          rainfall_30d_mm = sum(D1:D30)
          etc_30d_avg_mm = mean(D1:D30)
          temp_anomaly_c = D30_temp - mean(D1:D30)_temp
          days_since_last_rain = count since last ≥1mm
```

**The 11 engineered features:**

| # | Feature | Formula | What It Detects |
|---|---------|---------|-----------------|
| 1 | `soil_moisture_pct` | Latest value | Current water availability |
| 2 | `ndvi` | Latest value | Current vegetation health |
| 3 | `lst_c` | Latest value | Current surface heat stress |
| 4 | `rainfall_30d_mm` | Sum of 30 days | Medium-term water supply |
| 5 | `rainfall_7d_mm` | Sum of 7 days | Recent rainfall relief |
| 6 | `etc_7d_avg_mm` | Mean of 7 days | Recent water demand |
| 7 | `etc_30d_avg_mm` | Mean of 30 days | Sustained water demand |
| 8 | `temp_anomaly_c` | Latest - 30d mean | Heat wave detection |
| 9 | `days_since_last_rain` | Count of dry days | Drought duration |
| 10 | `soil_moisture_trend` | Linear slope over 7d | Dry-down rate |
| 11 | `ndvi_trend` | Linear slope over 14d | Vegetation decline rate |

**Training target:**
The training target is calculated heuristically:
```
soil_risk = (1 - min(1, soil_water / available_capacity)) × 100
ndvi_penalty = max(0, (0.8 - min(0.8, NDVI)) / 0.8) × 20
spi_penalty = max(0, -SPI) × 10
risk = min(100, soil_risk + ndvi_penalty + spi_penalty)
```

**Driver Attribution:**
XGBoost's built-in `feature_importances_` (based on how many times a feature is used for splits, weighted by improvement) are mapped to 5 driver categories:

| XGBoost Feature | Maps to Driver Category |
|----------------|------------------------|
| rainfall_30d_mm, rainfall_7d_mm, days_since_last_rain | **rainfall_deficit** |
| soil_moisture_pct, soil_moisture_trend | **soil_moisture_decline** |
| temp_anomaly_c | **high_temperature** |
| ndvi, ndvi_trend | **vegetation_stress** |
| etc_7d_avg_mm | **high_evapotranspiration** |

Drivers are normalized to sum to 100%, providing a "what's causing this drought" breakdown.

### 8.3 LSTM — The Soil Moisture Forecaster

**Architecture:**
```
Input: (batch, 30-60 time steps, 10 features)
    │
    ▼
┌─────────────────────┐
│   LSTM Layer 1      │  hidden_size=64, returns_sequences=True
│   dropout=0.2       │
└─────────┬───────────┘
          │
┌─────────▼───────────┐
│   LSTM Layer 2      │  hidden_size=64, returns_sequences=False
│   dropout=0.2       │
└─────────┬───────────┘
          │
┌─────────▼───────────┐
│   Dropout(0.2)      │
└─────────┬───────────┘
          │
┌─────────▼───────────┐
│   Linear(hidden→1)  │  → predicted soil moisture
└─────────────────────┘
```

**10 input features to LSTM (the state vector):**

| Index | Feature | Why Include |
|-------|---------|-------------|
| 0 | `soil_moisture_pct` | Target variable — the sequence we need to forecast |
| 1 | `rainfall_mm` | Primary driver that replenishes soil moisture |
| 2 | `temp_max_c` | Drives ET — drains soil moisture |
| 3 | `temp_min_c` | Affects nighttime respiration and dew formation |
| 4 | `humidity_pct` | Controls ET rate |
| 5 | `wind_speed_ms` | Affects ET rate |
| 6 | `solar_radiation_wm2` | Energy for ET |
| 7 | `ndvi` | Vegetation health — declines when stressed |
| 8 | `lst_c` | Surface heat — rises when dry |
| 9 | `etc_mm` | Actual water demand |

**Why LSTM over other time-series models?**
- LSTMs capture long-term dependencies (up to 60 days in this case)
- They model non-linear relationships naturally
- They can learn complex interactions between variables (e.g., rain + temperature → soil moisture is non-linear)
- Outperforms ARIMA/SARIMA for multivariate environmental time series

**How training works:**
1. Normalize all 10 features to zero-mean unit-variance
2. Create sliding windows: for a dataset of N days, create (N - 30 - forecast_days) sequences
3. Each sequence: 30 days of [10 features] → target: soil moisture at day 30 + forecast_days
4. Split 80/20 train/validation
5. Train with Adam optimizer, MSELoss, early stopping (patience=15)
6. Two separate models:
   - **LSTM-7d**: sequence=30, forecast=7 → predicts soil moisture 7 days ahead
   - **LSTM-30d**: sequence=60, forecast=30 → predicts soil moisture 30 days ahead

**Converting LSTM soil moisture to risk:**
```
risk = (1 - min(1, predicted_soil_moisture / field_capacity)) × 100
```

This gives a 0-100 risk score. If predicted moisture is at or above field capacity, risk = 0. If moisture is 0, risk = 100.

### 8.4 Heuristic (Physics-Based) Fallback

When ML models are not trained, the system uses deterministic formulas:

**Risk calculation:**
```
soil_risk = (1 - min(1, current_moisture / field_capacity)) × 100
ndvi_penalty = max(0, (0.8 - ndvi) / 0.8) × 20
spi_penalty = max(0, -spi) × 10
risk_today = min(100, soil_risk + ndvi_penalty + spi_penalty)
```

**Future risk projection:**
```
decline_factor = max(0, min(2.0, abs(soil_trend) × 10))
rainfall_relief = max(0, min(20, rainfall_7d × 1.5))
risk_7day = max(0, min(100, risk_today + decline_factor × 8 - rainfall_relief × 0.5))
risk_30day = max(0, min(100, risk_today + decline_factor × 18 - rainfall_relief))
```

**Driver scores (heuristic):**
```
rainfall_deficit = max(0, 100 - min(100, (rainfall_30d/30) × 10)) + max(0, 100 - min(100, rainfall_7d × 10))
soil_moisture_decline = max(0, min(100, abs(soil_trend) × 300))
high_temperature = max(0, min(100, temp_anomaly × 15))
vegetation_stress = max(0, min(100, (1 - ndvi) × 100))
high_evapotranspiration = max(0, min(100, etc_avg × 20))
```

### 8.5 The Penman-Monteith ET0 Engine

A simplified FAO-56 Penman-Monteith is implemented in `physical_helpers.py`:

```python
# 1. Saturation vapor pressure (es) — depends only on temperature
es = 0.6108 × exp(17.27 × T / (T + 237.3))

# 2. Actual vapor pressure (ea) — es adjusted by humidity
ea = es × relative_humidity / 100

# 3. Vapor Pressure Deficit (VPD) — the "drying power" of air
VPD = es - ea

# 4. Slope of saturation vapor pressure curve (Δ)
Δ = 4098 × es / (T + 237.3)²

# 5. Psychrometric constant (γ) — depends on atmospheric pressure
γ = 0.000665 × 101.3  # ~0.067 kPa/°C at sea level

# 6. Net radiation (Rn) — converted from solar radiation
Rn = solar_radiation_Wm2 × 0.0864  # convert to MJ/m²/day

# 7. Wind factor
wind_factor = 0.26 × (1 + 0.54 × wind_speed_ms)

# 8. Reference ET (FAO-56 Penman-Monteith)
ET0 = (0.408 × Δ × Rn + γ × wind_factor × VPD) / (Δ + γ)
```

### 8.6 The Daily Water Balance

The pipeline simulates the soil water tank:

```
soil_water[t] = soil_water[t-1] + rainfall[t] + irrigation[t] - ETc[t] - runoff[t]
```

Where:
- Initial condition: `soil_water[0] = available_water_capacity × 0.7` (starting at 70% full)
- `runoff[t] = max(0, rainfall[t] - 5) × 0.3` (simple SCS-like runoff curve)
- `soil_water[t]` can never go below 0

---

## 9. THE LLM EXPLAINER

The system optionally connects to a local **Ollama** server running **Llama 3.2 (3B)** to generate natural language explanations.

**Input prompt structure:**
```
You are a drought analysis assistant for Ichkeul Lake, Tunisia.
Generate a 2-3 sentence explanation for a farmer based on:
- Current drought risk: 65/100 (Severe)
- 7-day forecast: 72/100 (Severe)
- 30-day forecast: 80/100 (Extreme)
- Primary driver: 45% rainfall deficit
- Secondary driver: 30% temperature anomaly
- Soil moisture: 18% (35% of capacity)
```

**Fallback explanations** (when Ollama is unavailable):
- Risk ≤ 20: "Conditions are normal..."
- Risk 21-40: "Watch level..."
- Risk 41-60: "Moderate drought..."
- Risk 61-80: "Severe drought..."
- Risk 81-100: "EXTREME DROUGHT EMERGENCY..."

---

## 10. END-TO-END PREDICTION FLOW

```
User clicks "Get Drought Prediction" (API: /api/drought-prediction/?region_id=X&year_id=Y)
    │
    ▼
1. Check database for recent prediction (within 1 hour)
    ├── Found and not "refresh" → return cached result
    └── Not found or "refresh=1" → proceed to pipeline
    
    ▼
2. Initialize DroughtPredictionPipeline
    │
    ▼
3. Set soil properties
    ├── Query latest SoilMetrics for region
    ├── Get sand/clay/silt/organic_matter/root_depth
    ├── Calculate field_capacity (Saxton-Rawls)
    ├── Calculate wilting_point (Saxton-Rawls)
    └── Calculate available_water_capacity_mm
    
    ▼
4. Build prediction frame (query last 120 days)
    ├── SoilMetrics → soil_moisture_pct, sand_pct, etc.
    ├── ClimateMetrics → rainfall, temps, humidity, wind, ET
    ├── DroughtIndices → SPI, SPEI, PDSI
    ├── RemoteSensingMetrics → NDVI, LST, satellite moisture
    ├── HydrologyMetrics → precipitation, ET, groundwater, runoff
    └── AgriculturalMetrics → Kc, CWR, irrigation
    
    ▼
5. Merge all on measurement_date (outer join)
    ├── Sort by date ascending
    └── Fill missing values (ffill, bfill, defaults)
    
    ▼
6. Prepare daily data
    ├── Convert solar_radiation MJ/m²/day → W/m²
    ├── Calculate ET0 (Penman-Monteith FAO-56)
    ├── Apply Kc → ETc = ET0 × Kc
    └── Run daily water balance → soil_water_mm
    
    ▼
7. Check for trained model files
    ├── All 6 files exist → load models → set is_trained = True
    └── Missing → is_trained = False
    
    ▼
8. Predict
    ├── is_trained = True:
    │   ├── XGBoost → risk_today, drivers (feature importances)
    │   ├── LSTM-7d → soil_moisture_7day_pct, risk_7day
    │   └── LSTM-30d → soil_moisture_30day_pct, risk_30day
    │
    └── is_trained = False:
        └── Heuristic formulas → risk_today, risk_7day, risk_30day, drivers
    
    ▼
9. Generate LLM explanation (optional)
    ├── Check Ollama availability
    ├── Build prompt with risk scores, drivers, soil moisture
    ├── Send to Ollama (30s timeout)
    └── Receive or fallback explanation
    
    ▼
10. Save prediction to DroughtPrediction table
    └── Return JSON response with:
        ├── location (field capacity, wilting point, AWC)
        ├── current (soil_moisture, soil_water, % of capacity)
        ├── risk_scores (today, 7day, 30day)
        ├── drivers (rainfall_deficit, etc. with %)
        ├── forecasts (soil_moisture_7day, soil_moisture_30day)
        └── llm_explanation (text)
```

---

## 11. APPENDIX: FORMULA REFERENCE

### Saxton & Rawls Pedotransfer Functions
```
Field Capacity (%) = 20.0 + 0.3 × clay + 0.1 × silt - 0.05 × sand
Wilting Point (%) = 8.0 + 0.2 × clay + 0.05 × silt - 0.03 × sand
Available Water Capacity (mm) = (FC - WP) / 100 × root_depth_mm
```

### Simplified Penman-Monteith (FAO-56)
```
es = 0.6108 × exp(17.27 × T / (T + 237.3))
ea = es × RH / 100
VPD = es - ea
Δ = 4098 × es / (T + 237.3)²
γ = 0.000665 × P_atm (~0.067 at sea level)
Rn = solar_radiation_Wm2 × 0.0864
wind_factor = 0.26 × (1 + 0.54 × u2)
ET0 = (0.408 × Δ × Rn + γ × wind_factor × VPD) / (Δ + γ × (1 + 0.34 × u2))
```

### Crop Evapotranspiration
```
ETc = ET0 × Kc
```

### Daily Water Balance
```
S_t = max(0, S_{t-1} + P_t + I_t - ETc_t - R_t)
R_t = max(0, P_t - 5) × 0.3
S_0 = AWC × 0.7
```

### Standardized Precipitation Index (SPI)
```
SPI = (P_current - μ_historical) / σ_historical
Clamped to [-3, +3]
```

### Vegetation Condition Index (VCI)
```
VCI = (NDVI_current - NDVI_min) / (NDVI_max - NDVI_min) × 100
```

### Heuristic Drought Risk (Fallback)
```
Soil Risk = (1 - min(1, SM / FC)) × 100
NDVI Penalty = max(0, (0.8 - NDVI) / 0.8) × 20
SPI Penalty = max(0, -SPI) × 10
Total Risk = min(100, Soil Risk + NDVI Penalty + SPI Penalty)
```

### LSTM Risk Conversion
```
Risk_forecast = (1 - min(1, SM_predicted / FC)) × 100
```

---


