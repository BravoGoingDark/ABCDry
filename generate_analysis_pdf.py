#!/usr/bin/env python3
"""Generate a comprehensive PDF analysis of the APWRS data entry system."""

from fpdf import FPDF
from datetime import datetime


class PDF(FPDF):
    def header(self):
        if self.page_no() > 1:
            self.set_font("Helvetica", "I", 7)
            self.set_text_color(120, 120, 120)
            self.cell(0, 4, "APWRS — Data Entry & Prediction Analysis", align="C")
            self.ln(6)

    def footer(self):
        self.set_y(-10)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(150, 150, 150)
        self.cell(0, 8, f"Page {self.page_no()}/{{nb}}", align="C")

    def section_title(self, title):
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(1, 45, 29)
        self.cell(0, 8, title)
        self.ln(2)
        self.set_draw_color(1, 45, 29)
        self.set_line_width(0.4)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def sub_title(self, title):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(0, 103, 125)
        self.cell(0, 6, title)
        self.ln(5)

    def body_text(self, text):
        self.set_font("Helvetica", "", 8.5)
        self.set_text_color(30, 30, 30)
        self.multi_cell(0, 4, text)
        self.ln(1)

    def field_table(self, rows, col_widths=(38, 28, 22, 52, 50)):
        self.set_font("Helvetica", "B", 7.5)
        self.set_fill_color(1, 45, 29)
        self.set_text_color(255, 255, 255)
        headers = ["Field", "Type", "Why Chosen", "Prediction Impact", "Priority"]
        for i, h in enumerate(headers):
            self.cell(col_widths[i], 5, h, border=1, fill=True, align="C")
        self.ln()
        self.set_font("Helvetica", "", 7)
        self.set_text_color(20, 20, 20)
        fill = False
        for row in rows:
            if fill:
                self.set_fill_color(240, 243, 255)
            else:
                self.set_fill_color(255, 255, 255)
            max_lines = 1
            for i, cell_text in enumerate(row):
                lines = self.multi_cell(col_widths[i], 4, cell_text, split_only=True)
                max_lines = max(max_lines, len(lines))
            h = max_lines * 4
            y_before = self.get_y()
            x_start = self.get_x()
            for i, cell_text in enumerate(row):
                x = x_start + sum(col_widths[:i])
                self.set_xy(x, y_before)
                self.multi_cell(col_widths[i], 4, cell_text, border=1, fill=fill)
            self.set_y(y_before + h)
            fill = not fill
            if self.get_y() > 260:
                self.add_page()


def build():
    pdf = PDF(orientation="P", unit="mm", format="A4")
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=15)

    # ── Cover Page ──
    pdf.add_page()
    pdf.ln(50)
    pdf.set_font("Helvetica", "B", 28)
    pdf.set_text_color(1, 45, 29)
    pdf.cell(0, 12, "APWRS", align="C")
    pdf.ln(14)
    pdf.set_font("Helvetica", "", 14)
    pdf.set_text_color(0, 103, 125)
    pdf.cell(0, 8, "Adaptive Planting Window Recommendation System", align="C")
    pdf.ln(20)
    pdf.set_draw_color(1, 45, 29)
    pdf.set_line_width(0.5)
    pdf.line(60, pdf.get_y(), 150, pdf.get_y())
    pdf.ln(10)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(60, 60, 60)
    pdf.cell(0, 7, "Comprehensive Analysis of Data Entry Fields", align="C")
    pdf.ln(7)
    pdf.cell(0, 7, "and Their Role in Drought Prediction", align="C")
    pdf.ln(20)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 5, f"Generated: {datetime.now().strftime('%B %d, %Y')}", align="C")
    pdf.ln(5)
    pdf.cell(0, 5, "Ichkeul Environmental Intelligence Platform", align="C")
    pdf.ln(30)
    pdf.set_font("Helvetica", "", 7.5)
    pdf.set_text_color(150, 150, 150)
    pdf.multi_cell(0, 4, (
        "This document explains every data field in the APWRS system: why it was chosen, "
        "how it is measured, and exactly how it affects the drought risk prediction pipeline. "
        "It covers the heuristic fallback model, the XGBoost ML model, and the LSTM "
        "forecasting engine, tracing each field from data entry through to the final risk score."
    ), align="C")

    # ── Table of Contents ──
    pdf.add_page()
    pdf.section_title("Table of Contents")
    toc = [
        "1.  Overview of the Prediction Pipeline",
        "2.  Soil Metrics",
        "3.  Climate Metrics",
        "4.  Drought Indices",
        "5.  Agricultural Metrics",
        "6.  Remote Sensing Metrics",
        "7.  Hydrology Metrics",
        "8.  Environmental Snapshot",
        "9.  The Soil Water Balance Engine",
        "10. Heuristic Risk Score Calculation",
        "11. XGBoost ML Model",
        "12. LSTM Forecasting",
        "13. Data Priority Summary",
    ]
    for t in toc:
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 5.5, t)
        pdf.ln()

    # ── 1. Overview ──
    pdf.add_page()
    pdf.section_title("1. Overview of the Prediction Pipeline")
    pdf.body_text(
        "The APWRS drought prediction system transforms raw environmental data into actionable "
        "risk scores through a multi-stage pipeline:\n\n"
        "1. DATA ENTRY: Users submit measurements via the Data Ingestion form or import Excel files. "
        "Data is stored in six metric tables (Soil, Climate, Drought Indices, Agricultural, "
        "Remote Sensing, Hydrology) plus the Environmental Snapshot table.\n\n"
        "2. DATA ASSEMBLY: The DroughtPredictionPipeline.build_prediction_frame() queries the last "
        "120 days of each metric type for a given region/year and merges them on measurement_date "
        "using an outer join. Missing values are forward-filled, backward-filled, then filled with "
        "domain-specific defaults.\n\n"
        "3. DERIVED COMPUTATIONS: The pipeline calculates evapotranspiration (Penman-Monteith style), "
        "soil water balance (cumulative water accounting), solar radiation unit conversion, and "
        "temperature averaging.\n\n"
        "4. PREDICTION: If trained ML models exist, XGBoost predicts today's risk and LSTM forecasts "
        "7/30-day risk. Otherwise, a heuristic fallback model computes risk from soil moisture, NDVI, "
        "and SPI using empirically-derived formulas.\n\n"
        "5. DRIVER ATTRIBUTION: Both heuristic and ML models identify the dominant drought driver "
        "(rainfall deficit, soil moisture decline, high temperature, vegetation stress, or high "
        "evapotranspiration) and display it on the analysis page.\n\n"
        "6. FORECASTING: The model projects risk 7 and 30 days ahead using soil moisture trends, "
        "expected rainfall relief, and (when trained) LSTM sequence prediction.\n\n"
        "The following sections detail every data field, organized by metric category."
    )

    # ── 2. Soil Metrics ──
    pdf.add_page()
    pdf.section_title("2. Soil Metrics")
    pdf.body_text(
        "Soil metrics describe the physical and hydrological properties of the soil profile. "
        "They determine how much water the soil can store, how quickly water infiltrates, "
        "and how much is available to plants."
    )
    soil_rows = [
        ("moisture_content_percent", "Decimal(5,2)", "Volumetric water content (%) — direct measure of water in the root zone. The single most reliable ground-truth drought indicator.",
         "PRIMARY input to soil_risk. In heuristic: risk = max(0,(1 - moisture/FC))*100. Top-3 XGBoost feature. LSTM forecast target.", "Critical"),
        ("field_capacity_percent", "Decimal(5,2)", "The upper limit of plant-available water. Soil above this drains away. Varies by texture (sand ~10%, clay ~40%).",
         "Denominator in soil_risk formula. Normalizes moisture across soil types. Sets the 100%-full reference for water balance.", "Critical"),
        ("wilting_point_percent", "Decimal(5,2)", "Lower limit of plant-available water. Below this, plants permanently wilt and die. Sand ~4%, clay ~20%.",
         "Used to compute Available Water Capacity (AWC) = (FC - WP) * root_depth / 100. Initializes the water balance model.", "High"),
        ("sand_ratio / clay_ratio / silt_ratio", "Decimal(5,2) each", "Soil texture triangle percentages. Define water retention, drainage, and infiltration characteristics.",
         "Input to pedotransfer functions that estimate field capacity and AWC when direct measurements are missing. Indirect water balance effect.", "Medium"),
        ("root_zone_depth_mm", "Integer", "Depth of the effective root zone (mm). Deeper roots access more soil water volume.",
         "Multiplied into AWC. Shallow roots (e.g., lettuce, 300mm) stress faster than deep roots (e.g., olives, 1500mm).", "Medium"),
        ("organic_matter_percent", "Decimal(5,2)", "Organic matter content (%). 1% OM holds ~20,000 gal/acre of extra water.",
         "Indirect — feeds pedotransfer functions. Higher OM = higher FC = lower risk at same moisture level.", "Low-Medium"),
        ("infiltration_rate_mmhr", "Decimal(6,2)", "How fast rainfall enters the soil. Sandy soil: 50+ mm/hr. Clay: 1-5 mm/hr.",
         "Controls runoff threshold in water balance. Low infiltration = more runoff = less water entering soil.", "Medium"),
        ("salinity_ece_dsm", "Decimal(5,3)", "Electrical conductivity (dS/m). High salinity creates osmotic drought — water present but plants can't absorb it.",
         "Alert trigger only. Future: could reduce effective field capacity in saline conditions.", "Low"),
        ("ph_level", "Decimal(3,1)", "Soil pH (0-14). Extreme pH locks out nutrients, causing physiological drought.",
         "Dashboard monitoring only. Future: could add soil health penalty to risk score.", "Low"),
    ]
    pdf.sub_title("2.1 Field Details")
    pdf.field_table(soil_rows)

    # ── 3. Climate Metrics ──
    pdf.add_page()
    pdf.section_title("3. Climate Metrics")
    pdf.body_text(
        "Climate metrics capture atmospheric conditions that drive water demand (evapotranspiration) "
        "and supply (rainfall). These are the most frequently updated data and have the largest "
        "impact on the prediction."
    )
    climate_rows = [
        ("rainfall_mm", "Decimal(6,1)", "Daily rainfall (mm). The primary water input. Also fallback to hydrology precipitation_mm if missing.",
         "Feeds water balance: soil_water += rain. Heuristic: rainfall_relief reduces 7/30d risk. XGBoost: 3 features (30d sum, 7d sum, days_since_last_rain). Most influential category.", "Critical"),
        ("temperature_max_c / min_c / mean_c", "Decimal(4,1)", "Daily temperature extremes and mean. Drives ET and heat stress.",
         "XGBoost: temp_anomaly_c (max vs 30d mean) is top feature. Heuristic: high_temperature driver. ET0 calculation via Penman-Monteith.", "Critical"),
        ("evapotranspiration_etc_mmday", "Decimal(5,2)", "Crop evapotranspiration (mm/day) — actual water consumed by the specific crop.",
         "Subtracted from water balance daily. XGBoost: etc_7d_avg and etc_30d_avg features. Heuristic: high_evapotranspiration driver.", "Critical"),
        ("evapotranspiration_et0_mmday", "Decimal(5,2)", "Reference evapotranspiration (mm/day) for a grass surface. The atmospheric water demand benchmark.",
         "Computed from climate variables if missing (Penman-Monteith). Then ETc = ET0 * Kc gives crop water use.", "High"),
        ("relative_humidity_percent", "Integer", "Relative humidity (%). Dry air = higher Vapor Pressure Deficit = more ET.",
         "Input to ET0 calculation. Lower humidity = higher ET0 = faster soil drying.", "High"),
        ("wind_speed_ms", "Decimal(4,2)", "Wind speed at 2m height (m/s). Removes humid boundary layer, increasing transpiration.",
         "Input to ET0 calculation. Stronger wind = higher ET0 = higher water demand.", "Medium"),
        ("solar_radiation_mjm2day", "Decimal(6,2)", "Solar radiation (MJ/m2/day). The energy driving evaporation and photosynthesis.",
         "Converted to W/m2 internally. Input to ET0 calculation. Largest energy source for ET.", "Medium"),
        ("seasonal_rainfall_variability", "Char(50)", "Classification of rainfall timing: normal, early, late, erratic.",
         "Informational display only. Not directly in risk formula.", "Low"),
    ]
    pdf.sub_title("3.1 Field Details")
    pdf.field_table(climate_rows)

    # ── 4. Drought Indices ──
    pdf.add_page()
    pdf.section_title("4. Drought Indices")
    pdf.body_text(
        "Drought indices are standardized measures that compare current conditions to historical "
        "norms. They provide context: is this drought unusual or within the expected range?"
    )
    drought_rows = [
        ("spi_1month", "Decimal(5,2)", "Standardized Precipitation Index (1-month). Measures rainfall deviation from historical normal. Range: -3 to +3.",
         "Heuristic: spi_penalty = max(0, -spi) * 10. SPI of -2 adds 20 risk points. SPI of -3 adds 30. XGBoost: spi feature.", "High"),
        ("spi_3month / spi_12month", "Decimal(5,2)", "SPI at 3 and 12-month timescales. Capture longer-term precipitation deficits.",
         "Available for charting on dashboard. 1-month version used in risk formula.", "Medium"),
        ("spei_1month / 3month / 12month", "Decimal(5,2)", "Standardized Precipitation-Evapotranspiration Index. Like SPI but also accounts for temperature-driven ET demand.",
         "Displayed on dashboard (orange polyline vs SPI red). Not yet in risk formula but would be a more comprehensive replacement for SPI.", "Medium"),
        ("pdsi_value", "Decimal(5,2)", "Palmer Drought Severity Index. Range -6 (extreme drought) to +6 (extreme wet). Incorporates temperature and soil moisture.",
         "Included in prediction frame as a feature. Not directly weighted in heuristic.", "Low-Medium"),
        ("drought_severity_class", "Char(20)", "Human-readable classification: None / Abnormally Dry / Moderate / Severe / Extreme Drought.",
         "Display/output field. Maps to color-coded badges in the UI.", "Low"),
    ]
    pdf.sub_title("4.1 Field Details")
    pdf.field_table(drought_rows)

    # ── 5. Agricultural Metrics ──
    pdf.add_page()
    pdf.section_title("5. Agricultural Metrics")
    pdf.body_text(
        "Agricultural metrics describe the crop itself: what is planted, its growth stage, "
        "water requirements, and how it is irrigated. These fields convert a general drought "
        "index into an agricultural drought risk specific to the farmer's crop."
    )
    agri_rows = [
        ("crop_id (CropType FK)", "ForeignKey", "The crop species (e.g., Durum Wheat, Olives, Tomatoes, Barley). Different crops have vastly different water needs.",
         "Determines the Kc curve. Olives (Kc=0.6) use half the water of tomatoes at flowering (Kc=1.2). Directly scales ETc = ET0 * Kc.", "High"),
        ("crop_coefficient_kc", "Decimal(4,2)", "Crop coefficient that scales reference ET0 to crop-specific ETc. Varies by crop and growth stage.",
         "Direct multiplier in ETc calculation. Higher Kc = more water consumed = faster soil depletion = higher risk.", "High"),
        ("growth_stage", "Char(20)", "Crop development stage: Germination / Vegetative / Flowering / Grain Filling / Maturity. Water sensitivity varies dramatically.",
         "Currently stored for reference. Future: could adjust Kc by stage (Kc peaks at flowering, drops at maturity).", "Medium"),
        ("crop_water_requirement_mmday", "Decimal(5,2)", "The total water the crop needs per day to avoid stress. Integrates ET and soil evaporation.",
         "Used in soil water deficit calculation. Deficit = requirement - available. Positive deficit = stress.", "Medium"),
        ("yield_reduction_factor", "Decimal(5,3)", "Yield loss fraction per unit of water deficit (0-1). Factor of 0.8 = 80% yield loss under complete stress.",
         "Displayed as Crop Stress metric on analysis page. Separate indicator alongside risk score.", "Medium"),
        ("irrigation_method (IrrigationMethod FK)", "ForeignKey", "Irrigation technique: Drip (90%+ efficiency), Sprinkler (75%), Flood (50-60%).",
         "Determines irrigation_efficiency, which scales water_applied in the water balance.", "High"),
        ("irrigation_efficiency_percent", "Integer", "Fraction of applied water that enters the root zone. Drip: 90%, Flood: 55%.",
         "Water balance: net_irrigation = water_applied * efficiency / 100. Low efficiency = less usable water.", "High"),
        ("water_applied_mm", "Decimal(6,2)", "Irrigation water applied (mm). The second water input alongside rainfall.",
         "Added to water balance. Without this, irrigated fields show falsely high risk.", "High"),
        ("leaf_temperature_c", "Decimal(4,1)", "Leaf temperature (C). Leaf temp above air temp indicates stomatal closure (water stress).",
         "Early-warning stress indicator. Stored for research/display.", "Low"),
        ("stomatal_conductance", "Decimal(6,3)", "How open the stomata are (mol/m2/s). Low conductance = plant conserving water = stressed.",
         "Most direct measure of plant water status. Stored for future models.", "Low"),
    ]
    pdf.sub_title("5.1 Field Details")
    pdf.field_table(agri_rows)

    # ── 6. Remote Sensing ──
    pdf.add_page()
    pdf.section_title("6. Remote Sensing Metrics")
    pdf.body_text(
        "Remote sensing data from satellites (MODIS, Sentinel-2, Landsat, SMAP) provides "
        "wall-to-wall coverage of vegetation health, soil moisture, and land surface temperature. "
        "These are especially valuable in areas without ground sensors."
    )
    rs_rows = [
        ("ndvi", "Decimal(4,3)", "Normalized Difference Vegetation Index (-1 to 1). Measures greenness/health. 0.6-0.9 = healthy, 0.1-0.3 = stressed/bare.",
         "Heuristic: ndvi_penalty = max(0, (0.8-ndvi)/0.8)*20. NDVI 0.2 adds 15 risk points. XGBoost: ndvi + ndvi_trend (14d slope).", "Critical"),
        ("ndwi", "Decimal(4,3)", "Normalized Difference Water Index. Detects water content in canopies. Drops before NDVI shows visible stress.",
         "Stored for future use. Would catch earlier-stage drought than NDVI alone.", "Low"),
        ("land_surface_temperature_c", "Decimal(5,2)", "Satellite thermal band temperature (C). Hot surfaces = dry soil + stressed vegetation (no evaporative cooling).",
         "XGBoost: lst_c feature. Elevated LST vs air temp = strong thermal stress signal.", "Medium"),
        ("satellite_soil_moisture_percent", "Decimal(5,2)", "Soil moisture from SMAP/Sentinel-1 radar. Depth ~5cm for radar, ~5cm for SMAP.",
         "Fallback for soil_moisture_pct when ground sensor data is missing. Enables predictions without ground stations.", "Medium"),
        ("vegetation_condition_index", "Decimal(5,2)", "NDVI relative to historical range for the same time of year (%). VCI < 35% = moderate-severe drought.",
         "Normalizes NDVI across seasons. Stored for future enhancement of the risk model.", "Low"),
        ("evapotranspiration_sebal_mmday", "Decimal(5,2)", "ET from SEBAL/METRIC energy balance model. Spatially-distributed ET over large areas.",
         "Alternative source for etc_mm when ground measurements unavailable.", "Low"),
        ("satellite_source", "Char(50)", "Satellite platform: SMAP / Sentinel-1 / MODIS / Landsat. Different resolution and accuracy.",
         "Metadata for data provenance. No direct impact on risk score.", "Low"),
    ]
    pdf.sub_title("6.1 Field Details")
    pdf.field_table(rs_rows)

    # ── 7. Hydrology ──
    pdf.add_page()
    pdf.section_title("7. Hydrology Metrics")
    pdf.body_text(
        "Hydrology metrics track the broader water cycle: precipitation, runoff, groundwater, "
        "and surface water storage. They provide basin-scale context for the field-level drought assessment."
    )
    hydro_rows = [
        ("precipitation_mm", "Decimal(6,1)", "In-situ precipitation from weather stations.",
         "Fallback for rainfall_mm in the water balance. Same field, different source.", "Medium"),
        ("evapotranspiration_mm", "Decimal(6,1)", "Hydrologic water balance ET (precip - runoff - storage change).",
         "Cross-check for climate ETc. Not used directly in risk scoring.", "Low"),
        ("groundwater_depth_m", "Decimal(6,2)", "Depth to groundwater (m). Shallow water (<2m) can capillary-rise into root zone.",
         "Dashboard monitoring. Future: could add capillary rise contribution to water balance in shallow GW areas.", "Low"),
        ("runoff_mm", "Decimal(6,1)", "Rainfall that runs off instead of infiltrating.",
         "Pipeline computes runoff internally as max(0,rain-5)*0.3. Manual entries are stored but computed value is used.", "Medium"),
        ("river_flow_m3s", "Decimal(10,2)", "River discharge (m3/s). Indicates basin-scale water availability.",
         "Displayed for regional awareness. Indirect: low flow = regional drought context.", "Low"),
        ("reservoir_storage_m3", "Decimal(15,0)", "Reservoir water volume (m3). Indicates irrigation water availability for coming weeks.",
         "Planning indicator. Full reservoir buffers against short-term rainfall deficits.", "Low"),
        ("irrigation_supply_available_m3", "Decimal(15,0)", "Available irrigation water for allocation.",
         "Complements water_applied_mm. Even if crop needs water, it can't be applied if supply is exhausted.", "Low"),
        ("soil_water_deficit_index_mm", "Decimal(6,2)", "Gap between crop water demand and available water (ETc - available).",
         "Pipeline computes this internally. Manual entry provides cross-verification.", "Medium"),
        ("water_balance_percent", "Decimal(6,2)", "Water supply as percentage of demand. 100% = supply meets demand.",
         "Display field. Internal water balance achieves same with more granularity.", "Low"),
    ]
    pdf.sub_title("7.1 Field Details")
    pdf.field_table(hydro_rows)

    # ── 8. Environmental Snapshot ──
    pdf.add_page()
    pdf.section_title("8. Environmental Snapshot")
    pdf.body_text(
        "The Environmental Snapshot stores yearly summary conditions for a region. It provides "
        "the high-level context displayed on the dashboard sidebar (live metrics) and the "
        "EnvironmentalSnapshot cards in the Data Ingestion section."
    )
    snap_rows = [
        ("wind_speed_kmh", "Decimal(5,1)", "Snapshot wind speed (km/h).",
         "Dashboard live display. ClimateMetrics wind_speed_ms (converted) feeds ET0 calculation.", "Low"),
        ("wind_gust_kmh / wind_direction", "Decimal/Char", "Gust speed and prevailing direction.",
         "Dashboard display. Identifies weather pattern origins.", "Low"),
        ("rainfall_mm / rainfall_delta_percent", "Decimal / Integer", "Annual rainfall and deviation from normal.",
         "Dashboard live display. Negative delta triggers precipitation gap alert.", "Low"),
        ("temperature_c / humidity_percent", "Decimal / Integer", "Snapshot temperature and humidity.",
         "Dashboard live display. Actual risk model uses ClimateMetrics equivalents.", "Low"),
        ("ph_level", "Decimal(3,1)", "Water/soil pH snapshot.",
         "Dashboard monitoring.", "Low"),
        ("npk_index", "Char(20)", "Nitrogen-Phosphorus-Potassium nutrient index. Healthy plants tolerate drought better.",
         "Dashboard display. Future: could adjust yield_reduction_factor based on nutrient status.", "Low"),
    ]
    pdf.sub_title("8.1 Field Details")
    pdf.field_table(snap_rows)

    # ── 9. Soil Water Balance ──
    pdf.add_page()
    pdf.section_title("9. The Soil Water Balance Engine")
    pdf.body_text(
        "The soil water balance is the core hydrological model that converts sporadic measurements "
        "into a continuous daily soil moisture simulation. It is defined as:\n\n"
        "    soil_water[t] = soil_water[t-1] + rainfall + irrigation_net - etc - runoff\n\n"
        "Where:\n"
        "    soil_water[0] = AWC x 0.7   (initial condition: 70% of field capacity)\n"
        "    AWC = (field_capacity - wilting_point) x root_zone_depth / 100\n"
        "    irrigation_net = water_applied x irrigation_efficiency / 100\n"
        "    runoff = max(0, rainfall - 5) x 0.3   (simplified SCS curve number)\n"
        "    etc = ET0 x Kc, or directly from etc_mmday\n\n"
        "The balance is initialized at 70% of field capacity (a typical well-watered condition "
        "for rainfed agriculture). Each day, rainfall and irrigation add water, while ETc consumes "
        "water and runoff removes excess. The balance is constrained between 0 and AWC (soil cannot "
        "hold more than field capacity; excess becomes deep drainage).\n\n"
        "The resulting soil_water_mm is normalized: moisture_pct = soil_water_mm / AWC * 100. "
        "This normalized value is what feeds the risk formulas. A balance that has steadily declined "
        "to 30% of AWC indicates severe stress.\n\n"
        "Key insight: The balance integrates 120 days of history. A single rain event today cannot "
        "undo 3 months of deficit — it takes sustained rainfall to refill the profile. This is why "
        "the balance is more reliable than a single moisture snapshot."
    )

    # ── 10. Heuristic Risk ──
    pdf.add_page()
    pdf.section_title("10. Heuristic Risk Score Calculation")
    pdf.body_text(
        "When ML models are not trained, the pipeline uses empirically-derived formulas. "
        "These are based on physical principles and expert agronomic knowledge.\n\n"
        "TODAY'S RISK:\n"
        "    soil_risk = max(0, (1 - min(1, moisture_pct / field_capacity)) x 100)\n"
        "    ndvi_penalty = max(0, (0.8 - min(0.8, ndvi)) / 0.8) x 20\n"
        "    spi_penalty = max(0, -spi) x 10\n"
        "    risk_today = min(100, soil_risk + ndvi_penalty + spi_penalty)\n\n"
        "7-DAY FORECAST:\n"
        "    decline = max(0, min(2, abs(soil_trend) x 10))\n"
        "    relief = max(0, min(20, rainfall_7d x 1.5))\n"
        "    risk_7d = max(0, min(100, risk_today + decline x 8 - relief x 0.5))\n\n"
        "30-DAY FORECAST:\n"
        "    risk_30d = max(0, min(100, risk_today + decline x 18 - relief))\n\n"
        "DRIVER ATTRIBUTION (which factor is driving the risk):\n"
        "    rainfall_deficit = f(rainfall_7d, rainfall_30d)\n"
        "    soil_moisture_decline = f(7-day moisture trend)\n"
        "    high_temperature = f(temp_anomaly from 30-day mean)\n"
        "    vegetation_stress = f(ndvi)\n"
        "    high_evapotranspiration = f(etc_7d_average)\n\n"
        "The driver with the highest score is labelled the 'Dominant Driver' on the analysis page, "
        "with its absolute magnitude shown alongside (e.g., 'rainfall_deficit (72/100)')."
    )

    # ── 11. XGBoost ──
    pdf.add_page()
    pdf.section_title("11. XGBoost ML Model")
    pdf.body_text(
        "The XGBoost model learns non-linear relationships between environmental features and "
        "drought risk from historical data.\n\n"
        "FEATURES (11 engineered from a 30-day window):\n"
        "  1. soil_moisture_pct     - latest ground/satellite moisture\n"
        "  2. ndvi                  - latest vegetation index\n"
        "  3. lst_c                 - latest land surface temperature\n"
        "  4. rainfall_30d_mm      - total rainfall over 30 days\n"
        "  5. rainfall_7d_mm       - total rainfall over 7 days\n"
        "  6. etc_7d_avg_mm        - mean crop ET over 7 days\n"
        "  7. etc_30d_avg_mm       - mean crop ET over 30 days\n"
        "  8. temp_anomaly_c       - current max temp minus 30-day mean max temp\n"
        "  9. days_since_last_rain - consecutive days with <1mm rain\n"
        " 10. soil_moisture_trend  - linear slope of 7-day moisture values\n"
        " 11. ndvi_trend           - linear slope of 14-day NDVI values\n\n"
        "TARGET (ground truth for training): Computed identically to the heuristic formula.\n\n"
        "MODEL CONFIGURATION:\n"
        "    Algorithm: XGBRegressor\n"
        "    Trees: 150 (with early stopping at 20 rounds)\n"
        "    Max depth: 5\n"
        "    Learning rate: 0.05\n"
        "    Subsample: 80% (row sampling)\n"
        "    Colsample: 80% (column sampling)\n"
        "    Preprocessing: StandardScaler on all features\n\n"
        "DRIVER MAPPING: Feature importances from XGBoost are grouped into the same 5 driver "
        "categories. The ML model can learn that, for example, 'days since last rain' is more "
        "important than 'rainfall_30d_mm' in certain climatic regimes, adjusting driver weights "
        "accordingly."
    )

    # ── 12. LSTM ──
    pdf.add_page()
    pdf.section_title("12. LSTM Forecasting")
    pdf.body_text(
        "The LSTM (Long Short-Term Memory) model provides sequence-based forecasting for both "
        "risk scores and soil moisture.\n\n"
        "7-DAY FORECASTER:\n"
        "    Input sequence: 30 days of daily features\n"
        "    Output: 7 days of predicted risk scores + 7 days of predicted soil moisture\n"
        "    Architecture: LSTM with hidden layers, trained on historical sequences\n\n"
        "30-DAY FORECASTER:\n"
        "    Input sequence: 60 days of daily features\n"
        "    Output: 30 days of predicted risk scores + 30 days of predicted soil moisture\n"
        "    Architecture: LSTM with hidden layers, trained on historical sequences\n\n"
        "The LSTM captures temporal dependencies that the heuristic and XGBoost models miss. "
        "For example, a pattern of 'moderate rain followed by heat wave' might historically "
        "lead to a specific risk trajectory that the LSTM recognizes.\n\n"
        "Training: Both models require torch (PyTorch). The management command is:\n"
        "    python manage.py train_models --region-id X --year-id Y [--skip-lstm]\n\n"
        "If torch is unavailable, use --skip-lstm to train XGBoost only."
    )

    # ── 13. Priority Summary ──
    pdf.add_page()
    pdf.section_title("13. Data Priority Summary")
    pdf.body_text(
        "Not all data fields are equally important. The priority classification below helps users "
        "focus their data entry efforts on the fields that have the greatest impact on prediction accuracy.\n\n"
        "CRITICAL - Prediction will be unreliable without these:\n"
        "    moisture_content_percent, field_capacity_percent\n"
        "    rainfall_mm (daily time series)\n"
        "    etc_mmday (or et0_mmday + kc)\n"
        "    ndvi\n"
        "    spi_1month\n\n"
        "HIGH - Significantly improve accuracy:\n"
        "    temperature_max_c (for temp_anomaly and ET0)\n"
        "    crop_id + crop_coefficient_kc (crop-specific ETc)\n"
        "    water_applied_mm + irrigation_method + irrigation_efficiency\n"
        "    wilting_point_percent (for AWC calculation)\n"
        "    relative_humidity_percent, wind_speed_ms, solar_radiation (for ET0)\n\n"
        "MEDIUM - Useful refinements:\n"
        "    sand/clay/silt_ratio, root_zone_depth, organic_matter_percent, infiltration_rate\n"
        "    growth_stage, crop_water_requirement_mmday, yield_reduction_factor\n"
        "    satellite_soil_moisture_percent (fallback if ground missing)\n"
        "    land_surface_temperature_c (XGBoost feature)\n"
        "    precipitation_mm, runoff_mm (fallback/cross-check)\n"
        "    spei (future SPI replacement)\n\n"
        "LOW - Monitoring/display only (no direct risk impact):\n"
        "    salinity, pH (both soil), seasonal_rainfall_variability\n"
        "    groundwater_depth_m, river_flow_m3s, reservoir_storage_m3\n"
        "    irrigation_supply_available_m3, water_balance_percent\n"
        "    ndwi, vegetation_condition_index, evapotranspiration_sebal_mmday\n"
        "    leaf_temperature_c, stomatal_conductance\n"
        "    All EnvironmentalSnapshot fields\n\n"
        "SYSTEM RESILIENCE: The pipeline is designed to produce a prediction even with "
        "incomplete data. Each critical field has a fallback chain:\n"
        "    Moisture: ground sensor -> satellite soil moisture -> default 0\n"
        "    Rainfall: climate rainfall -> hydrology precipitation -> default 0\n"
        "    ETc: stored etc -> ET0 * Kc -> calculated from climate variables\n"
        "    NDVI: satellite ndvi -> default 0.5\n"
        "    SPI: stored spi -> default 0\n\n"
        "The more fields a user provides, the more accurate the prediction. But a meaningful "
        "estimate is always possible with just rainfall + moisture + NDVI."
    )

    # Save
    output_path = r"C:\Users\Taha\Desktop\APWRS_Data_Entry_Analysis.pdf"
    pdf.output(output_path)
    print(f"PDF saved to: {output_path}")


if __name__ == "__main__":
    build()
