from fpdf import FPDF
import os

class FormulaReport(FPDF):
    def header(self):
        if self.page_no() > 1:
            self.set_font('Helvetica', 'I', 8)
            self.set_text_color(120, 120, 120)
            self.cell(0, 8, 'APWRS - Formula & Calculation Reference', 0, 0, 'C')
            self.ln(4)
            self.set_draw_color(200, 200, 200)
            self.line(10, 14, 200, 14)
            self.ln(6)

    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f'Page {self.page_no()}/{{nb}}', 0, 0, 'C')

    def chapter_title(self, num, title):
        self.set_font('Helvetica', 'B', 16)
        self.set_text_color(25, 60, 100)
        self.cell(0, 12, f'{num}. {title}', 0, 1, 'L')
        self.set_draw_color(25, 60, 100)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def sub_title(self, title):
        self.set_font('Helvetica', 'B', 12)
        self.set_text_color(60, 80, 120)
        self.cell(0, 8, title, 0, 1, 'L')
        self.ln(1)

    def formula_box(self, formula, desc, inputs, source, ref):
        self.set_fill_color(240, 245, 255)
        self.set_draw_color(180, 200, 230)
        y_before = self.get_y()
        self.set_font('Courier', '', 9)
        lines = self.multi_cell(0, 5, formula, split_only=True)
        h = max(len(lines) * 5 + 2, 8) + 2
        if y_before + h + 30 > 270:
            self.add_page()
            y_before = self.get_y()
        self.rect(12, y_before, 186, h, 'DF')
        self.set_xy(14, y_before + 2)
        self.set_font('Courier', '', 9)
        self.set_text_color(20, 20, 20)
        self.multi_cell(182, 5, formula)
        self.set_y(y_before + h + 1)
        self.set_font('Helvetica', '', 9)
        self.set_text_color(60, 60, 60)
        self.cell(0, 5, f'Description: {desc}', 0, 1)
        self.cell(0, 5, f'Inputs: {inputs}', 0, 1)
        self.cell(0, 5, f'Source: {source}', 0, 1)
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(100, 100, 100)
        self.cell(0, 5, f'Reference: {ref}', 0, 1)
        self.ln(4)

    def code_block(self, text):
        self.set_fill_color(245, 245, 245)
        self.set_text_color(30, 30, 30)
        self.set_font('Courier', '', 8)
        lines = text.split('\n')
        h = len(lines) * 4 + 4
        if self.get_y() + h + 10 > 270:
            self.add_page()
        y = self.get_y()
        self.rect(12, y, 186, h, 'F')
        self.set_xy(14, y + 2)
        for line in lines:
            self.cell(0, 4, line, 0, 1)
        self.ln(3)

    def table_row(self, cells, bold=False, fill=False):
        w = [40, 50, 50, 50]
        if bold:
            self.set_font('Helvetica', 'B', 8)
        else:
            self.set_font('Helvetica', '', 8)
        if fill:
            self.set_fill_color(230, 235, 245)
        else:
            self.set_fill_color(255, 255, 255)
        self.set_draw_color(200, 200, 200)
        x_start = self.get_x()
        y_start = self.get_y()
        max_h = 6
        for i, cell in enumerate(cells):
            x = x_start + sum(w[:i])
            self.set_xy(x, y_start)
            self.multi_cell(w[i], 5, str(cell), border=1, fill=True, align='C' if i > 0 else 'L')
            max_h = max(max_h, self.get_y() - y_start)
        self.set_y(y_start + max_h)


pdf = FormulaReport()
pdf.alias_nb_pages()
pdf.set_auto_page_break(auto=True, margin=20)
pdf.add_page()

# Title page
pdf.set_font('Helvetica', 'B', 28)
pdf.set_text_color(25, 60, 100)
pdf.ln(50)
pdf.cell(0, 15, 'APWRS', 0, 1, 'C')
pdf.set_font('Helvetica', '', 16)
pdf.set_text_color(80, 80, 80)
pdf.cell(0, 10, 'Formula & Calculation Reference Manual', 0, 1, 'C')
pdf.ln(5)
pdf.set_draw_color(25, 60, 100)
pdf.line(60, pdf.get_y(), 150, pdf.get_y())
pdf.ln(10)
pdf.set_font('Helvetica', '', 11)
pdf.set_text_color(100, 100, 100)
pdf.cell(0, 7, 'Drought Risk Assessment Platform', 0, 1, 'C')
pdf.cell(0, 7, 'Comprehensive documentation of all mathematical models,', 0, 1, 'C')
pdf.cell(0, 7, 'algorithms, and data processing methods', 0, 1, 'C')
pdf.ln(20)
pdf.set_font('Helvetica', 'I', 9)
pdf.set_text_color(150, 150, 150)
pdf.cell(0, 5, f'Generated: June 2026', 0, 1, 'C')
pdf.cell(0, 5, 'Project: APWRS', 0, 1, 'C')

# Table of Contents
pdf.add_page()
pdf.set_font('Helvetica', 'B', 18)
pdf.set_text_color(25, 60, 100)
pdf.cell(0, 12, 'Table of Contents', 0, 1, 'L')
pdf.set_draw_color(25, 60, 100)
pdf.line(10, pdf.get_y(), 200, pdf.get_y())
pdf.ln(6)

toc = [
    ("1", "Soil Physics - Saxton-Rawls Pedotransfer Functions", "3"),
    ("2", "Evapotranspiration - FAO-56 Penman-Monteith", "4"),
    ("3", "Crop Coefficient (Kc) Model", "5"),
    ("4", "Soil Water Balance", "6"),
    ("5", "Drought Indices (SPI, VCI)", "7"),
    ("6", "Composite Risk Scoring", "8"),
    ("7", "Heuristic Driver Scores & Ensemble", "9"),
    ("8", "XGBoost Machine Learning Model", "10"),
    ("9", "LSTM Neural Network Forecasting", "11"),
    ("10", "Rolling Window Aggregations", "12"),
    ("11", "Haversine Coordinate Validation", "13"),
    ("12", "Synthetic Data Generation", "14"),
    ("13", "Classification Thresholds", "15"),
    ("14", "JavaScript / Turf.js Spatial Calculations", "16"),
    ("15", "Data Validation & Unit Conversion", "17"),
    ("16", "Statistical Evaluation Metrics", "18"),
]

for num, title, pg in toc:
    pdf.set_font('Helvetica', '', 11)
    pdf.set_text_color(60, 60, 60)
    dots = '.' * (70 - len(f'{num}. {title}'))
    pdf.cell(0, 7, f'  {num}. {title} {dots} {pg}', 0, 1)

# ============================================================
# SECTION 1
# ============================================================
pdf.add_page()
pdf.chapter_title('1', 'Soil Physics - Saxton-Rawls Pedotransfer Functions')
pdf.set_font('Helvetica', '', 10)
pdf.set_text_color(60, 60, 60)
pdf.multi_cell(0, 5, 'These empirical functions estimate soil hydraulic properties from texture and organic matter. Based on Saxton & Rawls (2006). All percentages are 0-100 scale.')
pdf.ln(3)

pdf.formula_box(
    'FC = -0.251*SAND + 0.195*CLAY + 0.011*OM + 0.006*(SAND*OM)\n     - 0.027*(CLAY*OM) + 0.452*SILT + 0.299',
    'Field Capacity - water content at field capacity (%)',
    'SAND%, CLAY%, SILT%, OM% (organic matter)',
    'Saxton & Rawls (2006) pedotransfer function',
    'prediction_engine/physical_helpers.py:4'
)

pdf.formula_box(
    'WP = -0.024*SAND + 0.487*CLAY + 0.006*OM + 0.005*(SAND*OM)\n     - 0.013*(CLAY*OM) + 0.068*SILT + 0.031',
    'Wilting Point - water content at permanent wilting point (%)',
    'SAND%, CLAY%, SILT%, OM% (organic matter)',
    'Saxton & Rawls (2006) pedotransfer function',
    'prediction_engine/physical_helpers.py:9'
)

pdf.formula_box(
    'AWC_mm = (FC% - WP%) / 100 * ROOT_DEPTH_mm',
    'Available Water Capacity - total plant-available water in root zone (mm)',
    'FC% (field capacity), WP% (wilting point), ROOT_DEPTH_mm (root zone depth)',
    'Derived from Saxton-Rawls outputs',
    'prediction_engine/physical_helpers.py:14'
)

# ============================================================
# SECTION 2
# ============================================================
pdf.add_page()
pdf.chapter_title('2', 'Evapotranspiration - FAO-56 Penman-Monteith')
pdf.set_font('Helvetica', '', 10)
pdf.set_text_color(60, 60, 60)
pdf.multi_cell(0, 5, 'The FAO-56 Penman-Monteith equation is the standard method for computing reference evapotranspiration (ET0) from meteorological data.')
pdf.ln(3)

pdf.formula_box(
    'ET0 = [0.408*D*(Rn-G) + g*(900/(T+273))*u2*(es-ea)]\n      / [D + g*(1 + 0.34*u2)]',
    'Reference Evapotranspiration (mm/day)',
    'Rn = net radiation (MJ/m2/day), G = soil heat flux (~0), T = mean temp (C),\nu2 = wind speed at 2m (m/s), es-ea = vapor pressure deficit (kPa)',
    'FAO Irrigation & Drainage Paper 56',
    'prediction_engine/physical_helpers.py:19'
)

pdf.sub_title('Supporting Calculations')

pdf.formula_box(
    'D = 4098 * 0.6108 * exp((17.27*T)/(T+237.3)) / (T+237.3)^2',
    'Slope of saturation vapor pressure curve (kPa/C)',
    'T = mean daily temperature (C)',
    'FAO-56',
    'physical_helpers.py:22'
)

pdf.formula_box(
    'es = 0.6108 * exp((17.27*T)/(T+237.3))',
    'Saturation vapor pressure (kPa)',
    'T = mean daily temperature (C)',
    'FAO-56',
    'physical_helpers.py:24'
)

pdf.formula_box(
    'ea = es * HUMIDITY% / 100',
    'Actual vapor pressure (kPa)',
    'es (saturation vapor pressure), HUMIDITY% (relative humidity)',
    'FAO-56',
    'physical_helpers.py:26'
)

pdf.formula_box(
    'Rn = SOLAR_RAD_Wm2 * 0.0864 * (1 - 0.23)',
    'Net radiation (MJ/m2/day). Albedo = 0.23 (reference grass).',
    'SOLAR_RAD_Wm2 (solar radiation in W/m2)',
    'FAO-56',
    'physical_helpers.py:30'
)

pdf.formula_box(
    'g = 0.665e-3 * 101.3',
    'Psychrometric constant (kPa/C) at sea level',
    'Atmospheric pressure (101.3 kPa at sea level)',
    'FAO-56',
    'physical_helpers.py:28'
)

pdf.formula_box(
    'ETc = ET0 * Kc',
    'Crop Evapotranspiration (mm/day)',
    'ET0 (reference ET), Kc (crop coefficient)',
    'FAO-56',
    'prediction_engine/physical_helpers.py:49'
)

# ============================================================
# SECTION 3
# ============================================================
pdf.add_page()
pdf.chapter_title('3', 'Crop Coefficient (Kc) Model')
pdf.set_font('Helvetica', '', 10)
pdf.set_text_color(60, 60, 60)
pdf.multi_cell(0, 5, 'The crop coefficient Kc is determined by a piecewise linear function over four growth stages (initial, development, mid-season, late-season). Based on FAO-56.')
pdf.ln(3)

pdf.sub_title('Stage Definition & Kc Values')
pdf.set_font('Helvetica', '', 8)
pdf.set_text_color(60, 60, 60)

# Table header
pdf.set_font('Helvetica', 'B', 9)
pdf.set_fill_color(25, 60, 100)
pdf.set_text_color(255, 255, 255)
col_w = [47, 24, 24, 24, 24, 33]
headers = ['Crop', 'Initial', 'Develop', 'Mid', 'Late', 'End']
x0 = pdf.get_x()
y0 = pdf.get_y()
for i, h in enumerate(headers):
    w = col_w[i]
    pdf.cell(w, 7, h, 1, 0, 'C', True)
pdf.ln()

data = [
    ['Wheat / Barley', '0.30', 'Linear', '1.15', 'Linear', '0.30'],
    ['Olive', '0.65', 'Linear', '0.70', 'Linear', '0.70'],
    ['Date Palm', '0.65', 'Linear', '0.95', 'Linear', '0.50'],
    ['Alfalfa', '0.65', 'Linear', '1.20', 'Linear', '0.30'],
]
pdf.set_text_color(60, 60, 60)
for i, row in enumerate(data):
    pdf.set_font('Helvetica', '', 8)
    if i % 2 == 0:
        pdf.set_fill_color(240, 245, 255)
    else:
        pdf.set_fill_color(255, 255, 255)
    for j, val in enumerate(row):
        pdf.cell(col_w[j], 6, val, 1, 0, 'C' if j > 0 else 'L', True)
    pdf.ln()

pdf.ln(4)
pdf.set_font('Helvetica', '', 10)
pdf.set_text_color(60, 60, 60)
pdf.cell(0, 5, 'During development and late-season stages, Kc varies linearly between the adjacent stage values.', 0, 1)
pdf.cell(0, 5, 'Kc is constrained to a maximum of 2.0 for physical plausibility.', 0, 1)
pdf.ln(2)
pdf.formula_box(
    'Kc_total = interpolate(stage_duration_fraction, Kc_start, Kc_end)',
    'Linear interpolation between stage boundaries based on days since planting',
    'days_since_planting, total_growth_days, crop_type',
    'FAO-56 approach',
    'prediction_engine/physical_helpers.py:32'
)

# ============================================================
# SECTION 4
# ============================================================
pdf.add_page()
pdf.chapter_title('4', 'Soil Water Balance')
pdf.set_font('Helvetica', '', 10)
pdf.set_text_color(60, 60, 60)
pdf.multi_cell(0, 5, 'Daily soil water accounting based on inputs and losses. The soil profile is treated as a single-layer reservoir bounded by 0 and AWC.')
pdf.ln(3)

pdf.formula_box(
    'SM_t = SM_(t-1) + RAIN + IRRIGATION - ETc - RUNOFF',
    'Daily soil moisture update (mm). Constrained between 0 and AWC.',
    'SM_(t-1) = previous day moisture (mm), RAIN = daily rainfall (mm),\nIRRIGATION = applied water (mm), ETc = crop ET (mm), RUNOFF = surface runoff (mm)',
    'Single-layer bucket model',
    'prediction_engine/physical_helpers.py:54'
)

# ============================================================
# SECTION 5
# ============================================================
pdf.chapter_title('5', 'Drought Indices')
pdf.ln(2)

pdf.sub_title('Standardized Precipitation Index (SPI)')
pdf.formula_box(
    'SPI = (RAIN_30d_SUM - HIST_MEAN) / HIST_STD',
    'Standardized measure of rainfall deviation. Positive = wet, negative = dry.',
    'RAIN_30d_SUM = sum of rainfall over last 30 days,\nHIST_MEAN = historical mean of 30-day sums,\nHIST_STD = historical standard deviation',
    'McKee et al. (1993)',
    'prediction_engine/physical_helpers.py:60'
)

pdf.sub_title('Vegetation Condition Index (VCI)')
pdf.formula_box(
    'VCI = (NDVI_current - NDVI_min) / (NDVI_max - NDVI_min) * 100',
    'Vegetation health relative to historical range (0-100%).\nLow values indicate vegetation stress.',
    'NDVI_current (current NDVI value),\nNDVI_min/NDVI_max (historical min/max NDVI)',
    'Kogan (1995)',
    'prediction_engine/physical_helpers.py:68'
)

# ============================================================
# SECTION 6
# ============================================================
pdf.add_page()
pdf.chapter_title('6', 'Composite Risk Scoring')
pdf.set_font('Helvetica', '', 10)
pdf.set_text_color(60, 60, 60)
pdf.multi_cell(0, 5, 'Three different risk score formulations exist, used in different contexts:')
pdf.ln(3)

pdf.sub_title('A. Dashboard View Risk Score (views.py)')
pdf.formula_box(
    'SCORE = (w_NDVI*NDVI_score + w_T*T_score + w_R*RAIN_score + w_H*HUM_score)\n       / TOTAL_WEIGHT',
    'Weighted average of normalized metric scores. Each metric normalized 0-100.',
    'NDVI, temperature, rainfall, humidity observed values.\nNormalization: (val - min)/(max - min)*100',
    'Custom heuristic',
    'dashboard/views.py:78'
)

pdf.sub_title('B. XGBoost Target Risk Score (xgboost_risk_predictor.py)')
pdf.formula_box(
    'SM_risk = max(0, min(100, (1 - SM/FC)*100))\nNDVI_risk = max(0, min(100, (1 - NDVI)*100))\nRAIN_risk = max(0, min(100, max(0, 100 - RAIN_30d*2)))\nT_risk = max(0, min(100, (Tmax - 35)*5)) if Tmax>35 else 0\n\nFINAL = SM_risk*0.4 + NDVI_risk*0.25 + RAIN_risk*0.2 + T_risk*0.15',
    'Physical-based composite risk used as training target for XGBoost model (0-100)',
    'SM = soil moisture, FC = field capacity, NDVI = vegetation index,\nRAIN_30d = 30-day rainfall sum, Tmax = max temperature (C)',
    'Custom physical composite',
    'prediction_engine/xgboost_risk_predictor.py:67'
)

pdf.sub_title('C. Risk Level Classification')
pdf.formula_box(
    '< 20  -> "Normal"\n20-39 -> "Watch"\n40-59 -> "Moderate"\n60-79 -> "Severe"\n>=80  -> "Extreme"',
    'Risk level labels derived from the 0-100 continuous score',
    'risk_score (float 0-100)',
    'Custom thresholds',
    'All risk components (views.py:86, llm_explainer.py:26)'
)

# ============================================================
# SECTION 7
# ============================================================
pdf.add_page()
pdf.chapter_title('7', 'Heuristic Driver Scores & Ensemble Prediction')
pdf.set_font('Helvetica', '', 10)
pdf.set_text_color(60, 60, 60)
pdf.multi_cell(0, 5, 'The pipeline.py orchestrates physical heuristic calculations and combines them with ML model outputs.')

pdf.ln(2)
pdf.sub_title('Driver Scores (each 0-100)')
pdf.formula_box(
    'MOISTURE_driver = max(0, min(100, (1 - avg_SM/FC)*100))\nRAINFALL_driver = max(0, min(100, max(0, 100 - RAIN_30d*2)))\nTEMP_driver = max(0, min(100, (Tmax-35)*10)) if Tmax>35 else 0\nNDVI_driver = max(0, min(100, (1 - avg_NDVI)*100))\nHUMIDITY_driver = max(0, min(100, (100 - avg_HUM)*1.5))',
    'Individual risk drivers computed from observed/simulated data',
    'SM, FC, RAIN_30d, Tmax, NDVI, HUM from the prediction frame',
    'Custom heuristic',
    'prediction_engine/pipeline.py:356'
)

pdf.sub_title('Heuristic Risk')
pdf.formula_box(
    'HEUR_RISK = MOISTURE*0.35 + RAINFALL*0.20 + TEMP*0.15 + NDVI*0.20 + HUMIDITY*0.10',
    'Weighted combination of driver scores into a single heuristic risk estimate',
    '5 driver scores (0-100 each)',
    'Custom weighting',
    'prediction_engine/pipeline.py:375'
)

pdf.sub_title('Ensemble Prediction')
pdf.formula_box(
    'FINAL_RISK = (HEUR_RISK + XGB_RISK) / 2',
    'Simple average of heuristic and ML model outputs when XGBoost is available',
    'heuristic_risk, xgboost_risk (both 0-100)',
    'Custom ensemble',
    'prediction_engine/pipeline.py:444'
)

pdf.sub_title('Derived Columns in Pipeline')
pdf.set_font('Helvetica', '', 9)
pdf.set_text_color(60, 60, 60)
derived = [
    'etc_mm = crop_coefficient_kc * et0_mm',
    'soil_moisture_mm = moisture_pct / 100 * root_depth_mm',
    'awc_mm = (fc - wp) / 100 * root_depth_mm',
    'water_deficit_mm = max(0, awc_mm - soil_moisture_mm)',
    'deficit_pct = water_deficit_mm / awc_mm * 100',
    'daily_water_balance = rainfall - etc',
    'cumulative_water_balance = cumsum(water_balance) over lookback',
]
for d in derived:
    pdf.cell(0, 5, f'  * {d}', 0, 1)
pdf.ln(3)

# ============================================================
# SECTION 8
# ============================================================
pdf.add_page()
pdf.chapter_title('8', 'XGBoost Machine Learning Model')
pdf.set_font('Helvetica', '', 10)
pdf.set_text_color(60, 60, 60)
pdf.multi_cell(0, 5, 'Gradient boosted tree regressor trained on engineered features from a 30-day sliding window. Uses physical composite risk as the target variable.')
pdf.ln(3)

pdf.sub_title('Feature Engineering (30+ features)')
pdf.set_font('Helvetica', '', 9)

features = [
    'soil_moisture_mean/std/min/max/trend (30-day rolling)',
    'rainfall_sum_30day, rainfall_days_with_rain, rainfall_intensity',
    'temp_max_mean, temp_max_trend, temp_min_mean',
    'humidity_mean, humidity_trend',
    'et0_sum (30-day ET sum)',
    'ndvi_mean, ndvi_trend',
    'awc_mm, field_capacity_pct (contextual)',
]
pdf.set_text_color(60, 60, 60)
for f in features:
    pdf.cell(0, 5, f'  * {f}', 0, 1)
pdf.ln(2)

pdf.sub_title('Model Configuration')
pdf.formula_box(
    'XGBRegressor(\n    n_estimators=300, max_depth=6, learning_rate=0.1,\n    subsample=0.8, colsample_bytree=0.8, random_state=42\n)',
    'XGBoost model with regularization via subsampling and column sampling',
    'Feature vector (~30 features), Target = risk_score (0-100)',
    'XGBoost library (Chen & Guestrin, 2016)',
    'prediction_engine/xgboost_risk_predictor.py:85'
)

pdf.ln(2)
pdf.sub_title('Preprocessing')
pdf.formula_box(
    'Z = (X - MEAN) / STD',
    'StandardScaler normalization applied per feature column',
    'Training features',
    'scikit-learn StandardScaler',
    'prediction_engine/xgboost_risk_predictor.py:110'
)

pdf.sub_title('Driver Extraction (Feature Importance)')
pdf.formula_box(
    'DRIVER_i = IMPORTANCE_i / SUM(IMPORTANCE) * 100',
    'Top-5 most important features normalized to 100% for drought driver attribution',
    'XGBoost model.feature_importances_',
    'Custom normalization',
    'prediction_engine/xgboost_risk_predictor.py:150'
)

# ============================================================
# SECTION 9
# ============================================================
pdf.add_page()
pdf.chapter_title('9', 'LSTM Neural Network Forecasting')
pdf.set_font('Helvetica', '', 10)
pdf.set_text_color(60, 60, 60)
pdf.multi_cell(0, 5, 'A recurrent neural network for multi-step time series forecasting of soil moisture. Uses a 30-day lookback to predict 7-30 days ahead.')
pdf.ln(3)

pdf.sub_title('Model Architecture')
pdf.formula_box(
    'Input(30 days x 10 features)\n  -> LSTM(hidden=64, layers=2, dropout=0.2)\n    -> Linear(64 -> 1)\n      -> Output: next day soil moisture',
    '2-layer LSTM with dropout regularization, followed by a linear output layer',
    '10 features: soil_moisture%, rainfall, Tmax, Tmin, humidity%,\nwind_speed, solar_radiation, NDVI, LST, ETc',
    'PyTorch nn.Module',
    'prediction_engine/lstm_forecaster.py:16'
)

pdf.sub_title('Sequence Preparation')
pdf.formula_box(
    'X[i] = sequence[i : i+SEQ_LEN]\ny[i] = target[i+SEQ_LEN-1+FORECAST_DAYS]',
    'Sliding window: each sample is a SEQ_LEN-length window,\ntarget is FORECAST_DAYS ahead of the window end',
    'Full time series dataframe, SEQ_LEN=30, FORECAST_DAYS=7',
    'Custom sliding window',
    'prediction_engine/lstm_forecaster.py:70'
)

pdf.sub_title('Normalization')
pdf.formula_box(
    'X_norm = (X - MEAN) / (STD + 1e-8)',
    'Per-column z-score normalization. Epsilon prevents division by zero.',
    'Raw numeric feature columns',
    'StandardScaler analogue',
    'prediction_engine/lstm_forecaster.py:52'
)

pdf.sub_title('Training Configuration')
pdf.formula_box(
    'LOSS = MSE(y_true, y_pred)\nOPTIMIZER = Adam(lr=1e-3)\nEARLY_STOP = patience=8 on validation loss',
    'Mean squared error loss with Adam optimizer. Early stopping prevents overfitting.',
    'y_true (target risk), y_pred (model output)',
    'PyTorch MSELoss, Adam optimizer',
    'prediction_engine/lstm_forecaster.py:93'
)

pdf.sub_title('Recursive Multi-Step Forecast')
pdf.formula_box(
    'For day = 1..FORECAST_DAYS:\n    pred = model(last_30_days)\n    sequence = sequence[1:] + [pred]\n    forecasts.append(pred)',
    'Recursive: each prediction feeds back into the input window for the next step',
    'Last 30 days of observed data',
    'Custom recursive forecasting',
    'prediction_engine/lstm_forecaster.py:173'
)

pdf.sub_title('Risk from LSTM Forecast')
pdf.formula_box(
    'RISK = max(0, min(100, (1 - SM_predicted/FC)*100))',
    'Converts forecasted soil moisture back into a drought risk score (0-100)',
    'SM_predicted (mm), FC = field capacity (mm)',
    'Custom',
    'prediction_engine/lstm_forecaster.py:198'
)

# ============================================================
# SECTION 10
# ============================================================
pdf.add_page()
pdf.chapter_title('10', 'Rolling Window Aggregations')
pdf.set_font('Helvetica', '', 10)
pdf.set_text_color(60, 60, 60)
pdf.multi_cell(0, 5, 'Daily data is resampled and aggregated over sliding windows to capture recent trends and cumulative effects.')
pdf.ln(3)

rolls = [
    ('7d rainfall sum', 'SUM(rainfall) over 7-day window'),
    ('30d rainfall sum', 'SUM(rainfall) over 30-day window'),
    ('7d ET sum', 'SUM(ETc) over 7-day window'),
    ('30d ET sum', 'SUM(ETc) over 30-day window'),
    ('7d avg temperature', 'MEAN(Tmean) over 7-day window'),
    ('30d avg temperature', 'MEAN(Tmean) over 30-day window'),
    ('7d avg NDVI', 'MEAN(NDVI) over 7-day window'),
    ('30d avg NDVI', 'MEAN(NDVI) over 30-day window'),
    ('Water balance', 'RAIN - ETc (daily)'),
    ('Cumulative water balance', 'cumsum(water_balance) over lookback window'),
]

pdf.set_font('Helvetica', 'B', 9)
pdf.set_fill_color(25, 60, 100)
pdf.set_text_color(255, 255, 255)
pdf.cell(60, 7, 'Metric', 1, 0, 'C', True)
pdf.cell(130, 7, 'Formula', 1, 1, 'C', True)

pdf.set_text_color(60, 60, 60)
for i, (name, formula) in enumerate(rolls):
    pdf.set_font('Helvetica', '', 8)
    if i % 2 == 0:
        pdf.set_fill_color(240, 245, 255)
    else:
        pdf.set_fill_color(255, 255, 255)
    pdf.cell(60, 6, name, 1, 0, 'L', True)
    pdf.cell(130, 6, formula, 1, 1, 'L', True)

pdf.ln(5)
pdf.set_font('Helvetica', '', 10)
pdf.cell(0, 5, 'Source: prediction_engine/pipeline.py:219-260', 0, 1)

# ============================================================
# SECTION 11
# ============================================================
pdf.add_page()
pdf.chapter_title('11', 'Haversine Coordinate Validation')
pdf.set_font('Helvetica', '', 10)
pdf.set_text_color(60, 60, 60)
pdf.multi_cell(0, 5, 'Validates that submitted coordinates fall within an acceptable distance from the region\'s defined center point. Used during data ingestion to enforce geographic bounds.')
pdf.ln(3)

pdf.formula_box(
    'a = sin^2(Dlat/2) + cos(lat1)*cos(lat2)*sin^2(Dlon/2)\nc = 2 * atan2(sqrt(a), sqrt(1-a))\nd = 6371 * c',
    'Great-circle distance between two points on Earth (km)',
    'lat1, lon1 = region center point (degrees),\nlat2, lon2 = submitted coordinates (degrees)',
    'Haversine formula',
    'dashboard/views.py:157'
)

pdf.ln(2)
pdf.formula_box(
    'VALID if d <= REGION.radius_km\nREGIONS: Countries = 300 km, Sub-regions = 50 km\nDefaults to 100 km for unspecified regions',
    'Validation rule: submitted coordinates must be within region\'s radius',
    'd = haversine distance (km), region.radius_km = configured max radius',
    'Custom geographic bounds check',
    'dashboard/views.py:165'
)

# ============================================================
# SECTION 12
# ============================================================
pdf.add_page()
pdf.chapter_title('12', 'Synthetic Data Generation')
pdf.set_font('Helvetica', '', 10)
pdf.set_text_color(60, 60, 60)
pdf.multi_cell(0, 5, 'Synthetic datasets are generated using stochastic processes with seasonal patterns for testing and model training.')
pdf.ln(3)

pdf.sub_title('Rainfall (Gamma Distribution)')
pdf.formula_box('RAIN = Gamma(shape=2.0, scale=5.0) per day', 'Daily rainfall (mm), non-negative', 'Random seed', 'Gamma distribution', 'scripts/generate_sample_drought_data.py')

pdf.sub_title('Temperature (Seasonal + Noise)')
pdf.formula_box('Tmax = 35 + 15*sin(2p*day/365 - p/2) + N(0,3)\nTmin = 18 + 10*sin(2p*day/365 - p/2) + N(0,3)', 'Seasonal temperature with Gaussian noise', 'day (1-365)', 'Custom seasonal model', 'scripts/generate_sample_drought_data.py')

pdf.sub_title('Relative Humidity (Seasonal + Noise)')
pdf.formula_box('HUM = 55 + 20*sin(2p*day/365 + p/2) + N(0,8)', 'Seasonal relative humidity with noise, clipped to 0-100', 'day (1-365)', 'Custom seasonal model', 'scripts/generate_sample_drought_data.py')

pdf.sub_title('NDVI (Logistic Growth + Stress)')
pdf.formula_box('NDVI = 0.15 + 0.60*logistic(days_planting)*exp(-0.01*rain_deficit)', 'Crop growth curve with drought stress decay', 'days_since_planting, rainfall_deficit', 'Custom crop growth model', 'scripts/generate_sample_drought_data.py')

pdf.sub_title('NDWI (Water Index)')
pdf.formula_box('NDWI = -0.1 + 0.5*(SM/FC) - 0.1*NDVI + N(0,0.05)', 'Water index derived from soil moisture and vegetation', 'SM = soil moisture, FC = field capacity, NDVI', 'Custom', 'scripts/generate_sample_drought_data.py')

pdf.sub_title('PDSI Approximation (Simplified)')
pdf.formula_box('PDSI = -3.0*(1 - RAIN_30d/ET0_30d) + N(0,0.5)', 'Simplified Palmer Drought Severity Index approximation', 'RAIN_30d, ET0_30d (30-day totals)', 'Simplified Palmer model', 'scripts/generate_sample_drought_data.py')

pdf.sub_title('Synthetic Target Risk Score')
pdf.formula_box(
    'RISK = 0.30*(100-NDVI*100) + 0.25*SM_risk + 0.20*RAIN_risk\n     + 0.15*TEMP_risk + 0.10*HUM_risk',
    'Composite target risk score for ML model training',
    'NDVI, soil_moisture, rainfall_30d, Tmax, humidity',
    'Custom weighted composite',
    'scripts/generate_sample_drought_data.py'
)

# ============================================================
# SECTION 13
# ============================================================
pdf.add_page()
pdf.chapter_title('13', 'Classification Thresholds')
pdf.set_font('Helvetica', '', 10)
pdf.set_text_color(60, 60, 60)
pdf.multi_cell(0, 5, 'Continuous values are classified into discrete categories using fixed thresholds.')
pdf.ln(3)

# SPI table
pdf.sub_title('SPI Classification')
pdf.set_font('Helvetica', 'B', 9)
pdf.set_fill_color(25, 60, 100)
pdf.set_text_color(255, 255, 255)
pdf.cell(50, 7, 'SPI Range', 1, 0, 'C', True)
pdf.cell(80, 7, 'Classification', 1, 1, 'C', True)

spi_data = [
    ('< -2.0', 'Extremely Dry'),
    ('-2.0 to -1.5', 'Severely Dry'),
    ('-1.5 to -1.0', 'Moderately Dry'),
    ('-1.0 to 1.0', 'Near Normal'),
    ('1.0 to 1.5', 'Moderately Wet'),
    ('1.5 to 2.0', 'Very Wet'),
    ('> 2.0', 'Extremely Wet'),
]
pdf.set_text_color(60, 60, 60)
for i, (rng, cls) in enumerate(spi_data):
    pdf.set_font('Helvetica', '', 8)
    if i % 2 == 0:
        pdf.set_fill_color(240, 245, 255)
    else:
        pdf.set_fill_color(255, 255, 255)
    pdf.cell(50, 6, rng, 1, 0, 'C', True)
    pdf.cell(80, 6, cls, 1, 1, 'C', True)

pdf.ln(5)
# NDVI table
pdf.sub_title('NDVI Classification')
pdf.set_font('Helvetica', 'B', 9)
pdf.set_fill_color(25, 60, 100)
pdf.set_text_color(255, 255, 255)
pdf.cell(50, 7, 'NDVI Range', 1, 0, 'C', True)
pdf.cell(80, 7, 'Classification', 1, 1, 'C', True)

ndvi_data = [
    ('< 0.1', 'Barren'),
    ('0.1 - 0.2', 'Sparse'),
    ('0.2 - 0.4', 'Moderate'),
    ('> 0.4', 'Dense Vegetation'),
]
pdf.set_text_color(60, 60, 60)
for i, (rng, cls) in enumerate(ndvi_data):
    pdf.set_font('Helvetica', '', 8)
    if i % 2 == 0:
        pdf.set_fill_color(240, 245, 255)
    else:
        pdf.set_fill_color(255, 255, 255)
    pdf.cell(50, 6, rng, 1, 0, 'C', True)
    pdf.cell(80, 6, cls, 1, 1, 'C', True)

pdf.ln(5)
# VCI table
pdf.sub_title('VCI Classification')
pdf.set_font('Helvetica', 'B', 9)
pdf.set_fill_color(25, 60, 100)
pdf.set_text_color(255, 255, 255)
pdf.cell(50, 7, 'VCI Range', 1, 0, 'C', True)
pdf.cell(80, 7, 'Classification', 1, 1, 'C', True)

vci_data = [
    ('< 10', 'Extreme Drought'),
    ('10 - 25', 'Severe Drought'),
    ('25 - 40', 'Moderate Drought'),
    ('40 - 60', 'Normal'),
    ('> 60', 'Very Good'),
]
pdf.set_text_color(60, 60, 60)
for i, (rng, cls) in enumerate(vci_data):
    pdf.set_font('Helvetica', '', 8)
    if i % 2 == 0:
        pdf.set_fill_color(240, 245, 255)
    else:
        pdf.set_fill_color(255, 255, 255)
    pdf.cell(50, 6, rng, 1, 0, 'C', True)
    pdf.cell(80, 6, cls, 1, 1, 'C', True)

pdf.ln(5)
pdf.set_font('Helvetica', '', 9)
pdf.set_text_color(60, 60, 60)
pdf.cell(0, 5, 'Source: Templates/dashboard/analysis.html', 0, 1)

# ============================================================
# SECTION 14
# ============================================================
pdf.add_page()
pdf.chapter_title('14', 'JavaScript / Turf.js Spatial Calculations')
pdf.set_font('Helvetica', '', 10)
pdf.set_text_color(60, 60, 60)
pdf.multi_cell(0, 5, 'Client-side spatial operations performed in the browser using the Turf.js library.')
pdf.ln(3)

pdf.formula_box(
    'distance = turf.distance(point1, point2, {units:"kilometers"})',
    'Great-circle distance between two map points (km)',
    'Two GeoJSON Point objects',
    'Turf.js (Haversine)',
    'static/dashboard/js/dashboard.js'
)

pdf.formula_box(
    'area_hectares = turf.area(polygon) / 10000',
    'Area of a drawn polygon converted from m2 to hectares',
    'GeoJSON Polygon object',
    'Turf.js',
    'static/dashboard/js/dashboard.js'
)

pdf.formula_box(
    'bearing = turf.bearing(from, to)',
    'Compass bearing between two points (degrees from north)',
    'Two GeoJSON Point objects',
    'Turf.js',
    'static/dashboard/js/dashboard.js'
)

pdf.formula_box(
    'delta_pct = (current - previous) / previous * 100',
    'Percent change for real-time dashboard updates (wind, rain)',
    'current, previous sensor values',
    'Custom',
    'static/dashboard/js/dashboard.js'
)

# ============================================================
# SECTION 15
# ============================================================
pdf.add_page()
pdf.chapter_title('15', 'Data Validation & Unit Conversion')
pdf.set_font('Helvetica', '', 10)
pdf.set_text_color(60, 60, 60)
pdf.multi_cell(0, 5, 'Ingested data is validated against agronomically realistic bounds and converted to standard units.')
pdf.ln(3)

pdf.sub_title('Validation Bounds')
pdf.set_font('Helvetica', 'B', 9)
pdf.set_fill_color(25, 60, 100)
pdf.set_text_color(255, 255, 255)
pdf.cell(70, 7, 'Metric Type', 1, 0, 'C', True)
pdf.cell(120, 7, 'Valid Range', 1, 1, 'C', True)

bounds = [
    ('NDVI / NDWI', '-1.0 to 1.0'),
    ('Moisture, Humidity, OM (%)', '0 to 100'),
    ('Temperature (C)', '-50 to 60'),
    ('Evapotranspiration (mm/day)', '0 to 20'),
    ('Salinity', '0 to 50'),
    ('SPI', '-5 to 5'),
    ('Wind Speed', '0 to 200'),
    ('Rainfall / Irrigation / Runoff', '>= 0'),
]
pdf.set_text_color(60, 60, 60)
for i, (metric, rng) in enumerate(bounds):
    pdf.set_font('Helvetica', '', 8)
    if i % 2 == 0:
        pdf.set_fill_color(240, 245, 255)
    else:
        pdf.set_fill_color(255, 255, 255)
    pdf.cell(70, 6, metric, 1, 0, 'L', True)
    pdf.cell(120, 6, rng, 1, 1, 'C', True)

pdf.ln(5)
pdf.sub_title('Wind Speed Conversion')
pdf.formula_box(
    'km/h -> m/s: val / 3.6\nm/s -> km/h: val * 3.6',
    'Unit normalization for ET calculations',
    'Wind speed in original units',
    'Standard unit conversion',
    'dashboard/data_ingestion_utils.py:157'
)

pdf.sub_title('StandardScaler Normalization (ML)')
pdf.formula_box(
    'Z = (X - MEAN) / STD\n(with epsilon 1e-8 to prevent division by zero)',
    'Standard score normalization for ML model inputs',
    'Raw feature matrix X',
    'scikit-learn StandardScaler / custom',
    'xgboost_risk_predictor.py, lstm_forecaster.py'
)

pdf.sub_title('Metric Score Normalization (views.py)')
pdf.formula_box(
    'NORM = (VALUE - MIN_BOUND) / (MAX_BOUND - MIN_BOUND) * 100',
    'Normalizes any metric to 0-100 scale for risk scoring',
    'observed value, min_bound, max_bound',
    'Min-max normalization',
    'dashboard/views.py'
)

# ============================================================
# SECTION 16
# ============================================================
pdf.add_page()
pdf.chapter_title('16', 'Statistical Evaluation Metrics')
pdf.set_font('Helvetica', '', 10)
pdf.set_text_color(60, 60, 60)
pdf.multi_cell(0, 5, 'Model performance is evaluated using standard regression metrics.')
pdf.ln(3)

pdf.formula_box(
    'RMSE = sqrt(MEAN((y_true - y_pred)^2))',
    'Root Mean Squared Error - penalizes large errors more heavily',
    'y_true (actual values), y_pred (predicted values)',
    'Standard regression metric',
    'train_xgboost_quick.py:65, train_lstm_quick.py:157'
)

pdf.formula_box(
    'MAE = MEAN(|y_true - y_pred|)',
    'Mean Absolute Error - average absolute deviation',
    'y_true, y_pred',
    'Standard regression metric',
    'train_xgboost_quick.py:66, train_lstm_quick.py:158'
)

pdf.formula_box(
    'R^2 = 1 - SUM((y_true-y_pred)^2) / SUM((y_true-MEAN(y_true))^2)',
    'Coefficient of determination - proportion of variance explained (0 to 1)',
    'y_true, y_pred',
    'Standard regression metric',
    'train_xgboost_quick.py:67'
)

pdf.formula_box(
    'MSE = MEAN((y_true - y_pred)^2)',
    'Mean Squared Error - training loss for both XGBoost and LSTM',
    'y_true, y_pred',
    'Standard loss function',
    'train_xgboost_quick.py, lstm_forecaster.py'
)

# Final page
pdf.add_page()
pdf.set_font('Helvetica', 'B', 20)
pdf.set_text_color(25, 60, 100)
pdf.ln(40)
pdf.cell(0, 15, 'End of Reference Manual', 0, 1, 'C')
pdf.set_draw_color(25, 60, 100)
pdf.line(60, pdf.get_y(), 150, pdf.get_y())
pdf.ln(8)
pdf.set_font('Helvetica', '', 11)
pdf.set_text_color(100, 100, 100)
pdf.multi_cell(0, 6, 'This document covers all mathematical formulas and calculation methods\nused in the APWRS drought risk assessment platform.\n\nFor the latest version, refer to the source code repository.', 0, 'C')

# Save
output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'APWRS_Formula_Reference.pdf')
pdf.output(output_path)
print(f'PDF generated: {output_path}')
print(f'Size: {os.path.getsize(output_path)/1024:.1f} KB')
print(f'Pages: {pdf.page_no()}')
