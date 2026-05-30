import os
from datetime import datetime

import numpy as np
import pandas as pd

from ..models import (
    AgriculturalMetrics,
    ClimateMetrics,
    DroughtIndices,
    HydrologyMetrics,
    ObservationYear,
    RemoteSensingMetrics,
    Region,
    SoilMetrics,
    DroughtPrediction,
)
from .llm_explainer import DroughtLLMExplainer
from .lstm_forecaster import LSTMDroughtForecaster
from .physical_helpers import (
    calculate_available_water_capacity,
    calculate_etc,
    calculate_et0,
    calculate_field_capacity,
    calculate_spi,
    calculate_vci,
    calculate_wilting_point,
    get_crop_coefficient,
    update_soil_water,
)
from .xgboost_risk_predictor import XGBoostDroughtRiskPredictor


class DroughtPredictionPipeline:
    def __init__(self):
        self.xgb_predictor = None
        self.lstm_7d = None
        self.lstm_30d = None
        self.llm_explainer = None
        self.is_trained = False
        self.field_capacity_pct = None
        self.wilting_point_pct = None
        self.available_water_capacity_mm = None

    def set_soil_properties(self, sand_pct, clay_pct, silt_pct, organic_matter_pct, root_depth_mm):
        self.field_capacity_pct = calculate_field_capacity(sand_pct, clay_pct, silt_pct, organic_matter_pct)
        self.wilting_point_pct = calculate_wilting_point(sand_pct, clay_pct, silt_pct)
        self.available_water_capacity_mm = calculate_available_water_capacity(
            self.field_capacity_pct, self.wilting_point_pct, root_depth_mm
        )
        return self

    def set_soil_properties_from_metrics(self, region, year, root_depth_mm=600):
        latest = SoilMetrics.objects.filter(region=region, year=year).order_by('-measurement_date').first()
        if latest and latest.sand_ratio is not None and latest.clay_ratio is not None and latest.silt_ratio is not None:
            return self.set_soil_properties(
                float(latest.sand_ratio),
                float(latest.clay_ratio),
                float(latest.silt_ratio),
                float(latest.organic_matter_percent or 0),
                int(latest.root_zone_depth_mm or root_depth_mm),
            )
        return self.set_soil_properties(40, 25, 35, 2.5, root_depth_mm)

    def _query_frame(self, queryset, columns):
        rows = []
        for obj in queryset:
            row = {'measurement_date': obj.measurement_date}
            for source_field, target_field in columns.items():
                value = getattr(obj, source_field)
                if hasattr(value, 'name'):
                    value = value.name
                row[target_field] = value
            rows.append(row)
        if not rows:
            return pd.DataFrame(columns=['measurement_date'] + list(columns.values()))
        return pd.DataFrame(rows)

    def build_prediction_frame(self, region, year, lookback_days=120):
        soil_df = self._query_frame(
            SoilMetrics.objects.filter(region=region, year=year).order_by('measurement_date')[:lookback_days],
            {
                'moisture_content_percent': 'soil_moisture_pct',
                'sand_ratio': 'sand_pct',
                'clay_ratio': 'clay_pct',
                'silt_ratio': 'silt_pct',
                'root_zone_depth_mm': 'root_depth_mm',
                'organic_matter_percent': 'organic_matter_pct',
                'field_capacity_percent': 'field_capacity_pct',
                'wilting_point_percent': 'wilting_point_pct',
            },
        )

        climate_df = self._query_frame(
            ClimateMetrics.objects.filter(region=region, year=year).order_by('measurement_date')[:lookback_days],
            {
                'rainfall_mm': 'rainfall_mm',
                'temperature_max_c': 'temp_max_c',
                'temperature_min_c': 'temp_min_c',
                'temperature_mean_c': 'temp_mean_c',
                'relative_humidity_percent': 'humidity_pct',
                'wind_speed_ms': 'wind_speed_ms',
                'solar_radiation_mjm2day': 'solar_radiation_mjm2day',
                'evapotranspiration_et0_mmday': 'et0_mm',
                'evapotranspiration_etc_mmday': 'etc_mm',
            },
        )

        drought_df = self._query_frame(
            DroughtIndices.objects.filter(region=region, year=year).order_by('measurement_date')[:lookback_days],
            {
                'spi_1month': 'spi',
                'spei_1month': 'spei',
                'pdsi_value': 'pdsi',
            },
        )

        remote_df = self._query_frame(
            RemoteSensingMetrics.objects.filter(region=region, year=year).order_by('measurement_date')[:lookback_days],
            {
                'ndvi': 'ndvi',
                'land_surface_temperature_c': 'lst_c',
                'satellite_soil_moisture_percent': 'satellite_soil_moisture_pct',
                'vegetation_condition_index': 'vci',
                'evapotranspiration_sebal_mmday': 'sebal_etc_mm',
            },
        )

        hydro_df = self._query_frame(
            HydrologyMetrics.objects.filter(region=region, year=year).order_by('measurement_date')[:lookback_days],
            {
                'precipitation_mm': 'precipitation_mm',
                'evapotranspiration_mm': 'hydro_et_mm',
                'groundwater_depth_m': 'groundwater_depth_m',
                'runoff_mm': 'runoff_mm',
                'river_flow_m3s': 'river_flow_m3s',
                'soil_water_deficit_index_mm': 'soil_water_deficit_mm',
                'water_balance_percent': 'water_balance_percent',
            },
        )

        agricultural_df = self._query_frame(
            AgriculturalMetrics.objects.filter(region=region, year=year).order_by('measurement_date')[:lookback_days],
            {
                'growth_stage': 'growth_stage',
                'crop_coefficient_kc': 'kc',
                'crop_water_requirement_mmday': 'crop_water_requirement_mmday',
                'yield_reduction_factor': 'yield_reduction_factor',
                'water_applied_mm': 'irrigation_mm',
                'leaf_temperature_c': 'leaf_temperature_c',
                'stomatal_conductance': 'stomatal_conductance',
            },
        )

        frames = [frame for frame in [soil_df, climate_df, drought_df, remote_df, hydro_df, agricultural_df] if not frame.empty]
        if not frames:
            raise ValueError('No metric data found for the selected region/year.')

        merged = frames[0]
        for frame in frames[1:]:
            merged = merged.merge(frame, on='measurement_date', how='outer')

        merged = merged.sort_values('measurement_date').reset_index(drop=True)

        def _fill_column(frame, column_name, default_value):
            if column_name not in frame.columns:
                frame[column_name] = default_value
            else:
                frame[column_name] = frame[column_name].fillna(method='ffill').fillna(method='bfill').fillna(default_value)

        if 'solar_radiation_mjm2day' in merged.columns and 'solar_radiation_wm2' not in merged.columns:
            merged['solar_radiation_wm2'] = merged['solar_radiation_mjm2day'] / 0.0864

        if 'temp_mean_c' not in merged.columns:
            max_series = merged['temp_max_c'] if 'temp_max_c' in merged.columns else pd.Series([0] * len(merged))
            min_series = merged['temp_min_c'] if 'temp_min_c' in merged.columns else pd.Series([0] * len(merged))
            merged['temp_mean_c'] = max_series.fillna(0) + min_series.fillna(0)
            merged['temp_mean_c'] = merged['temp_mean_c'] / 2

        if 'etc_mm' not in merged.columns:
            merged['etc_mm'] = np.nan

        if 'kc' not in merged.columns:
            merged['kc'] = 1.0

        if 'et0_mm' not in merged.columns:
            merged['et0_mm'] = merged.apply(
                lambda row: calculate_et0(
                    float(row.get('temp_mean_c', 0) or 0),
                    float(row.get('wind_speed_ms', 0) or 0),
                    float(row.get('solar_radiation_wm2', 0) or 0),
                    float(row.get('humidity_pct', 0) or 0),
                ),
                axis=1,
            )

        merged['etc_mm'] = merged['etc_mm'].fillna(merged['et0_mm'] * merged['kc']) if 'etc_mm' in merged.columns else merged['et0_mm'] * merged['kc']
        if 'soil_moisture_pct' not in merged.columns and 'satellite_soil_moisture_pct' in merged.columns:
            merged['soil_moisture_pct'] = merged['satellite_soil_moisture_pct']

        _fill_column(merged, 'soil_moisture_pct', 0)
        if 'rainfall_mm' not in merged.columns and 'precipitation_mm' in merged.columns:
            merged['rainfall_mm'] = merged['precipitation_mm']
        _fill_column(merged, 'rainfall_mm', 0)
        _fill_column(merged, 'temp_max_c', 0)
        _fill_column(merged, 'temp_min_c', 0)
        _fill_column(merged, 'humidity_pct', 0)
        _fill_column(merged, 'wind_speed_ms', 0)
        _fill_column(merged, 'ndvi', 0.5)
        _fill_column(merged, 'lst_c', 0)
        _fill_column(merged, 'spi', 0)
        _fill_column(merged, 'irrigation_mm', 0)

        if 'soil_water_mm' not in merged.columns:
            merged['soil_water_mm'] = np.nan

        return merged.tail(lookback_days).reset_index(drop=True)

    def prepare_daily_data(self, raw_df):
        df = raw_df.copy()

        if 'solar_radiation_wm2' not in df.columns and 'solar_radiation_mjm2day' in df.columns:
            df['solar_radiation_wm2'] = df['solar_radiation_mjm2day'] / 0.0864

        if 'temp_mean_c' not in df.columns:
            df['temp_mean_c'] = (df.get('temp_max_c', 0) + df.get('temp_min_c', 0)) / 2

        df['et0_mm'] = df.apply(
            lambda row: calculate_et0(
                float(row['temp_mean_c']),
                float(row.get('wind_speed_ms', 0) or 0),
                float(row.get('solar_radiation_wm2', 0) or 0),
                float(row.get('humidity_pct', 0) or 0),
            ),
            axis=1,
        )

        if 'crop_type' in df.columns and 'days_since_planting' in df.columns:
            df['kc'] = df.apply(lambda row: get_crop_coefficient(row['crop_type'], row['days_since_planting'], 120), axis=1)
        elif 'kc' not in df.columns:
            df['kc'] = 1.0

        df['etc_mm'] = df.get('etc_mm', df['et0_mm'] * df['kc']).fillna(df['et0_mm'] * df['kc']) if 'etc_mm' in df.columns else df['et0_mm'] * df['kc']

        if 'soil_water_mm' not in df.columns or df['soil_water_mm'].isna().all():
            df['soil_water_mm'] = 0.0
            if self.available_water_capacity_mm is None:
                raise ValueError('Soil properties must be set before computing water balance.')
            initial_soil_water = self.available_water_capacity_mm * 0.7
            for i in range(len(df)):
                if i == 0:
                    df.loc[df.index[i], 'soil_water_mm'] = initial_soil_water
                else:
                    prev = float(df['soil_water_mm'].iloc[i - 1])
                    rain = float(df['rainfall_mm'].iloc[i] if 'rainfall_mm' in df.columns else 0)
                    irrigation = float(df['irrigation_mm'].iloc[i] if 'irrigation_mm' in df.columns else 0)
                    etc = float(df['etc_mm'].iloc[i])
                    df.loc[df.index[i], 'soil_water_mm'] = update_soil_water(prev, rain, irrigation, etc)

        return df

    def _predict_prepared_df(self, prepared_df, use_llm=True, llm_model='llama3.2:3b'):
        self._ensure_ready()

        current_soil_moisture = prepared_df['soil_moisture_pct'].iloc[-1]
        current_soil_water_mm = prepared_df['soil_water_mm'].iloc[-1]

        risk_today = self.xgb_predictor.predict(prepared_df)
        drivers = self.xgb_predictor.get_drivers(prepared_df)
        risk_7day = self.lstm_7d.predict_risk(prepared_df, self.field_capacity_pct)
        soil_7day = self.lstm_7d.predict_soil_moisture(prepared_df)
        risk_30day = self.lstm_30d.predict_risk(prepared_df, self.field_capacity_pct)
        soil_30day = self.lstm_30d.predict_soil_moisture(prepared_df)

        llm_explanation = None
        if use_llm:
            if self.llm_explainer is None:
                self.llm_explainer = DroughtLLMExplainer(model_name=llm_model)
            llm_explanation = self.llm_explainer.generate_explanation(
                risk_today,
                risk_7day,
                risk_30day,
                drivers,
                current_soil_moisture,
                self.available_water_capacity_mm,
            )

        return {
            'location': {
                'field_capacity_pct': self.field_capacity_pct,
                'wilting_point_pct': self.wilting_point_pct,
                'available_water_capacity_mm': self.available_water_capacity_mm,
            },
            'current': {
                'soil_moisture_pct': current_soil_moisture,
                'soil_water_mm': current_soil_water_mm,
                'soil_water_percent_of_capacity': round(
                    current_soil_water_mm / self.available_water_capacity_mm * 100, 1
                ) if self.available_water_capacity_mm > 0 else 0,
            },
            'risk_scores': {
                'today': risk_today,
                'day_7': risk_7day,
                'day_30': risk_30day,
            },
            'drivers': drivers,
            'forecasts': {
                'soil_moisture_7day_pct': soil_7day,
                'soil_moisture_30day_pct': soil_30day,
            },
            'llm_explanation': llm_explanation,
        }

    def train(self, historical_df, sand_pct, clay_pct, silt_pct, organic_matter_pct, root_depth_mm):
        self.set_soil_properties(sand_pct, clay_pct, silt_pct, organic_matter_pct, root_depth_mm)
        prepared_df = self.prepare_daily_data(historical_df)

        self.xgb_predictor = XGBoostDroughtRiskPredictor()
        self.xgb_predictor.train(prepared_df, self.available_water_capacity_mm, self.field_capacity_pct)

        self.lstm_7d = LSTMDroughtForecaster(sequence_length=30, n_features=10)
        self.lstm_7d.train(prepared_df, forecast_days=7, epochs=50)

        self.lstm_30d = LSTMDroughtForecaster(sequence_length=60, n_features=10)
        self.lstm_30d.train(prepared_df, forecast_days=30, epochs=50)

        self.is_trained = True
        return self

    def load(self, model_dir='./'):
        self.xgb_predictor = XGBoostDroughtRiskPredictor().load(
            f'{model_dir}/xgboost_risk_model.pkl',
            f'{model_dir}/xgboost_scaler.pkl',
            f'{model_dir}/xgboost_features.pkl',
        )
        self.lstm_7d = LSTMDroughtForecaster(sequence_length=30, n_features=10).load(
            forecast_days=7,
            model_path=f'{model_dir}/lstm_7day_best.pth',
            stats_path=f'{model_dir}/lstm_7day_stats.npz',
        )
        self.lstm_30d = LSTMDroughtForecaster(sequence_length=60, n_features=10).load(
            forecast_days=30,
            model_path=f'{model_dir}/lstm_30day_best.pth',
            stats_path=f'{model_dir}/lstm_30day_stats.npz',
        )
        self.is_trained = True
        return self

    def _ensure_ready(self):
        if not self.is_trained:
            raise ValueError('Models not trained or loaded. Call train() or load() first.')

    def _artifact_path(self, filename):
        return os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')), filename)

    def _heuristic_driver_scores(self, prepared_df):
        rainfall_30d = float(prepared_df['rainfall_mm'].tail(30).sum()) if 'rainfall_mm' in prepared_df.columns else 0
        rainfall_7d = float(prepared_df['rainfall_mm'].tail(7).sum()) if 'rainfall_mm' in prepared_df.columns else 0
        soil_trend = float(prepared_df['soil_moisture_pct'].tail(7).diff().mean()) if 'soil_moisture_pct' in prepared_df.columns else 0
        temp_anomaly = float(prepared_df['temp_max_c'].iloc[-1] - prepared_df['temp_max_c'].tail(30).mean()) if 'temp_max_c' in prepared_df.columns else 0
        ndvi = float(prepared_df['ndvi'].iloc[-1]) if 'ndvi' in prepared_df.columns else 0.5
        etc_avg = float(prepared_df['etc_mm'].tail(7).mean()) if 'etc_mm' in prepared_df.columns else 3.0

        scores = {
            'rainfall_deficit': max(0, 100 - min(100, (rainfall_30d / 30) * 10)) + max(0, 100 - min(100, rainfall_7d * 10)),
            'soil_moisture_decline': max(0, min(100, abs(soil_trend) * 300)),
            'high_temperature': max(0, min(100, temp_anomaly * 15)),
            'vegetation_stress': max(0, min(100, (1 - ndvi) * 100)),
            'high_evapotranspiration': max(0, min(100, etc_avg * 20)),
        }

        total = sum(scores.values()) or 1
        return {key: round((value / total) * 100, 1) for key, value in scores.items()}

    def _heuristic_prediction(self, prepared_df, use_llm=True, llm_model='llama3.2:3b'):
        current_soil_moisture = float(prepared_df['soil_moisture_pct'].iloc[-1]) if 'soil_moisture_pct' in prepared_df.columns else 0
        current_soil_water_mm = float(prepared_df['soil_water_mm'].iloc[-1]) if 'soil_water_mm' in prepared_df.columns else 0
        rainfall_30d = float(prepared_df['rainfall_mm'].tail(30).sum()) if 'rainfall_mm' in prepared_df.columns else 0
        rainfall_7d = float(prepared_df['rainfall_mm'].tail(7).sum()) if 'rainfall_mm' in prepared_df.columns else 0
        soil_trend = float(prepared_df['soil_moisture_pct'].tail(7).diff().mean()) if 'soil_moisture_pct' in prepared_df.columns else 0
        ndvi = float(prepared_df['ndvi'].iloc[-1]) if 'ndvi' in prepared_df.columns else 0.5
        spi_value = float(prepared_df['spi'].iloc[-1]) if 'spi' in prepared_df.columns and len(prepared_df) else 0

        if self.available_water_capacity_mm and self.available_water_capacity_mm > 0:
            soil_risk = (1 - min(1, current_soil_water_mm / self.available_water_capacity_mm)) * 100
        elif self.field_capacity_pct:
            soil_risk = (1 - min(1, current_soil_moisture / self.field_capacity_pct)) * 100
        else:
            soil_risk = max(0, 100 - current_soil_moisture)

        ndvi_penalty = max(0, (0.8 - min(0.8, ndvi)) / 0.8) * 20
        spi_penalty = max(0, -spi_value) * 10
        risk_today = round(min(100, soil_risk + ndvi_penalty + spi_penalty), 1)

        decline_factor = max(0, min(2.0, abs(soil_trend) * 10))
        rainfall_relief = max(0, min(20, rainfall_7d * 1.5))
        risk_7day = round(max(0, min(100, risk_today + (decline_factor * 8) - rainfall_relief * 0.5)), 1)
        risk_30day = round(max(0, min(100, risk_today + (decline_factor * 18) - rainfall_relief)), 1)

        soil_7day = round(max(0, min(100, current_soil_moisture + (soil_trend * 7))), 1)
        soil_30day = round(max(0, min(100, current_soil_moisture + (soil_trend * 30))), 1)

        drivers = self._heuristic_driver_scores(prepared_df)

        llm_explanation = None
        if use_llm:
            self.llm_explainer = DroughtLLMExplainer(model_name=llm_model)
            llm_explanation = self.llm_explainer.generate_explanation(
                risk_today,
                risk_7day,
                risk_30day,
                drivers,
                current_soil_moisture,
                self.available_water_capacity_mm or 1,
            )

        return {
            'prediction_mode': 'heuristic',
            'location': {
                'field_capacity_pct': self.field_capacity_pct,
                'wilting_point_pct': self.wilting_point_pct,
                'available_water_capacity_mm': self.available_water_capacity_mm,
            },
            'current': {
                'soil_moisture_pct': current_soil_moisture,
                'soil_water_mm': current_soil_water_mm,
                'soil_water_percent_of_capacity': round(
                    current_soil_water_mm / self.available_water_capacity_mm * 100, 1
                ) if self.available_water_capacity_mm and self.available_water_capacity_mm > 0 else 0,
            },
            'risk_scores': {
                'today': risk_today,
                'day_7': risk_7day,
                'day_30': risk_30day,
            },
            'drivers': drivers,
            'forecasts': {
                'soil_moisture_7day_pct': soil_7day,
                'soil_moisture_30day_pct': soil_30day,
            },
            'llm_explanation': llm_explanation,
        }

    def predict(self, last_30_days_df, use_llm=True, llm_model='llama3.2:3b'):
        prepared_df = self.prepare_daily_data(last_30_days_df)
        if self.is_trained:
            return self._predict_prepared_df(prepared_df, use_llm=use_llm, llm_model=llm_model)
        return self._heuristic_prediction(prepared_df, use_llm=use_llm, llm_model=llm_model)

    def predict_for_region(self, region, year, use_llm=True, llm_model='llama3.2:3b', lookback_days=120):
        self.set_soil_properties_from_metrics(region, year)
        prepared_df = self.prepare_daily_data(self.build_prediction_frame(region, year, lookback_days=lookback_days))
        model_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        model_paths = [
            self._artifact_path('xgboost_risk_model.pkl'),
            self._artifact_path('xgboost_scaler.pkl'),
            self._artifact_path('xgboost_features.pkl'),
            self._artifact_path('lstm_7day_best.pth'),
            self._artifact_path('lstm_7day_stats.npz'),
            self._artifact_path('lstm_30day_best.pth'),
            self._artifact_path('lstm_30day_stats.npz'),
        ]

        if all(os.path.exists(path) for path in model_paths):
            try:
                self.load(model_dir=model_dir)
            except Exception:
                pass

        if self.is_trained:
            return self._predict_prepared_df(prepared_df, use_llm=use_llm, llm_model=llm_model)
        return self._heuristic_prediction(prepared_df, use_llm=use_llm, llm_model=llm_model)

    def save_prediction(self, region, year, result, source_window_days=120, model_version='v1'):
        return DroughtPrediction.objects.create(
            region=region,
            year=year,
            model_version=model_version,
            current_risk_score=result['risk_scores']['today'],
            risk_7day=result['risk_scores']['day_7'],
            risk_30day=result['risk_scores']['day_30'],
            soil_moisture_today_pct=result['current']['soil_moisture_pct'],
            soil_moisture_7day_pct=result['forecasts']['soil_moisture_7day_pct'],
            soil_moisture_30day_pct=result['forecasts']['soil_moisture_30day_pct'],
            drivers=result.get('drivers', {}),
            explanation=result.get('llm_explanation', '') or '',
            source_window_days=source_window_days,
        )