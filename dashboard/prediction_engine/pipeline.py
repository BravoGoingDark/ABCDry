import logging
import os
from datetime import datetime

import numpy as np
import pandas as pd

from decimal import Decimal

logger = logging.getLogger(__name__)

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
from .rainfall_forecast import build_next_days_rain, climatological_daily_rain
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
        self.xgb_forecast_7d = None
        self.xgb_forecast_30d = None
        self.lstm_7d = None
        self.lstm_30d = None
        self.llm_explainer = None
        self.is_trained = False
        self.field_capacity_pct = None
        self.wilting_point_pct = None
        self.available_water_capacity_mm = None
        self.validation_metrics = {}
        self.model_trained_at = None

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
                elif isinstance(value, Decimal):
                    value = float(str(value))
                row[target_field] = value
            rows.append(row)
        if not rows:
            return pd.DataFrame(columns=['measurement_date'] + list(columns.values()))
        return pd.DataFrame(rows)

    def build_prediction_frame(self, region, year=None, lookback_days=120):
        def scoped(queryset):
            if year is not None:
                queryset = queryset.filter(year=year)
            if lookback_days is not None:
                queryset = queryset[:lookback_days]
            return queryset

        soil_df = self._query_frame(
            scoped(SoilMetrics.objects.filter(region=region).order_by('-measurement_date')),
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
            scoped(ClimateMetrics.objects.filter(region=region).order_by('-measurement_date')),
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
            scoped(DroughtIndices.objects.filter(region=region).order_by('-measurement_date')),
            {
                'spi_1month': 'spi',
                'spi_3month': 'spi3',
                'spei_1month': 'spei',
                'pdsi_value': 'pdsi',
            },
        )

        remote_df = self._query_frame(
            scoped(RemoteSensingMetrics.objects.filter(region=region).order_by('-measurement_date')),
            {
                'ndvi': 'ndvi',
                'land_surface_temperature_c': 'lst_c',
                'satellite_soil_moisture_percent': 'satellite_soil_moisture_pct',
                'vegetation_condition_index': 'vci',
                'evapotranspiration_sebal_mmday': 'sebal_etc_mm',
            },
        )

        hydro_df = self._query_frame(
            scoped(HydrologyMetrics.objects.filter(region=region).order_by('-measurement_date')),
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
            scoped(AgriculturalMetrics.objects.filter(region=region).order_by('-measurement_date')),
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
        merged = merged.ffill().bfill()

        if 'soil_moisture_pct' not in merged.columns and 'satellite_soil_moisture_pct' in merged.columns:
            merged['soil_moisture_pct'] = merged['satellite_soil_moisture_pct']

        if 'soil_water_mm' not in merged.columns:
            merged['soil_water_mm'] = np.nan

        if lookback_days is not None:
            merged = merged.tail(lookback_days)
        return merged.reset_index(drop=True)

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

        if 'etc_mm' in df.columns:
            df['etc_mm'] = df['etc_mm'].fillna(df['et0_mm'] * df['kc'])
        else:
            df['etc_mm'] = df['et0_mm'] * df['kc']

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
                    cn = 70.0
                    s_mm = 254 * (100 / cn - 1)
                    runoff = ((rain - 0.2 * s_mm) ** 2) / (rain + 0.8 * s_mm) if rain > 0.2 * s_mm else 0.0
                    df.loc[df.index[i], 'soil_water_mm'] = update_soil_water(prev, rain, irrigation, etc, runoff, awc_mm=self.available_water_capacity_mm)

        # Convert water-balance soil_water_mm to a soil moisture percentage.
        # This replaces unreliable satellite point readings (e.g. SMAP over a lake)
        # with a physically-based estimate derived from the weather data we already
        # collect: rainfall, temperature, wind, humidity, solar radiation.
        if self.available_water_capacity_mm and self.available_water_capacity_mm > 0 and self.field_capacity_pct:
            df['soil_moisture_pct'] = (
                df['soil_water_mm'] / self.available_water_capacity_mm
            ) * self.field_capacity_pct

        return df

    def _predict_prepared_df(self, prepared_df, use_llm=True, llm_model='llama3.2:3b'):
        self._ensure_ready()

        current_soil_moisture = prepared_df['soil_moisture_pct'].iloc[-1]
        current_soil_water_mm = prepared_df['soil_water_mm'].iloc[-1]

        risk_today = self.xgb_predictor.predict(prepared_df)
        drivers = self.xgb_predictor.get_drivers(prepared_df)

        if self.lstm_7d is not None:
            soil_7day = self.lstm_7d.predict_soil_moisture(prepared_df)
        else:
            _, soil_7day = self._heuristic_forecast(prepared_df, horizon_days=7)

        if self.lstm_30d is not None:
            soil_30day = self.lstm_30d.predict_soil_moisture(prepared_df)
        else:
            _, soil_30day = self._heuristic_forecast(prepared_df, horizon_days=30)

        if self.xgb_forecast_7d is not None and self.xgb_forecast_30d is not None:
            risk_7day = self.xgb_forecast_7d.predict(prepared_df)
            risk_30day = self.xgb_forecast_30d.predict(prepared_df)
        else:
            if self.lstm_7d is not None:
                risk_7day = self.lstm_7d.predict_risk(prepared_df, self.field_capacity_pct)
            else:
                risk_7day, _ = self._heuristic_forecast(prepared_df, horizon_days=7)
            if self.lstm_30d is not None:
                risk_30day = self.lstm_30d.predict_risk(prepared_df, self.field_capacity_pct)
            else:
                risk_30day, _ = self._heuristic_forecast(prepared_df, horizon_days=30)

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
            'prediction_mode': 'ml_model',
            'location': {
                'field_capacity_pct': self.field_capacity_pct,
                'wilting_point_pct': self.wilting_point_pct,
                'available_water_capacity_mm': self.available_water_capacity_mm,
            },
            'current': {
                'soil_moisture_pct': current_soil_moisture,
                'soil_water_mm': current_soil_water_mm,
                'soil_water_percent_of_capacity': round(
                    current_soil_moisture / self.field_capacity_pct * 100, 1
                ) if self.field_capacity_pct and self.field_capacity_pct > 0 else 0,
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

    # ── Forecast-augmented SPI-3 risk (GFS/ECMWF rainfall + climatology) ──

    def _observed_daily_rain(self, region, end_date=None):
        rows = []
        qs = ClimateMetrics.objects.filter(region=region, rainfall_mm__isnull=False).order_by('measurement_date')
        end = pd.Timestamp(end_date).date() if end_date is not None else None
        for obj in qs:
            d = self._naive(pd.Timestamp(obj.measurement_date))
            if end is not None and d.date() > end:
                break
            rows.append((d, float(obj.rainfall_mm)))
        if not rows:
            return pd.Series(dtype='float64')
        return pd.Series([r[1] for r in rows], index=pd.DatetimeIndex([r[0] for r in rows]), dtype='float64')

    @staticmethod
    def _naive(ts):
        return ts if ts.tzinfo is None else ts.tz_localize(None)

    def forecast_spi_risk(self, region, end_date, horizon_days, expected_rain=None):
        """SPI-3 risk at end_date + horizon_days, computed directly from the
        standard SPI method over observed rainfall (through end_date) extended
        by an expected-rainfall scenario for the following horizon days.

        expected_rain: pd.Series indexed by the future dates, or None to use
        climatology. Returns None if there is not enough history."""
        observed = self._observed_daily_rain(region, end_date)
        if len(observed) < 370:
            return None
        if expected_rain is None:
            expected_rain = climatological_daily_rain(region, end_date + pd.Timedelta(days=1), horizon_days)

        future_dates = pd.date_range(start=end_date + pd.Timedelta(days=1), periods=horizon_days, freq='D')
        expected = pd.Series(
            [float(expected_rain.loc[d]) for d in future_dates],
            index=future_dates,
            dtype='float64',
        )
        extended = pd.concat([observed, expected])
        spi3 = calculate_spi(extended, nmonth=3)
        if spi3.empty:
            return None
        spi = float(spi3.iloc[-1])
        if pd.isna(spi):
            return None
        return {
            'risk': round(max(0.0, min(100.0, 50.0 - spi * 15.0)), 1),
            'spi3': spi,
            'horizon_days': horizon_days,
        }

    def _forecast_risk_block(self, region, end_date=None, lat=None, lon=None):
        if end_date is None:
            latest = ClimateMetrics.objects.filter(region=region).order_by('-measurement_date').first()
            end_date = self._naive(pd.Timestamp(latest.measurement_date)) if latest else pd.Timestamp.today().normalize()
        else:
            end_date = self._naive(pd.Timestamp(end_date))
        if lat is None or lon is None:
            lat = float(region.latitude) if region.latitude is not None else None
            lon = float(region.longitude) if region.longitude is not None else None

        block = {'day_7': None, 'day_30': None, 'rain_7d_mm': None, 'rain_30d_mm': None,
                 'source': 'climatology', 'n_forecast_days': 0}

        scenario7, meta7 = build_next_days_rain(region, end_date + pd.Timedelta(days=1), 7, lat=lat, lon=lon)
        risk7 = self.forecast_spi_risk(region, end_date, 7, expected_rain=scenario7)
        if risk7:
            block['day_7'] = risk7

        scenario30, meta30 = build_next_days_rain(region, end_date + pd.Timedelta(days=1), 30, lat=lat, lon=lon)
        risk30 = self.forecast_spi_risk(region, end_date, 30, expected_rain=scenario30)
        if risk30:
            block['day_30'] = risk30

        block['rain_7d_mm'] = meta7.get('rain_7d_mm')
        block['rain_30d_mm'] = meta30.get('rain_30d_mm')
        block['source'] = meta30.get('source', 'climatology')
        block['n_forecast_days'] = meta30.get('n_forecast_days', 0)
        return block

    def _warning_block(self, metrics=None):
        metrics = metrics or self.validation_metrics or {}
        spi = metrics.get('spi_forecast') or {}

        def conf(m, fallback):
            f1 = (m or {}).get('drought_f1')
            return round(f1 * 100) if isinstance(f1, (int, float)) else fallback

        # The values served at +7d / +30d come from the forecast-augmented
        # SPI-3 method (GFS + climatology), NOT the XGBoost forecast models.
        # So their confidence must come from the SPI-forecast backtest, using
        # the honest realistic scenario for each horizon (3 real days for +7d,
        # 7 real days for +30d). Falls back to the XGBoost F1 if unavailable.
        def spi_conf(horizon, mode, fallback):
            m = (((spi.get(horizon) or {}).get('scenarios')) or {}).get(mode)
            f1 = (m or {}).get('drought_f1')
            if isinstance(f1, (int, float)) and f1 > 0:
                return round(f1 * 100)
            return fallback

        return {
            'today': {'status': 'operational', 'confidence_pct': conf(metrics.get('nowcast'), 80)},
            'day_7': {'status': 'operational',
                      'confidence_pct': spi_conf('7', 'forecast3_plus_clim',
                                                 conf(metrics.get('forecast_7d'), 55))},
            'day_30': {'status': 'trend_only',
                       'confidence_pct': spi_conf('30', 'forecast7_plus_clim',
                                                  conf(metrics.get('forecast_30d'), 40))},
            'note': ('The 7-day horizon is operational. The 30-day figure is trend-only: it reflects '
                     'the GFS rainfall forecast blended with climatology, not a firm prediction.'),
        }

    def _spi_forecast_metrics(self, region, step=3):
        """Backtested skill of the served forecast-SPI method (cached per instance)."""
        if getattr(self, '_spi_cache', None) is None:
            self._spi_cache = {}
        if region.id in self._spi_cache:
            return self._spi_cache[region.id]
        result = {}
        for horizon in (7, 30):
            try:
                bt = self.validate_spi_forecast(region, horizon_days=horizon, step=step)
            except Exception as exc:
                logger.warning('SPI-forecast backtest %dd failed for %s: %s', horizon, region, exc)
                bt = None
            if bt:
                result[str(horizon)] = bt
        self._spi_cache[region.id] = result
        return result

    def validate_spi_forecast(self, region, horizon_days, step=3):
        """Backtest the forecast-augmented SPI-3 method over the 2023+ validation
        period, comparing rainfall scenarios against the observed SPI-3:
          * climatology          — no forecast information (baseline)
          * forecast7_plus_clim  — real rain for the first 7 days, then climatology
                                   (honest proxy for GFS skill at a 30-day horizon)
          * forecast3_plus_clim  — real rain for the first 3 days, then climatology
                                   (honest proxy for GFS skill at a 7-day horizon)
          * perfect              — real rain for the whole horizon (upper ceiling)
        Returns metrics per scenario, or None if history is insufficient."""
        from dashboard.models import DroughtIndices

        rain = self._observed_daily_rain(region)
        idx_qs = list(DroughtIndices.objects.filter(region=region, spi_3month__isnull=False)
                      .order_by('measurement_date'))
        if len(rain) < 740 or len(idx_qs) < 740:
            return None

        actual = pd.Series(
            [float(i.spi_3month) for i in idx_qs],
            index=pd.DatetimeIndex([self._naive(pd.Timestamp(i.measurement_date)) for i in idx_qs]),
        )
        actual_risk = np.clip(50.0 - actual * 15.0, 0, 100)

        eval_dates = [d for d in actual.index if d >= pd.Timestamp('2023-01-01')][::step]
        if not eval_dates:
            return None

        results = {'climatology': [], 'forecast7_plus_clim': [], 'perfect': []}
        if horizon_days > 3:
            results['forecast3_plus_clim'] = []
        target_dates = []
        for t in eval_dates:
            target = t + pd.Timedelta(days=horizon_days)
            if target not in actual_risk.index:
                continue
            target_dates.append(target)
            observed = rain[rain.index <= t]
            if len(observed) < 370:
                continue
            future = pd.date_range(start=t + pd.Timedelta(days=1), periods=horizon_days, freq='D')
            actual_rain = rain.reindex(future)

            clim = climatological_daily_rain(region, future[0], horizon_days)
            scenarios = {
                'climatology': clim,
                'forecast7_plus_clim': actual_rain.iloc[:7].combine_first(
                    clim.iloc[7:]
                ) if horizon_days >= 7 else actual_rain,
                'perfect': actual_rain,
            }
            if horizon_days > 3:
                scenarios['forecast3_plus_clim'] = actual_rain.iloc[:3].combine_first(clim.iloc[3:])
            for mode, expected in scenarios.items():
                extended = pd.concat([observed, expected])
                spi3 = calculate_spi(extended, nmonth=3)
                if spi3.empty or pd.isna(spi3.iloc[-1]):
                    results[mode].append(None)
                    continue
                results[mode].append(50.0 - float(spi3.iloc[-1]) * 15.0)

        metrics = {}
        for mode, preds in results.items():
            pairs = [(p, float(actual_risk.loc[t])) for p, t in zip(preds, target_dates) if p is not None]
            if len(pairs) < 30:
                metrics[mode] = None
                continue
            pred = np.array([p[0] for p in pairs])
            true = np.array([p[1] for p in pairs])
            residuals = pred - true
            ss_res = float(np.sum(residuals ** 2))
            ss_tot = float(np.sum((true - np.mean(true)) ** 2))
            drought = true >= 65.0
            hit = (pred >= 65.0) & drought
            alarm = pred >= 65.0
            precision = float(hit.sum() / alarm.sum()) if alarm.sum() else 0.0
            recall = float(hit.sum() / drought.sum()) if drought.sum() else 0.0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
            metrics[mode] = {
                'n_samples': len(pairs),
                'mae': round(float(np.mean(np.abs(residuals))), 2),
                'rmse': round(float(np.sqrt(np.mean(residuals ** 2))), 2),
                'r2': round(1 - ss_res / ss_tot, 3) if ss_tot > 0 else 0.0,
                'drought_days_total': int(drought.sum()),
                'drought_days_caught': int(hit.sum()),
                'drought_precision': round(precision, 3),
                'drought_recall': round(recall, 3),
                'drought_f1': round(f1, 3),
            }
        return {'horizon_days': horizon_days, 'scenarios': metrics, 'period': '2023-01-01 ->'}

    def train(self, historical_df, sand_pct=None, clay_pct=None, silt_pct=None,
              organic_matter_pct=None, root_depth_mm=None, epochs=50, skip_lstm=False):
        if sand_pct is not None:
            self.set_soil_properties(sand_pct, clay_pct, silt_pct, organic_matter_pct, root_depth_mm)
        prepared_df = self.prepare_daily_data(historical_df)

        self.xgb_predictor = XGBoostDroughtRiskPredictor(horizon_days=0)
        self.xgb_predictor.train(prepared_df)
        self.xgb_forecast_7d = XGBoostDroughtRiskPredictor(horizon_days=7)
        self.xgb_forecast_7d.train(prepared_df)
        self.xgb_forecast_30d = XGBoostDroughtRiskPredictor(horizon_days=30)
        self.xgb_forecast_30d.train(prepared_df)

        self.lstm_7d = None
        self.lstm_30d = None
        if not skip_lstm:
            self.lstm_7d = LSTMDroughtForecaster(sequence_length=30)
            self.lstm_7d.train(prepared_df, forecast_days=7, epochs=epochs)
            self.lstm_30d = LSTMDroughtForecaster(sequence_length=60)
            self.lstm_30d.train(prepared_df, forecast_days=30, epochs=epochs)

        self.validation_metrics = {
            'nowcast': self.xgb_predictor.validation_metrics,
            'forecast_7d': self.xgb_forecast_7d.validation_metrics,
            'forecast_30d': self.xgb_forecast_30d.validation_metrics,
        }
        self.model_trained_at = self.xgb_predictor.train_date
        self.is_trained = True
        try:
            import json
            with open(self._artifact_path('xgboost_validation_metrics.json'), 'w') as vf:
                json.dump({'validation_metrics': self.validation_metrics,
                           'model_trained_at': self.model_trained_at}, vf)
        except Exception as exc:
            logger.warning('Could not persist validation metrics artifact: %s', exc)
        return self

    def build_history_frame(self, region, lookback_days=None):
        return self.build_prediction_frame(region, year=None, lookback_days=lookback_days)

    def load(self, model_dir='./'):
        self.xgb_predictor = XGBoostDroughtRiskPredictor(horizon_days=0).load(
            model_path=f'{model_dir}/xgboost_risk_model.pkl',
            scaler_path=f'{model_dir}/xgboost_scaler.pkl',
            features_path=f'{model_dir}/xgboost_features.pkl',
        )

        self.xgb_forecast_7d = None
        self.xgb_forecast_30d = None
        for horizon, attr in ((7, 'xgb_forecast_7d'), (30, 'xgb_forecast_30d')):
            try:
                setattr(self, attr, XGBoostDroughtRiskPredictor(horizon_days=horizon).load(
                    model_path=f'{model_dir}/xgboost_risk_model_{horizon}d.pkl',
                    scaler_path=f'{model_dir}/xgboost_scaler_{horizon}d.pkl',
                    features_path=f'{model_dir}/xgboost_features_{horizon}d.pkl',
                ))
            except Exception as exc:
                logger.warning('XGBoost %dd forecast model not loaded: %s', horizon, exc)
                setattr(self, attr, None)

        self.lstm_7d = None
        self.lstm_30d = None
        for horizon, attr, model_file, stats_file in (
            (7, 'lstm_7d', 'lstm_7day_best.pth', 'lstm_7day_stats.npz'),
            (30, 'lstm_30d', 'lstm_30day_best.pth', 'lstm_30day_stats.npz'),
        ):
            try:
                setattr(self, attr, LSTMDroughtForecaster(sequence_length=30 if horizon == 7 else 60).load(
                    forecast_days=horizon,
                    model_path=f'{model_dir}/{model_file}',
                    stats_path=f'{model_dir}/{stats_file}',
                ))
            except Exception as exc:
                logger.warning('LSTM %dd model not loaded: %s', horizon, exc)
                setattr(self, attr, None)

        self.is_trained = True
        try:
            import json
            with open(self._artifact_path('xgboost_validation_metrics.json')) as vf:
                data = json.load(vf)
            self.validation_metrics = data.get('validation_metrics', {}) or {}
            self.model_trained_at = data.get('model_trained_at')
        except Exception as exc:
            logger.warning('Validation metrics artifact not loaded: %s', exc)
        return self

    def _ensure_ready(self):
        if not self.is_trained:
            raise ValueError('Models not trained or loaded. Call train() or load() first.')

    def _artifact_path(self, filename):
        return os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')), filename)

    def _heuristic_forecast(self, prepared_df, horizon_days):
        current_soil_moisture = float(prepared_df['soil_moisture_pct'].iloc[-1]) if 'soil_moisture_pct' in prepared_df.columns else 0
        soil_trend = float(prepared_df['soil_moisture_pct'].tail(7).diff().mean()) if 'soil_moisture_pct' in prepared_df.columns else 0
        rainfall_7d = float(prepared_df['rainfall_mm'].tail(7).sum()) if 'rainfall_mm' in prepared_df.columns else 0

        if self.field_capacity_pct and self.field_capacity_pct > 0:
            risk_now = max(0, (1 - min(1, current_soil_moisture / self.field_capacity_pct)) * 100)
        else:
            risk_now = max(0, 100 - current_soil_moisture)

        decline_factor = max(0, min(2.0, abs(soil_trend) * 10))
        rainfall_relief = max(0, min(20, rainfall_7d * 1.5))
        risk = round(max(0, min(100, risk_now + (decline_factor * horizon_days * 0.6) - rainfall_relief * (horizon_days / 30))), 1)
        soil = round(max(0, min(100, current_soil_moisture + (soil_trend * horizon_days))), 1)
        return risk, soil

    def _heuristic_driver_scores(self, prepared_df):
        rainfall_30d = float(prepared_df['rainfall_mm'].tail(30).sum()) if 'rainfall_mm' in prepared_df.columns else 0
        rainfall_7d = float(prepared_df['rainfall_mm'].tail(7).sum()) if 'rainfall_mm' in prepared_df.columns else 0
        soil_trend = float(prepared_df['soil_moisture_pct'].tail(7).diff().mean()) if 'soil_moisture_pct' in prepared_df.columns else 0
        temp_latest = float(prepared_df['temp_max_c'].iloc[-1]) if 'temp_max_c' in prepared_df.columns else 25
        temp_anomaly = float(temp_latest - prepared_df['temp_max_c'].tail(30).mean()) if 'temp_max_c' in prepared_df.columns else 0
        temp_absolute_penalty = max(0, temp_latest - 28) * 5  # 0 at 28°C, 35 at 35°C, 60 at 40°C
        ndvi_raw = prepared_df['ndvi'].iloc[-1] if 'ndvi' in prepared_df.columns else None
        ndvi = ndvi_raw if isinstance(ndvi_raw, (int, float)) and not (isinstance(ndvi_raw, float) and np.isnan(ndvi_raw)) else None
        etc_avg = float(prepared_df['etc_mm'].tail(7).mean()) if 'etc_mm' in prepared_df.columns else 3.0

        abs_scores = {
            'rainfall_deficit': round(max(0, 100 - min(100, (rainfall_30d / 30) * 10)) + max(0, 100 - min(100, rainfall_7d * 10)), 1),
            'soil_moisture_decline': round(max(0, min(100, abs(soil_trend) * 300)), 1),
            'high_temperature': round(max(0, min(100, temp_anomaly * 15 + temp_absolute_penalty)), 1),
            'vegetation_stress': round(max(0, min(100, (1 - ndvi) * 100)), 1) if ndvi is not None else 0.0,
            'high_evapotranspiration': round(max(0, min(100, etc_avg * 20)), 1),
        }

        total = sum(abs_scores.values()) or 1
        norm = {key: round((value / total) * 100, 1) for key, value in abs_scores.items()}

        return {**norm, 'absolute': abs_scores}

    def _heuristic_prediction(self, prepared_df, use_llm=True, llm_model='llama3.2:3b'):
        current_soil_moisture = float(prepared_df['soil_moisture_pct'].iloc[-1]) if 'soil_moisture_pct' in prepared_df.columns else 0
        current_soil_water_mm = float(prepared_df['soil_water_mm'].iloc[-1]) if 'soil_water_mm' in prepared_df.columns else 0
        rainfall_30d = float(prepared_df['rainfall_mm'].tail(30).sum()) if 'rainfall_mm' in prepared_df.columns else 0
        rainfall_7d = float(prepared_df['rainfall_mm'].tail(7).sum()) if 'rainfall_mm' in prepared_df.columns else 0
        soil_trend = float(prepared_df['soil_moisture_pct'].tail(7).diff().mean()) if 'soil_moisture_pct' in prepared_df.columns else 0
        ndvi = float(prepared_df['ndvi'].iloc[-1]) if 'ndvi' in prepared_df.columns else 0.5
        spi_value = float(prepared_df['spi'].iloc[-1]) if 'spi' in prepared_df.columns and len(prepared_df) else 0

        if self.field_capacity_pct and self.field_capacity_pct > 0:
            soil_risk = max(0, (1 - min(1, current_soil_moisture / self.field_capacity_pct)) * 100)
        elif self.available_water_capacity_mm and self.available_water_capacity_mm > 0:
            soil_risk = (1 - min(1, current_soil_water_mm / self.available_water_capacity_mm)) * 100
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
            if self.llm_explainer is None:
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
                    current_soil_moisture / self.field_capacity_pct * 100, 1
                ) if self.field_capacity_pct and self.field_capacity_pct > 0 else 0,
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
        if not self.is_trained and os.path.exists(self._artifact_path('xgboost_risk_model.pkl')):
            try:
                self.load(model_dir=model_dir)
                logger.info('Loaded ML models from %s', model_dir)
            except Exception as exc:
                logger.warning('Model load failed (will use heuristic): %s', exc)

        if self.is_trained:
            result = self._predict_prepared_df(prepared_df, use_llm=use_llm, llm_model=llm_model)
        else:
            result = self._heuristic_prediction(prepared_df, use_llm=use_llm, llm_model=llm_model)

        # Override the 7d / 30d risk with the GFS-forecast-augmented SPI-3
        # method when it can be computed (falls back to the ML/heuristic values).
        try:
            forecast_block = self._forecast_risk_block(region)
        except Exception as exc:
            logger.warning('Rainfall-forecast risk unavailable for %s: %s', region, exc)
            forecast_block = None

        if forecast_block:
            if forecast_block.get('day_7'):
                result['risk_scores']['day_7'] = forecast_block['day_7']['risk']
            if forecast_block.get('day_30'):
                result['risk_scores']['day_30'] = forecast_block['day_30']['risk']
            result['rainfall_forecast'] = forecast_block

        # Backtested skill of the served SPI-forecast method, used for the
        # +7d / +30d confidence labels (computed once per region).
        try:
            spi_metrics = self._spi_forecast_metrics(region)
            if spi_metrics:
                self.validation_metrics = {**(self.validation_metrics or {}), 'spi_forecast': spi_metrics}
        except Exception as exc:
            logger.warning('SPI-forecast metrics unavailable for %s: %s', region, exc)

        result['warning'] = self._warning_block()
        return result

    def save_prediction(self, region, year, result, source_window_days=120, model_version='v1',
                        model_trained_at=None, validation_metrics=None):
        rf = result.get('rainfall_forecast', {}) or {}
        return DroughtPrediction.objects.create(
            region=region,
            year=year,
            model_version=model_version,
            model_trained_at=model_trained_at,
            validation_metrics=validation_metrics or {},
            current_risk_score=result['risk_scores']['today'],
            risk_7day=result['risk_scores']['day_7'],
            risk_30day=result['risk_scores']['day_30'],
            soil_moisture_today_pct=result['current']['soil_moisture_pct'],
            soil_moisture_7day_pct=result['forecasts']['soil_moisture_7day_pct'],
            soil_moisture_30day_pct=result['forecasts']['soil_moisture_30day_pct'],
            drivers=result.get('drivers', {}),
            explanation=result.get('llm_explanation', '') or '',
            source_window_days=source_window_days,
            forecast_rain_7d_mm=rf.get('rain_7d_mm'),
            forecast_rain_30d_mm=rf.get('rain_30d_mm'),
            rainfall_forecast={
                'source': rf.get('source'),
                'n_forecast_days': rf.get('n_forecast_days'),
                'day_7_spi3': (rf.get('day_7') or {}).get('spi3'),
                'day_30_spi3': (rf.get('day_30') or {}).get('spi3'),
            },
        )