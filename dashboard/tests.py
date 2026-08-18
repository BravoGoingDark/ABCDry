import pandas as pd

from django.test import TestCase

from .prediction_engine.physical_helpers import (
	calculate_available_water_capacity,
	calculate_etc,
	calculate_et0,
	calculate_field_capacity,
	calculate_spi,
	calculate_vci,
	calculate_wilting_point,
	update_soil_water,
)
from .models import ClimateMetrics, ObservationYear, Region
from .prediction_engine.pipeline import DroughtPredictionPipeline
from .prediction_engine.xgboost_risk_predictor import XGBoostDroughtRiskPredictor


class PhysicalHelperTests(TestCase):
	def test_field_capacity_and_wilting_point(self):
		fc = calculate_field_capacity(40, 25, 35, 2.5)
		wp = calculate_wilting_point(40, 25, 35)
		awc = calculate_available_water_capacity(fc, wp, 600)

		self.assertGreater(fc, wp)
		self.assertGreater(awc, 0)

	def test_et0_and_etc(self):
		et0 = calculate_et0(28, 3.5, 250, 65)
		etc = calculate_etc(et0, 1.1)

		self.assertGreaterEqual(et0, 0)
		self.assertAlmostEqual(etc, et0 * 1.1, places=2)

	def test_water_balance_and_indices(self):
		water = update_soil_water(120, rainfall_mm=5, irrigation_mm=3, etc_mm=6)
		# SPI now requires a pandas Series with DatetimeIndex
		import numpy as np
		dates = pd.date_range('2020-01-01', periods=365, freq='D')
		rain = np.random.gamma(2, 5, 365) * 0.5
		rain_series = pd.Series(rain, index=dates)
		spi_series = calculate_spi(rain_series, nmonth=1)
		spi = float(spi_series.iloc[-1]) if len(spi_series) and pd.notna(spi_series.iloc[-1]) else 0
		vci = calculate_vci(0.55, [0.3, 0.4, 0.7, 0.8])

		self.assertEqual(water, 122)
		self.assertGreaterEqual(spi, -3.29)
		self.assertLessEqual(spi, 3.29)
		self.assertGreaterEqual(vci, 0)
		self.assertLessEqual(vci, 100)

	def test_heuristic_pipeline_prediction(self):
		pipeline = DroughtPredictionPipeline()
		pipeline.set_soil_properties(40, 25, 35, 2.5, 600)

		sample_df = pd.DataFrame({
			'soil_moisture_pct': [32, 31, 30, 29, 28, 27, 26, 25, 24, 23],
			'rainfall_mm': [0, 0, 2, 0, 0, 0, 0, 1, 0, 0],
			'temp_max_c': [28, 29, 29, 30, 31, 31, 32, 32, 33, 33],
			'temp_min_c': [16, 16, 17, 17, 17, 18, 18, 18, 19, 19],
			'humidity_pct': [70, 69, 68, 68, 67, 66, 66, 65, 64, 63],
			'wind_speed_ms': [3.5] * 10,
			'solar_radiation_wm2': [250] * 10,
			'ndvi': [0.72, 0.71, 0.70, 0.69, 0.68, 0.67, 0.66, 0.65, 0.64, 0.63],
			'lst_c': [26, 26.2, 26.4, 26.6, 26.8, 27, 27.2, 27.4, 27.6, 27.8],
		})

		result = pipeline.predict(sample_df, use_llm=False)

		self.assertIn('risk_scores', result)
		self.assertIn('drivers', result)
		self.assertIn('forecasts', result)
		self.assertGreaterEqual(result['risk_scores']['today'], 0)
		self.assertLessEqual(result['risk_scores']['today'], 100)


class XGBoostRiskTests(TestCase):
	def test_target_risk_derived_from_spi3(self):
		import numpy as np
		import pandas as pd

		predictor = XGBoostDroughtRiskPredictor()
		window = pd.DataFrame({'spi3': [-2.0], 'spi': [-1.0]})
		self.assertEqual(predictor.calculate_target_risk(window), 80.0)

		window = pd.DataFrame({'spi3': [0.5]})
		self.assertEqual(predictor.calculate_target_risk(window), 42.5)

		window = pd.DataFrame({'spi3': [np.nan]})
		self.assertEqual(predictor.calculate_target_risk(window), 50.0)

	def test_walk_forward_split_uses_2023_boundary(self):
		import numpy as np
		import pandas as pd

		dates = pd.date_range('2015-01-01', periods=4245, freq='D')
		rng = np.random.default_rng(42)
		frame = pd.DataFrame({
			'measurement_date': dates,
			'soil_moisture_pct': rng.uniform(10, 50, len(dates)),
			'ndvi': rng.uniform(0.1, 0.7, len(dates)),
			'lst_c': rng.uniform(15, 40, len(dates)),
			'rainfall_mm': np.maximum(0, rng.normal(1.5, 4, len(dates))),
			'temp_max_c': rng.uniform(15, 38, len(dates)),
			'spi3': rng.uniform(-3, 3, len(dates)),
		})

		predictor = XGBoostDroughtRiskPredictor()
		X, y, dates_out = predictor._build_samples(frame)
		self.assertIn('measurement_date', frame.columns)
		self.assertEqual(len(X), len(dates) - 30 + 1)
		self.assertEqual(len(X.columns), 19)

		split_idx = int((dates_out < '2023-01-01').sum())
		self.assertGreater(split_idx, 0)
		self.assertLess(split_idx, len(dates_out))
		self.assertEqual(dates_out[split_idx].year, 2023)

	def test_horizon_shifts_target_forward(self):
		import numpy as np
		import pandas as pd

		dates = pd.date_range('2015-01-01', periods=500, freq='D')
		rng = np.random.default_rng(42)
		frame = pd.DataFrame({
			'measurement_date': dates,
			'soil_moisture_pct': rng.uniform(10, 50, len(dates)),
			'ndvi': rng.uniform(0.1, 0.7, len(dates)),
			'lst_c': rng.uniform(15, 40, len(dates)),
			'rainfall_mm': np.maximum(0, rng.normal(1.5, 4, len(dates))),
			'temp_max_c': rng.uniform(15, 38, len(dates)),
			'spi3': rng.uniform(-3, 3, len(dates)),
		})

		predictor = XGBoostDroughtRiskPredictor()
		_, _, d0 = predictor._build_samples(frame)
		X7, _, d7 = predictor._build_samples(frame, horizon_days=7)
		X30, _, d30 = predictor._build_samples(frame, horizon_days=30)

		self.assertEqual(len(X7), len(d0) - 7)
		self.assertEqual(len(X30), len(d0) - 30)
		self.assertEqual(d7.iloc[0], d0.iloc[0] + pd.Timedelta(days=7))
		self.assertEqual(d30.iloc[0], d0.iloc[0] + pd.Timedelta(days=30))
		self.assertEqual(len(X7.columns), 19)


class ForecastSpiRiskTests(TestCase):
	def _seed_region_with_rain(self, days=500):
		import numpy as np

		region = Region.objects.create(name='Test Region')
		year = ObservationYear.objects.create(label='2026')
		rng = np.random.default_rng(7)
		start = pd.Timestamp('2024-01-01')
		for i in range(days):
			ClimateMetrics.objects.create(
				region=region,
				year=year,
				measurement_date=start + pd.Timedelta(days=i),
				rainfall_mm=float(max(0, rng.normal(1.5, 4))),
				temperature_max_c=30.0,
				temperature_min_c=20.0,
				temperature_mean_c=25.0,
			)
		return region, year

	def test_forecast_spi_risk_returns_clamped_risk(self):
		region, year = self._seed_region_with_rain()
		pipeline = DroughtPredictionPipeline()
		observed = pipeline._observed_daily_rain(region)
		self.assertEqual(len(observed), 500)

		expected = pd.Series(1.0, index=pd.date_range('2025-05-16', periods=7, freq='D'))
		result = pipeline.forecast_spi_risk(region, pd.Timestamp('2025-05-15'), 7, expected_rain=expected)
		self.assertIsNotNone(result)
		self.assertIn('risk', result)
		self.assertGreaterEqual(result['risk'], 0)
		self.assertLessEqual(result['risk'], 100)
		self.assertIn('spi3', result)

	def test_forecast_spi_risk_without_forecast_uses_climatology(self):
		region, year = self._seed_region_with_rain()
		pipeline = DroughtPredictionPipeline()
		result = pipeline.forecast_spi_risk(region, pd.Timestamp('2025-05-15'), 7)
		self.assertIsNotNone(result)
		self.assertGreaterEqual(result['risk'], 0)
		self.assertLessEqual(result['risk'], 100)

	def test_warning_block_flags_30d_as_trend_only(self):
		pipeline = DroughtPredictionPipeline()
		block = pipeline._warning_block({
			'nowcast': {'drought_f1': 0.92},
			'forecast_7d': {'drought_f1': 0.66},
			'forecast_30d': {'drought_f1': 0.51},
		})
		self.assertEqual(block['today']['status'], 'operational')
		self.assertEqual(block['day_7']['status'], 'operational')
		self.assertEqual(block['day_30']['status'], 'trend_only')
		self.assertEqual(block['today']['confidence_pct'], 92)
		self.assertEqual(block['day_7']['confidence_pct'], 66)
