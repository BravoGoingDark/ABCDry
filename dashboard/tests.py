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
from .prediction_engine.pipeline import DroughtPredictionPipeline


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
		spi = calculate_spi(22, 18, 4)
		vci = calculate_vci(0.55, [0.3, 0.4, 0.7, 0.8])

		self.assertEqual(water, 122)
		self.assertGreaterEqual(spi, -3)
		self.assertLessEqual(spi, 3)
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
