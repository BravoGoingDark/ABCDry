from datetime import date, timedelta
from datetime import datetime, timezone as dt_timezone
import json
import re
from pathlib import Path
from unittest import mock

import pandas as pd

from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
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
from .models import ClimateMetrics, DroughtIndices, ObservationYear, Region, RemoteSensingMetrics
from .services import assistant_nlu as nlu
from .services import retrieval
from .views.utils import _build_browser_row
from .prediction_engine.pipeline import DroughtPredictionPipeline
from .prediction_engine.xgboost_risk_predictor import XGBoostDroughtRiskPredictor
from .prediction_engine.spei_features import (
	drought_flag_from_probability,
	drought_probability_band,
	drought_warning,
	DROUGHT_PROB_THRESHOLD,
)


class DashboardChartFallbackTests(TestCase):
	def test_demo_chart_data_is_populated_when_no_measurements_exist(self):
		from .views.analytics_views import _demo_dashboard_chart_data

		payload = _demo_dashboard_chart_data()
		self.assertEqual(len(payload["chart_months"]), 12)
		self.assertEqual(len(payload["climate_rainfall"]), 12)
		self.assertEqual(len(payload["drought_spi"]), 12)
		self.assertEqual(len(payload["ndvi_values"]), 12)
		self.assertTrue(all(value is not None for value in payload["climate_rainfall"]))


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

		# A NULL preferred index must fall through to the next usable one
		# instead of silently labelling the sample as neutral. spi_3month and
		# spi_1month are NULL for every row in this database, so preferring
		# spi3 unconditionally made every label 50.0 and the model learned
		# nothing.
		window = pd.DataFrame({'spi3': [np.nan], 'spei3': [-1.0]})
		self.assertEqual(predictor.calculate_target_risk(window), 65.0)

		# No drought index at all means the sample is unlabelled, not neutral.
		window = pd.DataFrame({'spi3': [np.nan], 'spi': [np.nan]})
		self.assertIsNone(predictor.calculate_target_risk(window))

	def test_windows_are_calendar_based_not_row_based(self):
		"""A 90-day rainfall window must mean 90 days for monthly data too.

		Row-count windows turned 90 monthly rows into a 7.5-year window, so the
		same feature name meant completely different things per region.
		"""
		import numpy as np
		import pandas as pd

		predictor = XGBoostDroughtRiskPredictor()
		dates = pd.date_range('2024-01-31', periods=3, freq='MS')
		monthly = pd.DataFrame({
			'measurement_date': dates,
			'rainfall_mm': [30.0, 30.0, 30.0],
			'temporal_resolution_days': [30.4, 30.4, 30.4],
			'soil_moisture_pct': [20.0, 20.0, 20.0],
			'ndvi': [0.4, 0.4, 0.4],
			'temp_max_c': [30.0, 31.0, 32.0],
			'etc_mm': [4.0, 4.0, 4.0],
		})
		enriched = predictor._enrich_frame(monthly)
		# 2024-01-31 + 90 days reaches back over all three months (Jan 31 -> Mar 31).
		self.assertAlmostEqual(float(enriched['rainfall_90d_mm'].iloc[-1]), 90.0, places=3)

		daily_dates = pd.date_range('2024-01-01', '2024-03-30', freq='D')
		daily = pd.DataFrame({
			'measurement_date': daily_dates,
			'rainfall_mm': np.ones(len(daily_dates)),
			'temporal_resolution_days': np.ones(len(daily_dates)),
			'soil_moisture_pct': 20.0,
			'ndvi': 0.4,
			'temp_max_c': 30.0,
			'etc_mm': 4.0,
		})
		daily_enriched = predictor._enrich_frame(daily)
		self.assertAlmostEqual(float(daily_enriched['rainfall_90d_mm'].iloc[-1]), 90.0, places=3)

	def test_collapse_to_daily_averages_gauges_instead_of_summing(self):
		"""Two gauges on one day describe one place; their depth is averaged.

		Summing them would double the regional rainfall.
		"""
		import pandas as pd

		frame = pd.DataFrame({
			'measurement_date': pd.to_datetime(['2024-05-01', '2024-05-01', '2024-05-02']),
			'rainfall_mm': [10.0, 20.0, 4.0],
		})
		collapsed = DroughtPredictionPipeline._collapse_to_daily(frame)
		self.assertEqual(len(collapsed), 2)
		self.assertAlmostEqual(float(collapsed['rainfall_mm'].iloc[0]), 15.0)

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


class DashboardDataContractTests(TestCase):
	def setUp(self):
		self.user = get_user_model().objects.create_user(username='dashboardtester', password='secret123')
		self.client.force_login(self.user)
		self.region = Region.objects.create(name='Dashboard Test Region')
		self.year = ObservationYear.objects.create(label='2025')
		ClimateMetrics.objects.create(
			region=self.region,
			year=self.year,
			measurement_date=date(2025, 1, 15),
			rainfall_mm=12.5,
			temperature_mean_c=21.2,
		)
		DroughtIndices.objects.create(
			region=self.region,
			year=self.year,
			measurement_date=date(2025, 1, 15),
			spi_3month=-1.2,
			spei_3month=-0.8,
		)
		RemoteSensingMetrics.objects.create(
			region=self.region,
			year=self.year,
			measurement_date=date(2025, 1, 15),
			ndvi=0.61,
		)

	def test_dashboard_view_exposes_chart_and_map_contract(self):
		response = self.client.get('/dashboard/')
		self.assertEqual(response.status_code, 200)
		self.assertIn('climate_labels', response.context)
		self.assertIn('drought_labels', response.context)
		self.assertIn('ndvi_labels', response.context)
		self.assertIn('region_map_config_json', response.context)
		self.assertIn('lakes_by_region_json', response.context)
		self.assertIn('dashboard_js_i18n_json', response.context)

	def test_chart_data_api_returns_dashboard_js_keys(self):
		response = self.client.get(f'/api/chart-data/?region_id={self.region.id}&year_id={self.year.id}')
		self.assertEqual(response.status_code, 200)
		payload = response.json()
		for key in [
			'climate_points_rainfall',
			'climate_points_temp',
			'climate_points_spi',
			'climate_points_ndvi',
			'drought_points_spi',
			'drought_points_spei',
			'ndvi_points',
			'climate_labels',
			'drought_labels',
			'ndvi_labels',
			'chart_months',
		]:
			self.assertIn(key, payload)

	def test_climate_export_handles_timezone_aware_datetimes(self):
		response = self.client.get('/metrics/export/climate/')
		self.assertEqual(response.status_code, 200)
		self.assertIn('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', response['Content-Type'])

	def test_browser_row_includes_point_key_for_multi_point_regions(self):
		metric = ClimateMetrics.objects.create(
			region=self.region,
			year=self.year,
			measurement_date=date(2025, 1, 20),
			latitude=37.17543,
			longitude=9.62311,
			rainfall_mm=12.5,
		)
		row = _build_browser_row(metric)
		self.assertEqual(row['filters']['point_key'], '37.175430,9.623110')

	def test_multi_point_region_allows_same_day_rows_for_different_coordinates(self):
		region = Region.objects.create(name='Ichkeul Multi Point')
		year = ObservationYear.objects.create(label='2026')
		ClimateMetrics.objects.create(
			region=region,
			year=year,
			measurement_date=date(2026, 1, 15),
			latitude=37.1170,
			longitude=9.3180,
			rainfall_mm=10.0,
		)
		ClimateMetrics.objects.create(
			region=region,
			year=year,
			measurement_date=date(2026, 1, 15),
			latitude=37.0100,
			longitude=9.7310,
			rainfall_mm=12.5,
		)
		self.assertEqual(ClimateMetrics.objects.filter(region=region, year=year, measurement_date=date(2026, 1, 15)).count(), 2)


	def test_resolve_region_api_returns_nearest_region(self):
		Region.objects.all().delete()
		Region.objects.create(name='Nearest Region', latitude=37.16, longitude=9.66)
		Region.objects.create(name='Far Region', latitude=-33.92, longitude=18.42)
		response = self.client.get('/api/resolve-region/?lat=37.10&lon=9.60')
		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(payload['region_name'], 'Nearest Region')
		self.assertIn('region_id', payload)
		self.assertIn('distance_km', payload)

	def test_resolve_region_api_rejects_invalid_coordinates(self):
		response = self.client.get('/api/resolve-region/?lat=abc&lon=9.60')
		self.assertEqual(response.status_code, 400)

	def test_resolve_region_api_falls_back_to_first_region_without_coordinates(self):
		Region.objects.all().delete()
		Region.objects.create(name='No Coord Region')
		response = self.client.get('/api/resolve-region/?lat=37.10&lon=9.60')
		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(payload['region_name'], 'No Coord Region')
		self.assertEqual(payload['distance_km'], 0)

	def test_resolve_region_api_returns_404_when_no_regions_exist(self):
		Region.objects.all().delete()
		response = self.client.get('/api/resolve-region/?lat=37.10&lon=9.60')
		self.assertEqual(response.status_code, 404)


class ForecastSpiRiskTests(TestCase):
	def _seed_region_with_rain(self, days=4523):
		# SPI compares a window with the same window in earlier years, so the
		# region needs about 12 years of rain (2013-01-01 .. 2025-05-25).
		import numpy as np

		region = Region.objects.create(name='Test Region')
		year = ObservationYear.objects.create(label='2026')
		rng = np.random.default_rng(7)
		start = pd.Timestamp('2013-01-01')
		ClimateMetrics.objects.bulk_create([
			ClimateMetrics(
				region=region,
				year=year,
				measurement_date=start + pd.Timedelta(days=i),
				rainfall_mm=float(max(0, rng.normal(1.5, 4))),
				temperature_max_c=30.0,
				temperature_min_c=20.0,
				temperature_mean_c=25.0,
			)
			for i in range(days)
		])
		return region, year

	def test_forecast_spi_risk_returns_clamped_risk(self):
		region, year = self._seed_region_with_rain()
		pipeline = DroughtPredictionPipeline()
		observed = pipeline._observed_daily_rain(region)
		self.assertEqual(len(observed), 4523)

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


def _rag_chunks():
	return [
		{'id': 'a1', 'source': 'docs/SPEI_NOTES.md', 'title': 'SPEI', 'kind': 'document',
		 'text': 'The SPEI index standardises the precipitation evapotranspiration balance over a rolling three month window.'},
		{'id': 'a2', 'source': 'docs/SPEI_NOTES.md', 'title': 'SPEI', 'kind': 'document',
		 'text': 'A negative SPEI value indicates a water deficit for the region over the window.'},
		{'id': 'a3', 'source': 'docs/SPEI_NOTES.md', 'title': 'SPEI', 'kind': 'document',
		 'text': 'SPEI is computed from rainfall and potential evapotranspiration series.'},
		{'id': 'b1', 'source': 'docs/MAPS.md', 'title': 'Maps', 'kind': 'document',
		 'text': 'The dashboard map requests raster tiles through a local proxy that caches the images on disk.'},
		{'id': 'c1', 'source': 'crop knowledge base', 'title': 'Crop profile: tomato', 'kind': 'crop',
		 'text': 'Crop profile: tomato. Advised sowing / planting months: February, March, August, September. Water requirement: high water need.'},
	]


class RetrievalIndexTests(SimpleTestCase):
	def test_split_long_produces_bounded_overlapping_windows(self):
		text = ' '.join('sentence number %d explains the drought risk model.' % n for n in range(200))
		blocks = retrieval._split_long(text, size=400, overlap=80)

		self.assertGreater(len(blocks), 1)
		for block in blocks:
			self.assertLessEqual(len(block), 400)
		self.assertTrue(text.startswith(blocks[0]))
		self.assertTrue(text.endswith(blocks[-1]))

	def test_split_long_keeps_short_text_whole(self):
		self.assertEqual(retrieval._split_long('short note'), ['short note'])
		self.assertEqual(retrieval._split_long('   '), [])

	def test_corpus_covers_documents_and_crop_knowledge(self):
		chunks = retrieval.load_corpus()

		self.assertTrue(chunks)
		self.assertTrue(any(c['source'].startswith('docs/') for c in chunks))
		self.assertTrue(any(c['kind'] == 'crop' for c in chunks))
		self.assertTrue(all(c['text'].strip() and c['id'] for c in chunks))

	def test_lexical_search_ranks_the_relevant_document_first(self):
		index = retrieval.DocumentIndex(_rag_chunks())

		hits = index.search('how does the tile proxy cache the map images?')

		self.assertTrue(hits)
		self.assertEqual(hits[0]['source'], 'docs/MAPS.md')

	def test_search_also_matches_when_crop_is_supplied(self):
		index = retrieval.DocumentIndex(_rag_chunks())

		hits = index.search('when should I sow it?', crop='tomato', top_k=1)

		self.assertTrue(hits)
		self.assertEqual(hits[0]['source'], 'crop knowledge base')

	def test_search_caps_the_number_of_chunks_per_source(self):
		index = retrieval.DocumentIndex(_rag_chunks())

		hits = index.search('SPEI precipitation evapotranspiration', top_k=3, max_per_source=1)

		sources = [hit['source'] for hit in hits]
		self.assertEqual(len(sources), len(set(sources)))
		self.assertLessEqual(len(hits), 3)

	def test_search_on_empty_index_returns_nothing(self):
		self.assertEqual(retrieval.DocumentIndex([]).search('anything'), [])

	def test_context_numbers_reads_documents_and_data_strings(self):
		context = {
			'documents': [{'text': 'SPEI-3 was -0.42 in the window.'}],
			'data': ['Rainfall extremes: 12.5 mm total over 6 station-days.'],
		}

		numbers = retrieval.context_numbers(context)

		self.assertIn(-0.42, numbers)
		self.assertIn(12.5, numbers)
		self.assertIn(6.0, numbers)

	def test_prompt_block_labels_every_excerpt(self):
		context = {
			'documents': [{'text': 'chunk text', 'source': 'docs/SPEI_NOTES.md', 'relevance': 0.4}],
			'data': ['Latest satellite observation for Ichkeul: NDVI 0.61.'],
			'numbers': [],
		}

		block = retrieval.prompt_block(context)

		self.assertIn('LIVE DATA', block)
		self.assertIn('[Context 1]: chunk text', block)
		# Source paths and relevance scores stay out of the prompt, so the
		# model cannot echo them; the UI gets them from sources_for().
		self.assertNotIn('docs/SPEI_NOTES.md', block)
		self.assertNotIn('REFERENCE', block)

	def test_prompt_block_is_empty_without_context(self):
		self.assertEqual(retrieval.prompt_block({'documents': [], 'data': []}), '')

	def test_embed_texts_returns_none_when_ollama_is_unreachable(self):
		with override_settings(RAG_OLLAMA_URL='http://127.0.0.1:1', RAG_EMBED_TIMEOUT=1):
			self.assertIsNone(retrieval.embed_texts(['some text']))

	def test_gather_degrades_to_a_usable_shape_when_index_is_absent(self):
		import tempfile

		with tempfile.TemporaryDirectory() as docs, tempfile.TemporaryDirectory() as index_dir:
			retrieval.reset_index_cache()
			# No embedding server either: without this the test passes or fails
			# depending on whether Ollama happens to be running on the machine.
			with override_settings(RAG_DOCS_DIR=docs, RAG_INDEX_DIR=index_dir,
			                       RAG_OLLAMA_URL='http://127.0.0.1:1', RAG_EMBED_TIMEOUT=1):
				context = retrieval.gather('what are the tomato sowing months?')
		retrieval.reset_index_cache()

		self.assertEqual(context['dense'], False)
		self.assertIsInstance(context['documents'], list)
		self.assertIsInstance(context['numbers'], list)
		self.assertEqual(context['data'], [])

	def test_gather_returns_nothing_when_disabled(self):
		with override_settings(RAG_ENABLED=False):
			context = retrieval.gather('anything at all')

		self.assertEqual(context['documents'], [])
		self.assertEqual(context['chunks'], 0)

	def test_sources_for_marks_the_database_digest(self):
		context = {'documents': [{'title': 'Maps', 'source': 'docs/MAPS.md', 'kind': 'document', 'relevance': 0.3}],
			'data': ['a digest']}

		sources = retrieval.sources_for(context)

		self.assertEqual(sources[0]['source'], 'docs/MAPS.md')
		self.assertEqual(sources[-1]['source'], 'database')


class RetrievalDataDigestTests(TestCase):
	def setUp(self):
		today = date.today()
		first_of_month = today.replace(day=1)
		self.previous = (first_of_month - timedelta(days=1)).replace(day=1)
		self.before_that = (self.previous - timedelta(days=1)).replace(day=1)
		self.region = Region.objects.create(name='Digest Region')
		self.year = ObservationYear.objects.create(label='2025')
		for day in range(1, 7):
			ClimateMetrics.objects.create(
				region=self.region, year=self.year,
				measurement_date=self.previous.replace(day=day),
				rainfall_mm=1.0, temperature_max_c=30.0)
			ClimateMetrics.objects.create(
				region=self.region, year=self.year,
				measurement_date=self.before_that.replace(day=day),
				rainfall_mm=10.0, temperature_max_c=40.0)
		DroughtIndices.objects.create(
			region=self.region, year=self.year,
			measurement_date=self.previous.replace(day=3), spei_3month=-1.25)
		RemoteSensingMetrics.objects.create(
			region=self.region, year=self.year,
			measurement_date=self.previous.replace(day=4), ndvi=0.61)

	def test_data_digests_report_live_region_values(self):
		digests = retrieval.data_digests(self.region)
		joined = ' '.join(digests)

		self.assertEqual(len(digests), 3)
		self.assertIn('Digest Region', joined)
		self.assertIn('6.0 mm', joined)
		self.assertIn('60.0 mm', joined)
		self.assertIn('NDVI 0.61', joined)
		self.assertIn('SPEI-3 history', joined)
		self.assertIn('-1.25', joined)

	def test_data_digests_are_empty_without_a_region(self):
		self.assertEqual(retrieval.data_digests(None), [])

	def test_answer_question_reports_rag_metadata_and_sources(self):
		import tempfile

		from .services.assistant_brain import answer_question

		with tempfile.TemporaryDirectory() as docs, tempfile.TemporaryDirectory() as index_dir:
			retrieval.reset_index_cache()
			with override_settings(RAG_DOCS_DIR=docs, RAG_INDEX_DIR=index_dir):
				result = answer_question('What should I plant this season?',
				                         region_id=self.region.id, lang='en', use_llm=False)
		retrieval.reset_index_cache()

		self.assertTrue(result['answer'])
		self.assertIn('rag', result)
		self.assertIn('documents', result['rag'])
		self.assertIn('data', result['rag'])
		self.assertIsInstance(result['sources'], list)

	def test_grounding_validator_accepts_numbers_from_retrieved_context(self):
		from .services.assistant_brain import validate_numbers

		facts = {'summary': {'risk_score': 20}}
		text = 'The score is 20 out of 100, and the largest factor weight is 37.4.'

		self.assertEqual(validate_numbers(text, facts, extra=[37.4]), [])
		self.assertIn('37.4', validate_numbers(text, facts))


class AssistantNluTests(SimpleTestCase):
	def test_normalize_folds_case_accents_and_arabic_marks(self):
		self.assertEqual(nlu.normalize_text('  Sècheresse,  ÉTÉ!! '), 'secheresse ete')
		self.assertEqual(nlu.normalize_text('سَقَاءُ اَلْمِيَاه'),
			nlu.normalize_text('سقاء المياه'))
		self.assertEqual(nlu.normalize_text('أهلا'), nlu.normalize_text('اهلا'))
		self.assertEqual(nlu.normalize_text('بطاطا'), nlu.normalize_text('بطاطا'))

	def test_keyword_score_separates_verbatim_from_typo(self):
		text = nlu.normalize_text('please irrigate the tomato field')
		tokens = text.split()

		self.assertEqual(nlu.keyword_score(text, tokens, 'irrigat'), 2)
		self.assertEqual(nlu.keyword_score(text, tokens, 'irigate'), 1)
		self.assertEqual(nlu.keyword_score(text, tokens, 'salinity'), 0)

	def test_match_intent_survives_typos_and_accents(self):
		self.assertEqual(nlu.classify_intent('when shoud I irigate?'), 'irrigation')
		self.assertEqual(nlu.classify_intent('do I need to plnt wheat?'), 'planting')
		self.assertEqual(nlu.classify_intent('quelle est la secheresse?'), 'drought_status')
		self.assertEqual(nlu.classify_intent('is there draught risk?'), 'drought_status')
		self.assertEqual(nlu.classify_intent('qqqq zzzz'), 'freeform')

	def test_match_intent_does_not_match_wheat_on_heat(self):
		self.assertNotEqual(nlu.classify_intent('my wheat is fine'), 'temperature')

	def test_stopwords_never_fuzzy_match_a_real_keyword(self):
		# "what" reaching "wheat" once turned an irrigation question into
		# "knowledge", because the phrase "what is" matched piecemeal.
		self.assertEqual(nlu.classify_intent('when should i irrigate my wheat?'),
		                 'irrigation')
		# A one letter preposition must not reach the citrus alias "agrumes".
		self.assertIsNone(nlu.match_crop('quelle est la secheresse a Kairouan ?'))
		self.assertIsNone(nlu.match_crop('what is the risk'))

	def test_french_inflections_and_british_spelling_are_understood(self):
		self.assertEqual(nlu.classify_intent('quand dois-je irriguer mon ble ?'),
		                 'irrigation')
		self.assertEqual(nlu.classify_intent('is there a draught risk?'),
		                 'drought_status')
		self.assertEqual(nlu.classify_intent('quelle est la secheresse ?'),
		                 'drought_status')

	def test_arabic_definite_article_does_not_hide_the_crop(self):
		self.assertEqual(nlu.match_crop('متى يجب أن أسقي القمح ؟'), 'wheat')
		self.assertEqual(nlu.classify_intent('متى يجب أن أسقي القمح ؟'), 'irrigation')
		self.assertEqual(nlu.classify_intent('هل هناك جفاف الشهر القادم ؟'),
		                 'drought_status')

	def test_match_crop_handles_typos_and_french(self):
		self.assertEqual(nlu.match_crop('when do I plant tomatos?'), 'tomato')
		self.assertEqual(nlu.match_crop('irrigation des oliviers'), 'olive')
		self.assertEqual(nlu.match_crop('tell me about olive'), 'olive')
		self.assertIsNone(nlu.match_crop('what is the risk'))

	def test_is_followup_detects_continuations(self):
		self.assertTrue(nlu.is_followup('and next month', intent='freeform'))
		self.assertTrue(nlu.is_followup('next month', intent='freeform'))
		self.assertTrue(nlu.is_followup('when should I water them', intent='freeform'))
		self.assertFalse(nlu.is_followup(
			'what is the drought forecast for next month', intent='drought_status'))

	def test_resolve_inherits_crop_and_intent_on_followup(self):
		history = [{'role': 'user', 'content': 'When should I irrigate my tomatoes?'}]

		resolved = nlu.resolve('and next month?', history=history, regions=[])

		self.assertEqual(resolved['crop'], 'tomato')
		self.assertTrue(resolved['inherited']['crop'])
		self.assertEqual(resolved['intent'], 'irrigation')
		self.assertTrue(resolved['inherited']['intent'])
		self.assertTrue(resolved['followup'])

	def test_resolve_prefers_the_new_crop_over_the_inherited_one(self):
		history = [{'role': 'user', 'content': 'When should I irrigate my tomatoes?'}]

		resolved = nlu.resolve('what about olive trees?', history=history, regions=[])

		self.assertEqual(resolved['crop'], 'olive')
		self.assertFalse(resolved['inherited']['crop'])

	def test_resolve_honours_explicit_values(self):
		resolved = nlu.resolve('and next month?', history=[], crop='barley', regions=[],
		                      explicit={'crop': 'olive', 'intent': 'planting'})

		self.assertEqual(resolved['crop'], 'barley')
		self.assertEqual(resolved['intent'], 'planting')

	def test_needs_clarification_asks_for_region_once(self):
		regions = [_FakeRegion('Ichkeul'), _FakeRegion('Kairouan')]

		self.assertEqual(
			nlu.needs_clarification('irrigation', regions=regions), 'region')
		self.assertIsNone(
			nlu.needs_clarification('irrigation', region_id=4, regions=regions))
		self.assertIsNone(nlu.needs_clarification('greeting', regions=regions))

	def test_needs_clarification_does_not_repeat_itself(self):
		history = [{'role': 'user', 'content': 'drought in Kairouan please'}]

		self.assertIsNone(
			nlu.needs_clarification('irrigation', history=history,
			                        regions=[_FakeRegion('Kairouan')]))

	def test_needs_clarification_asks_topic_only_when_nothing_matched(self):
		self.assertEqual(nlu.needs_clarification('freeform'), 'topic')
		self.assertIsNone(nlu.needs_clarification('freeform', best_relevance=0.4))

	def test_clarification_options_are_self_contained_questions(self):
		regions = [_FakeRegion('Ichkeul'), _FakeRegion('Kairouan'), _FakeRegion('Ichkeul Verify')]

		text, options = nlu.clarification('region', 'en', regions=regions)

		self.assertIn('region', text.lower())
		self.assertEqual(len(options), 2)
		self.assertIn('Ichkeul', options[0])
		self.assertIn('Kairouan', options[1])
		for option in options:
			self.assertTrue(option.endswith('?'))

	def test_clarification_is_localised(self):
		for lang in ('en', 'fr', 'ar'):
			text, options = nlu.clarification('topic', lang)
			self.assertTrue(text)
			self.assertEqual(len(options), 5)


class _FakeRegion:
	def __init__(self, name, id=0):
		self.name = name
		self.id = id


class AssistantClarificationTests(TestCase):
	def setUp(self):
		self.user = get_user_model().objects.create_user(username='clarifytester', password='secret123')
		self.client.force_login(self.user)
		for name in ('Clarify Ichkeul', 'Clarify Kairouan'):
			Region.objects.get_or_create(name=name)

	def test_ambiguous_region_question_asks_instead_of_guessing(self):
		response = self.client.post('/assistant/chat/',
		                            data=json.dumps({'question': 'When should I irrigate my wheat?'}),
		                            content_type='application/json')

		payload = response.json()
		self.assertEqual(payload['engine'], 'clarification')
		self.assertEqual(payload['clarification']['kind'], 'region')
		self.assertTrue(payload['suggestions'])
		self.assertLessEqual(len(payload['suggestions']), 4)
		# Every option repeats the farmer's own question so one click is enough.
		names = set(Region.objects.values_list('name', flat=True))
		for option in payload['suggestions']:
			self.assertIn('When should I irrigate my wheat in ', option)
			self.assertTrue(any(option.endswith(f'in {name}?') for name in names),
			                option)

	def test_question_naming_a_region_is_answered_not_clarified(self):
		region = Region.objects.get(name='Clarify Kairouan')

		response = self.client.post('/assistant/chat/',
		                            data=json.dumps({
		                                'question': 'When should I irrigate in Kairouan?',
		                                'region_id': region.id}),
		                            content_type='application/json')

		payload = response.json()
		self.assertNotEqual(payload['engine'], 'clarification')
		self.assertEqual(payload['region'], 'Kairouan')


class DroughtWarningRuleTests(SimpleTestCase):
	"""The published warning must be one deterministic decision, not two.

	Regression = severity, classifier = probability. The rule fires when
	either is confident, which is what the walk-forward evaluation backed.
	"""

	def test_warning_fires_on_either_surface(self):
		self.assertEqual(drought_warning(0.80, 0.2), (True, 'classifier'))
		self.assertEqual(drought_warning(0.10, -1.4), (True, 'regression'))
		self.assertEqual(drought_warning(0.40, -1.2), (True, 'both'))

	def test_warning_silent_when_neither_surface_is_confident(self):
		self.assertEqual(drought_warning(0.10, -0.2), (False, None))

	def test_warning_threshold_is_the_single_source_of_truth(self):
		just_below = DROUGHT_PROB_THRESHOLD - 0.01
		self.assertEqual(drought_warning(just_below, 0.0), (False, None))
		self.assertEqual(drought_warning(DROUGHT_PROB_THRESHOLD, 0.0),
		                 (True, 'classifier'))

	def test_missing_inputs_do_not_crash_and_do_not_warn(self):
		self.assertEqual(drought_warning(None, -0.5), (False, None))
		self.assertEqual(drought_warning(float('nan'), -0.5), (False, None))
		self.assertEqual(drought_warning(0.1, None), (False, None))

	def test_probability_band_is_monotone(self):
		keys = [drought_probability_band(p)[0]
		        for p in (0.05, 0.2, 0.4, 0.7)]
		self.assertEqual(keys, ['minimal', 'low', 'elevated', 'high'])
		self.assertEqual(drought_probability_band(None)[0], 'unknown')

	def test_probability_flag_uses_the_same_threshold(self):
		self.assertTrue(drought_flag_from_probability(DROUGHT_PROB_THRESHOLD))
		self.assertFalse(drought_flag_from_probability(DROUGHT_PROB_THRESHOLD - 0.01))
		self.assertIsNone(drought_flag_from_probability(None))


class HistoricalObservationsApiTests(TestCase):
	def setUp(self):
		self.factory = RequestFactory()
		self.region, _ = Region.objects.get_or_create(name="Ichkeul", defaults={"latitude": 37.16, "longitude": 9.66})

	def test_historical_view_renders_template(self):
		from .views.analytics_views import historical_view
		req = self.factory.get('/historical/')
		response = historical_view(req)
		self.assertEqual(response.status_code, 200)

	def test_historical_observations_api_returns_success(self):
		from .views.analytics_views import historical_observations_api
		req = self.factory.get(f'/api/historical/observations/?region_id={self.region.id}&category=climate&metric=rainfall_mm&interval=1y')
		response = historical_observations_api(req)
		self.assertEqual(response.status_code, 200)
		data = json.loads(response.content.decode('utf-8'))
		self.assertTrue(data['success'])
		self.assertEqual(data['category'], 'climate')
		self.assertEqual(data['metric'], 'rainfall_mm')
		self.assertIn('labels', data)
		self.assertIn('values', data)
		self.assertIn('stats', data)
		self.assertIn('observations', data)
		self.assertGreater(len(data['values']), 0)

	def test_historical_observations_api_different_intervals(self):
		from .views.analytics_views import historical_observations_api
		for interval in ['7d', '30d', '90d', '6m', '1y', '5y']:
			req = self.factory.get(f'/api/historical/observations/?region_id={self.region.id}&category=soil&metric=moisture_content_percent&interval={interval}')
			response = historical_observations_api(req)
			self.assertEqual(response.status_code, 200)
			data = json.loads(response.content.decode('utf-8'))
			self.assertTrue(data['success'])
			self.assertEqual(data['interval'], interval)
			self.assertGreater(len(data['observations']), 0)


class WeatherForecastServiceTests(TestCase):
	def setUp(self):
		from django.core.cache import cache

		cache.clear()
		self.region = Region.objects.create(
			name="Weather Test Basin", latitude=37.0635, longitude=9.5245
		)

	def _open_meteo_payload(self):
		return {
			"timezone": "Africa/Tunis",
			"daily": {
				"time": ["2026-11-03", "2026-11-04"],
				"weather_code": [0, 61],
				"temperature_2m_max": [24.0, 19.5],
				"temperature_2m_min": [12.0, 11.0],
				"temperature_2m_mean": [18.0, 15.25],
				"precipitation_sum": [0.0, 4.2],
				"precipitation_probability_max": [5, 80],
				"et0_fao_evapotranspiration": [2.1, 1.2],
				"wind_speed_10m_max": [14.0, 22.5],
			},
			"hourly": {
				"time": ["2026-11-03T00:00", "2026-11-03T12:00", "2026-11-04T12:00"],
				"relative_humidity_2m": [80, 60, 70],
			},
		}

	def _mock_response(self):
		from unittest.mock import Mock

		response = Mock()
		response.json.return_value = self._open_meteo_payload()
		response.raise_for_status.return_value = None
		return response

	def test_fetch_normalises_open_meteo_payload(self):
		from unittest.mock import patch

		from .services.weather_forecast import fetch_region_forecast

		with patch(
			"dashboard.services.weather_forecast.requests.get",
			return_value=self._mock_response(),
		) as mocked:
			payload = fetch_region_forecast(self.region, days=2)

		mocked.assert_called_once()
		self.assertIsNotNone(payload)
		self.assertEqual(payload["source"], "open-meteo")
		self.assertEqual(len(payload["days"]), 2)
		self.assertEqual(payload["days"][0]["condition"]["label"], "Clear sky")
		self.assertEqual(payload["days"][1]["condition"]["label"], "Light rain")
		self.assertEqual(payload["days"][0]["humidity"], 70.0)
		self.assertEqual(payload["days"][1]["precip_prob"], 80)
		self.assertEqual(payload["summary"]["total_rain_mm"], 4.2)
		self.assertEqual(payload["summary"]["max_temp_c"], 24.0)
		self.assertIsNone(payload["error"])

	def test_fetch_returns_none_when_upstream_fails(self):
		from unittest.mock import patch

		from .services.weather_forecast import fetch_region_forecast

		with patch(
			"dashboard.services.weather_forecast.requests.get",
			side_effect=ConnectionError("boom"),
		):
			self.assertIsNone(fetch_region_forecast(self.region))

	def test_get_region_forecast_caches_successful_payload(self):
		from unittest.mock import patch

		from .services.weather_forecast import get_region_forecast

		payload = {"region": {"id": self.region.id}, "days": []}
		with patch(
			"dashboard.services.weather_forecast.fetch_region_forecast",
			return_value=payload,
		) as mocked:
			first = get_region_forecast(self.region)
			second = get_region_forecast(self.region)

		self.assertEqual(first, payload)
		self.assertEqual(second, payload)
		self.assertEqual(mocked.call_count, 1)

	def test_region_without_coordinates_falls_back_to_known_centroid(self):
		from .services.weather_forecast import region_point

		ichkeul = Region(name="Ichkeul", latitude=None, longitude=None)
		self.assertEqual(region_point(ichkeul), (37.0635, 9.5245))

		unknown = Region(name="Atlantis", latitude=None, longitude=None)
		self.assertIsNone(region_point(unknown))


class WeatherForecastApiTests(TestCase):
	def setUp(self):
		from django.core.cache import cache

		cache.clear()
		self.client = self.client_class()
		user = get_user_model().objects.create_user(
			username="weather-api-tester", password="test-pass-123"
		)
		self.client.force_login(user)
		self.region = Region.objects.create(
			name="API Weather Basin", latitude=37.0635, longitude=9.5245
		)

	def test_api_returns_forecast_payload(self):
		from unittest.mock import patch

		payload = {
			"region": {"id": self.region.id, "name": self.region.name},
			"source": "open-meteo",
			"attribution": "Weather data by Open-Meteo.com",
			"days": [{"date": "2026-11-03"}],
			"summary": {"total_rain_mm": 0.0},
			"error": None,
		}
		with patch(
			"dashboard.views.prediction_views.get_region_forecast",
			return_value=payload,
		) as mocked:
			response = self.client.get(
				f"/api/weather-forecast/?region={self.region.id}&days=99"
			)

		self.assertEqual(response.status_code, 200)
		body = response.json()
		self.assertEqual(body["attribution"], "Weather data by Open-Meteo.com")
		self.assertEqual(len(body["days"]), 1)
		mocked.assert_called_once_with(self.region, days=16)

	def test_api_returns_404_for_unknown_region(self):
		response = self.client.get("/api/weather-forecast/?region=999999")
		self.assertEqual(response.status_code, 404)
		self.assertIn("error", response.json())

	def test_api_returns_400_for_region_without_coordinates(self):
		region = Region.objects.create(name="Nowhere Basin")
		response = self.client.get(f"/api/weather-forecast/?region={region.id}")
		self.assertEqual(response.status_code, 400)
		self.assertIn("error", response.json())

	def test_api_returns_502_when_upstream_is_down(self):
		from unittest.mock import patch

		payload = {
			"region": {"id": self.region.id},
			"days": [],
			"error": "The weather service is temporarily unavailable.",
		}
		with patch(
			"dashboard.views.prediction_views.get_region_forecast",
			return_value=payload,
		):
			response = self.client.get(f"/api/weather-forecast/?region={self.region.id}")

		self.assertEqual(response.status_code, 502)
		self.assertIn("error", response.json())




class UserRoleTests(TestCase):
	"""RBAC: Django superusers are superadmins, and the user editor is safe."""

	def setUp(self):
		User = get_user_model()
		self.admin = User.objects.create_superuser("root", "root@example.com", "pw")
		self.viewer = User.objects.create_user("viewer", password="pw")

	def test_superuser_profile_gets_superadmin_role(self):
		self.assertEqual(self.admin.profile.role, "superadmin")
		self.assertEqual(self.viewer.profile.role, "viewer")

	def test_superuser_can_open_user_management(self):
		self.client.force_login(self.admin)
		self.assertEqual(self.client.get("/manage/users/").status_code, 200)

	def test_viewer_is_refused_user_management(self):
		self.client.force_login(self.viewer)
		self.assertEqual(self.client.get("/manage/users/").status_code, 302)

	def test_edit_page_creates_missing_profile(self):
		from .models import UserProfile

		UserProfile.objects.filter(user=self.viewer).delete()
		self.client.force_login(self.admin)
		response = self.client.get(f"/manage/users/{self.viewer.id}/edit/")
		self.assertEqual(response.status_code, 200)
		self.assertTrue(UserProfile.objects.filter(user=self.viewer, role="viewer").exists())

	def test_admin_cannot_demote_self(self):
		self.client.force_login(self.admin)
		self.client.post(f"/manage/users/{self.admin.id}/edit/", {"role": "viewer", "region": ""})
		self.admin.profile.refresh_from_db()
		self.assertEqual(self.admin.profile.role, "superadmin")

	def test_admin_can_change_other_roles(self):
		self.client.force_login(self.admin)
		self.client.post(f"/manage/users/{self.viewer.id}/edit/", {"role": "subadmin", "region": "bogus"})
		self.viewer.profile.refresh_from_db()
		self.assertEqual(self.viewer.profile.role, "subadmin")
		self.assertIsNone(self.viewer.profile.region)


class CropSuitabilityTests(SimpleTestCase):
    """Pure-function checks of the crop suitability scorer (no database)."""

    @staticmethod
    def _clim(rain=60.0, tmean=18.0, et0=3.0):
        return {m: {'rain_mean': rain, 'rain_p25': rain / 2, 'tmean': tmean, 'et0': et0}
                for m in range(1, 13)}

    def test_fao56_et0_matches_textbook_example(self):
        from .prediction_engine.physical_helpers import fao56_et0
        # FAO-56 Example 18 (Brussels, 6 July): ET0 = 3.9 mm/day with u2 given
        et0 = fao56_et0(21.5, 12.3, 22.07, 70.0, 2.078, 50.8, 187,
                        elevation_m=100, wind_height_m=2)
        self.assertAlmostEqual(et0, 3.9, delta=0.2)

    def test_trapezoid_and_effective_rain(self):
        from .services.crop_suitability import effective_rain, trapezoid
        self.assertEqual(trapezoid(15, 0, 10, 20, 30), 1.0)
        self.assertAlmostEqual(trapezoid(5, 0, 10, 20, 30), 0.5)
        self.assertEqual(trapezoid(31, 0, 10, 20, 30), 0.0)
        self.assertIsNone(trapezoid(None, 0, 10, 20, 30))
        self.assertAlmostEqual(effective_rain(100), 84.0)
        self.assertAlmostEqual(effective_rain(300), 155.0)

    def test_wet_climate_needs_no_irrigation_dry_one_does(self):
        from .services.crop_suitability import score_crop
        wet = score_crop('barley', self._clim(rain=150, et0=1.5), sow_month=11)
        dry = score_crop('barley', self._clim(rain=5, et0=5.0), sow_month=11)
        self.assertEqual(wet['water_balance']['net_irrigation_mm'], 0)
        self.assertGreater(wet['factors']['water'], 0.95)
        self.assertLess(dry['factors']['water'], 0.5)
        self.assertGreater(dry['water_balance']['net_irrigation_mm'], 100)
        self.assertEqual(dry['limiting_factor'], 'water')

    def test_irrigated_mode_removes_water_limit_unless_supply_is_short(self):
        from .services.crop_suitability import score_crop
        clim = self._clim(rain=5, et0=5.0)
        full = score_crop('tomato', clim, sow_month=3, mode='irrigated')
        short = score_crop('tomato', clim, sow_month=3, mode='irrigated', water_supply_mm=100)
        self.assertEqual(full['factors']['water'], 1.0)
        self.assertLess(short['factors']['water'], 0.5)

    def test_soil_limits_apply_only_when_known(self):
        from .services.crop_suitability import score_crop
        clim = self._clim()
        no_soil = score_crop('citrus', clim)
        alkaline_saline = score_crop('citrus', clim, soil={'ph': 8.4, 'ece_dsm': 5.0,
                                                           'sand_pct': 20, 'clay_pct': 45})
        self.assertIsNone(no_soil['factors']['ph'])
        self.assertLess(alkaline_saline['score'], no_soil['score'])
        self.assertEqual(alkaline_saline['factors']['texture'], 0.75)

    def test_cold_month_excludes_frost_sensitive_perennial(self):
        from .services.crop_suitability import score_crop
        clim = self._clim(rain=80)
        clim[1]['tmean'] = 4.0
        self.assertEqual(score_crop('date_palm', clim)['class'], 'N')
        self.assertGreater(score_crop('olive', clim)['score'], 40)

    def test_rank_flags_plantable_crops_and_scores_requested_month(self):
        from .services.crop_suitability import rank_crops
        ranking = rank_crops(self._clim(), month=3, mode='irrigated')
        pepper = next(r for r in ranking if r['crop'] == 'pepper')
        wheat = next(r for r in ranking if r['crop'] == 'wheat')
        self.assertTrue(pepper['plantable_now'])
        self.assertEqual(pepper['sow_month'], 3)
        self.assertFalse(wheat['plantable_now'])
        self.assertEqual(wheat['next_planting_month'], 11)
        flags = [r['plantable_now'] for r in ranking]
        self.assertEqual(flags, sorted(flags, reverse=True))

    def test_off_season_crop_gets_sow_now_and_next_window_scenarios(self):
        from .services.crop_suitability import rank_crops, score_crop
        clim = self._clim()
        clim[3]['tmean'] = 2.0  # a frost month makes sowing wheat in March fail
        ranking = rank_crops(clim, month=3)
        wheat = next(r for r in ranking if r['crop'] == 'wheat')
        now, nxt = wheat['if_sown_now'], wheat['next_window']
        # "Sow now" is the same model run at the off-season month.
        self.assertEqual(now['score'], score_crop('wheat', clim, sow_month=3)['score'])
        self.assertEqual(now['class'], 'N')
        # "Wait" is the next window, scored for that month.
        self.assertEqual(nxt['month'], wheat['next_planting_month'])
        self.assertEqual(nxt['score'], score_crop('wheat', clim, sow_month=nxt['month'])['score'])
        # In-season crops and perennials carry no scenario.
        pepper = next(r for r in ranking if r['crop'] == 'pepper')
        olive = next(r for r in ranking if r['crop'] == 'olive')
        self.assertNotIn('if_sown_now', pepper)
        self.assertNotIn('if_sown_now', olive)


# A ~1 km x 1 km square near Mateur (lon/lat): about 99.5 ha at this latitude
_SQUARE = {'type': 'Polygon', 'coordinates': [[
    [9.60, 37.00], [9.6112, 37.00], [9.6112, 37.009], [9.60, 37.009]]]}


class FarmGeometryTests(SimpleTestCase):
    def test_polygon_is_closed_and_measured(self):
        from .services import farmer_service as fs
        poly = fs.clean_polygon({'type': 'Feature', 'geometry': _SQUARE})
        ring = poly['coordinates'][0]
        self.assertEqual(ring[0], ring[-1])
        area, lat, lon = fs.polygon_area_centroid(poly)
        # (0.0112 deg x 111.2 km x cos 37) * (0.009 deg x 111.2 km) = 0.995 km2
        self.assertAlmostEqual(area, 99.5, delta=1.0)
        self.assertAlmostEqual(lat, 37.0045, places=3)
        self.assertAlmostEqual(lon, 9.6056, places=3)

    def test_invalid_shapes_are_rejected(self):
        from .services import farmer_service as fs
        for bad in (None, {'type': 'Point', 'coordinates': [9, 37]},
                    {'type': 'Polygon', 'coordinates': [[[9, 37], [9.1, 37]]]},
                    {'type': 'Polygon', 'coordinates': [[[9, 37], [999, 37], [9.1, 37.1]]]}):
            with self.assertRaises(fs.FarmGeometryError):
                fs.clean_polygon(bad)


class CropManagementTests(SimpleTestCase):
    def test_every_crop_has_management_guidance(self):
        from .services.crop_management import MANAGEMENT
        from .services.crop_suitability import CROPS
        self.assertEqual(set(MANAGEMENT), set(CROPS))
        for key, mgmt in MANAGEMENT.items():
            self.assertTrue(mgmt['fertilizer']['schedule'], key)
            self.assertTrue(mgmt['protection'], key)

    def test_calendar_is_dated_and_sorted(self):
        import datetime as dt
        from .services.crop_management import crop_calendar
        cal = crop_calendar('wheat', dt.date(2026, 11, 15), today=dt.date(2026, 11, 1))
        dates = [e['date'] for e in cal['events']]
        self.assertEqual(dates, sorted(dates))
        self.assertEqual(cal['events'][0]['title'], 'Sowing / planting')
        harvest = next(e for e in cal['events'] if e['title'] == 'Expected harvest')
        self.assertEqual(harvest['date'], '2027-05-24')  # 15 Nov + 190 days

    def test_weather_alerts(self):
        import datetime as dt
        from .services.crop_management import weather_alerts
        cold_wet = [{'label': f'D{i}', 'tmin': 1, 'tmax': 14, 'tmean': 12, 'precip': 6,
                     'precip_prob': 80, 'wind': 10, 'humidity': 90, 'et0': 1.0} for i in range(7)]
        titles = [a['title'] for a in weather_alerts(cold_wet, 'potato', today=dt.date(2026, 3, 1))]
        self.assertIn('Frost risk', titles)
        self.assertIn('Late blight (mildiou): favourable weather', titles)
        calm = [{'label': 'Mon', 'tmin': 10, 'tmax': 22, 'tmean': 16, 'precip': 0,
                 'precip_prob': 5, 'wind': 8, 'humidity': 60, 'et0': 3.0}]
        spray = next(a for a in weather_alerts(calm) if a['title'] == 'Spraying windows')
        self.assertIn('Mon', spray['text'])


@override_settings(ALLOWED_HOSTS=['testserver'])
class FarmerRoleTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.farmer = User.objects.create_user('ali', password='pw-12345')
        self.farmer.profile.role = 'farmer'
        self.farmer.profile.save()
        self.other = User.objects.create_user('sami', password='pw-12345')
        self.other.profile.role = 'farmer'
        self.other.profile.save()
        self.viewer = User.objects.create_user('vera', password='pw-12345')
        self.soil = mock.patch('dashboard.services.farmer_service.ensure_soil', return_value=None)
        self.soil.start()
        self.addCleanup(self.soil.stop)

    def _create(self, client, **extra):
        body = {'name': 'North field', 'boundary': _SQUARE, 'crop': 'wheat', **extra}
        return client.post('/farmer/api/farms/', json.dumps(body), content_type='application/json')

    def test_login_sends_farmer_to_farmer_space(self):
        r = self.client.post('/login/', {'username': 'ali', 'password': 'pw-12345'})
        self.assertRedirects(r, '/farmer/', fetch_redirect_response=False)

    def test_farmer_is_kept_inside_farmer_space(self):
        self.client.force_login(self.farmer)
        self.assertEqual(self.client.get('/farmer/').status_code, 200)
        self.assertRedirects(self.client.get('/analysis/'), '/farmer/', fetch_redirect_response=False)
        self.assertEqual(self.client.get('/api/spei-forecast/').status_code, 403)

    def test_non_farmer_cannot_use_farmer_api(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get('/farmer/api/farms/').status_code, 403)
        self.assertEqual(self.client.get('/farmer/').status_code, 302)

    def test_create_update_and_isolation(self):
        self.client.force_login(self.farmer)
        r = self._create(self.client)
        self.assertEqual(r.status_code, 201, r.content)
        farm = r.json()['farm']
        self.assertGreater(farm['area_ha'], 80)
        self.assertEqual(farm['crop'], 'wheat')

        url = f"/farmer/api/farms/{farm['id']}/"
        bad = self.client.patch(url, json.dumps({'crop': 'banana'}), content_type='application/json')
        self.assertEqual(bad.status_code, 400)
        ok = self.client.patch(url, json.dumps({'irrigated': True, 'water_supply_mm': 300}),
                               content_type='application/json')
        self.assertTrue(ok.json()['farm']['irrigated'])

        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.delete(url).status_code, 404)
        self.assertEqual(self.client.get('/farmer/api/farms/').json()['farms'], [])

    def test_soil_lookup_runs_after_commit_not_in_the_request(self):
        self.client.force_login(self.farmer)
        with mock.patch('dashboard.services.farmer_service.threading.Thread') as thread,                 self.captureOnCommitCallbacks(execute=True) as callbacks:
            self.assertEqual(self._create(self.client).status_code, 201)
            thread.assert_not_called()  # nothing started while the request is open
        self.assertEqual(len(callbacks), 1)
        thread.assert_called_once()

    def test_invalid_boundary_is_rejected(self):
        self.client.force_login(self.farmer)
        r = self._create(self.client, boundary={'type': 'Point', 'coordinates': [9, 37]})
        self.assertEqual(r.status_code, 400)

    def test_crop_plan_and_advice_without_climate_data(self):
        self.client.force_login(self.farmer)
        farm_id = self._create(self.client).json()['farm']['id']
        plan = self.client.get(f'/farmer/api/farms/{farm_id}/crop-plan/?crop=olive')
        self.assertEqual(plan.status_code, 200)
        self.assertTrue(plan.json()['protection'])
        advice = self.client.get(f'/farmer/api/farms/{farm_id}/advice/?month=11')
        self.assertEqual(advice.status_code, 404)  # no region with climate history in the test DB
        self.assertIn('error', advice.json())

    def test_irrigation_fields_are_validated(self):
        self.client.force_login(self.farmer)
        url = f"/farmer/api/farms/{self._create(self.client).json()['farm']['id']}/"
        patch = lambda body: self.client.patch(url, json.dumps(body), content_type='application/json')
        self.assertEqual(patch({'irrigation_method': 'flood'}).status_code, 400)
        self.assertEqual(patch({'irrigation_flow_m3h': -3}).status_code, 400)
        future = (date.today() + timedelta(days=2)).isoformat()
        self.assertEqual(patch({'last_irrigation_date': future}).status_code, 400)
        ok = patch({'irrigation_method': 'drip', 'irrigation_flow_m3h': 12.5,
                    'last_irrigation_date': date.today().isoformat()}).json()['farm']
        self.assertEqual((ok['irrigation_method'], ok['irrigation_flow_m3h']), ('drip', 12.5))
        self.assertEqual(ok['last_irrigation_date'], date.today().isoformat())

    def test_irrigation_plan_api(self):
        self.client.force_login(self.farmer)
        today = date.today()
        weather = [{'date': today + timedelta(days=k), 'precip': 0, 'et0': 6.0, 'tmax': 30,
                    'wind': 10, 'precip_prob': 0} for k in range(-60, 16)]
        farm = self._create(self.client, crop='olive', irrigated=True,
                            irrigation_method='drip', irrigation_flow_m3h=20).json()['farm']
        url = f"/farmer/api/farms/{farm['id']}/irrigation/"
        with mock.patch('dashboard.services.irrigation_schedule.fetch_daily_water', return_value=weather):
            d = self.client.get(url).json()
        self.assertTrue(d['available'])
        self.assertEqual(d['method'], 'drip')
        self.assertTrue(d['events'])
        e = d['events'][0]
        self.assertAlmostEqual(e['gross_mm'], e['net_mm'] / 0.9, delta=0.2)
        self.assertAlmostEqual(e['hours'], e['m3_farm'] / 20, delta=0.1)

        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_irrigation_plan_needs_a_crop(self):
        self.client.force_login(self.farmer)
        farm_id = self._create(self.client, crop='').json()['farm']['id']
        d = self.client.get(f'/farmer/api/farms/{farm_id}/irrigation/').json()
        self.assertEqual((d['available'], d['reason']), (False, 'no_crop'))


class IrrigationScheduleTests(SimpleTestCase):
    TODAY = date(2026, 7, 10)

    def _weather(self, et0=6.0, rain=None, past=60):
        rain = rain or {}
        return [{'date': self.TODAY + timedelta(days=k), 'precip': rain.get(k, 0.0), 'et0': et0,
                 'tmax': 30, 'wind': 10, 'precip_prob': 90 if k in rain else 0}
                for k in range(-past, 16)]

    def _plan(self, crop='tomato', **kw):
        from .services.irrigation_schedule import build_schedule
        kw.setdefault('sowing_date', date(2026, 4, 20))
        kw.setdefault('awc_mm_per_m', 140)
        return build_schedule(crop, kw.pop('weather', None) or self._weather(), self.TODAY, **kw)

    def test_method_sets_dose_frequency_and_losses(self):
        drip, surface = self._plan(method='drip'), self._plan(method='surface')
        self.assertGreater(len(drip['events']), len(surface['events']))
        self.assertLess(drip['events'][0]['net_mm'], surface['events'][-1]['net_mm'])
        for plan, eff in ((drip, 0.9), (surface, 0.6)):
            e = plan['events'][-1]
            self.assertAlmostEqual(e['gross_mm'], e['net_mm'] / eff, delta=0.2)
            self.assertEqual(e['m3_per_ha'], round(e['gross_mm'] * 10))

    def test_last_watering_resets_the_soil(self):
        plan = self._plan(last_irrigation=self.TODAY - timedelta(days=1))
        self.assertEqual(plan['basis'], 'last_irrigation')
        self.assertLessEqual(plan['now']['depletion_mm'], 8)  # one day of use
        self.assertEqual(plan['now']['code'], 'ok')

    def test_expected_rain_postpones_a_due_watering(self):
        # Watered 5 days ago: the sprinkler trigger is reached tomorrow, 30 mm fall the day after.
        last = self.TODAY - timedelta(days=5)
        dry = self._plan(last_irrigation=last)
        wet = self._plan(last_irrigation=last, weather=self._weather(rain={2: 30.0}))
        first_dry = dry['events'][0]['date']
        self.assertNotIn(first_dry, [e['date'] for e in wet['events']])
        self.assertTrue(any(d['postponed'] for d in wet['days']))

    def test_no_watering_in_the_last_weeks_before_harvest(self):
        # 190-day season: harvest 2026-08-03, so the last forecast days fall in the dry-down.
        plan = self._plan(crop='wheat', sowing_date=date(2026, 1, 25))
        for e in plan['events']:
            self.assertGreater(plan['season']['harvest_date'], e['date'])
            days_left = (date.fromisoformat(plan['season']['harvest_date']) - date.fromisoformat(e['date'])).days
            self.assertGreater(days_left, 14)

    def test_rain_only_farm_reports_when_the_crop_starts_to_suffer(self):
        wet = self._weather(et0=6.0, rain={-1: 60.0})
        plan = self._plan(crop='olive', irrigated=False, weather=wet, awc_mm_per_m=120)
        self.assertEqual(plan['basis'], 'rain_only')
        self.assertIsNotNone(plan['first_stress_date'])
        self.assertGreater(plan['first_stress_date'], self.TODAY.isoformat())

    def test_logged_amount_counts_not_a_full_refill(self):
        # Reports since 10 days ago, one watering yesterday: full refill vs 5 mm.
        day, since = self.TODAY - timedelta(days=1), self.TODAY - timedelta(days=10)
        full = self._plan(waterings={day: None}, reported_from=since)
        small = self._plan(waterings={day: 5.0}, reported_from=since)
        self.assertGreater(small['now']['depletion_mm'], full['now']['depletion_mm'] + 3)
        self.assertTrue(any(d['logged'] for d in small['days']))

    def test_forgotten_watering_is_asked_and_the_answer_closes_it(self):
        # Watered 20 days ago, nothing reported since, no rain: the plan was due long ago.
        last = {self.TODAY - timedelta(days=20): None}
        plan = self._plan(waterings=last)
        m = plan['missed']
        self.assertTrue(m['ask'])
        self.assertLess(m['due_date'], self.TODAY.isoformat())
        self.assertGreater(m['days_late'], 0)
        self.assertIsNotNone(m['stress_since'])
        self.assertGreater(plan['recent']['stress_days'], 0)
        self.assertGreater(plan['recent']['yield_risk_pct'], 0)
        self.assertEqual(plan['next']['date'], self.TODAY.isoformat())  # catch up today

        # "No, not yet" today: no question, but the plan remembers it was skipped.
        told = self._plan(waterings=last, answered_through=self.TODAY)
        self.assertFalse(told['missed']['ask'])
        self.assertTrue(told['missed']['reported_skipped'])

        # "Yes, yesterday": the deficit is gone and so is the question.
        done = self._plan(waterings={**last, self.TODAY - timedelta(days=1): None},
                          answered_through=self.TODAY - timedelta(days=1))
        self.assertIsNone(done['missed'])
        self.assertEqual(done['now']['code'], 'ok')

    def test_farmer_who_reports_no_watering_is_followed_dry(self):
        plan = self._plan(answered_through=self.TODAY - timedelta(days=12))
        self.assertEqual(plan['basis'], 'reported_dry')
        self.assertIsNotNone(plan['missed'])

    def test_days_before_the_first_report_are_not_counted_as_dry(self):
        # One watering reported 2 days ago: before it nothing is known, so the
        # last month must not show up as a drought the farmer caused.
        plan = self._plan(waterings={self.TODAY - timedelta(days=2): None})
        self.assertEqual(plan['recent']['stress_days'], 0)
        self.assertIsNone(plan['missed'])

    def test_big_catch_up_dose_is_split(self):
        plan = self._plan(method='drip', waterings={self.TODAY - timedelta(days=20): None})
        self.assertIn('split_dose', plan['next']['tips'])

    def test_skipping_the_plan_costs_more_than_following_it(self):
        plan = self._plan(waterings={self.TODAY - timedelta(days=2): None})
        follow, skip = plan['scenarios']['follow'], plan['scenarios']['skip']
        self.assertGreater(follow['waterings'], 0)
        self.assertGreater(skip['stress_days'], follow['stress_days'])
        self.assertGreater(skip['yield_risk_pct'], follow['yield_risk_pct'])

    def test_early_harvest_ends_the_season(self):
        plan = self._plan(harvested_on=self.TODAY - timedelta(days=1))
        self.assertEqual(plan['season']['state'], 'harvested')
        self.assertEqual(plan['events'], [])
        self.assertEqual(plan['now']['code'], 'no_crop')


class ProductCatalogTests(SimpleTestCase):
    def test_every_threat_and_fertiliser_has_products(self):
        from .services.crop_management import MANAGEMENT
        from .services.product_catalog import PROTECTION, PRODUCT_KEYS
        for crop, m in MANAGEMENT.items():
            for item in m.get('fertilizer', {}).get('schedule', []):
                self.assertIn(item['product'], PRODUCT_KEYS, (crop, item['product']))
            for threat in m.get('protection', []):
                self.assertTrue(PROTECTION.get(crop, {}).get(threat['name']), (crop, threat['name']))

    def test_fertiliser_quantities_for_the_farm(self):
        from .services.product_catalog import fertilizer_details
        d = fertilizer_details('Ammonium nitrate 33.5%', '100-150 kg/ha', area_ha=2)
        self.assertEqual(d['farm'], {'area_ha': 2, 'kg': '200–300', 'bags': '4–6', 'bag_kg': 50})
        self.assertEqual(d['supplies']['N'], '34–50 kg/ha')
        self.assertEqual(d['alternative']['name'], 'Urea 46%')
        self.assertEqual(d['alternative']['rate'], '73–109 kg/ha')  # same nitrogen
        mixed = fertilizer_details('Calcium nitrate + potassium nitrate', '10-15 kg/ha per week', 2)
        self.assertEqual(len(mixed['products']), 2)
        self.assertTrue(mixed['per_week'])
        self.assertNotIn('farm', mixed)  # split between two products is not known

    def test_protection_options_ipm_order_and_doses(self):
        from .services.product_catalog import protection_options
        opts = protection_options('olive', 'Peacock spot (oeil de paon)', area_ha=3)
        self.assertEqual(opts[0]['kind'], 'mineral')
        copper = opts[0]
        self.assertEqual(copper['per_ha'], '3,000–5,000 g/ha')   # 300-500 g/100 L x 1000 L/ha
        self.assertEqual(copper['farm_water_l'], 3000)
        tuta = protection_options('tomato', 'Tomato leaf miner (Tuta absoluta)', area_ha=2)
        kinds = [o['kind'] for o in tuta]
        self.assertEqual(kinds, sorted(kinds, key=['cultural', 'trap', 'biological', 'mineral', 'chemical'].index))
        bt = next(o for o in tuta if o['name'].startswith('Bacillus'))
        self.assertEqual(bt['farm'], '1–2 kg')
        mz = next(o for o in protection_options('potato', 'Late blight (mildiou)', area_ha=1.5)
                  if o['name'].startswith('Mancozeb'))
        self.assertEqual(mz['farm'], '3–3.8 kg')
        self.assertTrue(all(o['group'].startswith('IRAC') for o in tuta if o['kind'] == 'chemical'))

    def test_best_spray_day_skips_rain_wind_and_heat(self):
        from .services.product_catalog import best_spray_day
        days = [{'date': '2026-05-01', 'precip_prob': 80, 'wind': 5, 'tmax': 20, 'precip': 6},
                {'date': '2026-05-02', 'precip_prob': 0, 'wind': 30, 'tmax': 20, 'precip': 0},
                {'date': '2026-05-03', 'precip_prob': 0, 'wind': 5, 'tmax': 34, 'precip': 0},
                {'date': '2026-05-04', 'precip_prob': 10, 'wind': 8, 'tmax': 24, 'precip': 0}]
        self.assertEqual(best_spray_day(days), '2026-05-04')
        self.assertIsNone(best_spray_day(days[:3]))


class FarmerTranslationTests(SimpleTestCase):
    """The farmer page must be entirely in the chosen language."""
    ARABIC = re.compile(r'[؀-ۿ]')

    @staticmethod
    def _data_texts():
        from .services import crop_management as cm, product_catalog as pc, weather_forecast as wf
        out = set()
        for m in cm.MANAGEMENT.values():
            f = m.get('fertilizer') or {}
            out.add(f.get('note'))
            for it in f.get('schedule', []):
                out |= {it['stage'], it['product'], it['rate']}
            for t in m.get('protection', []):
                out |= {t['name'], t['watch'], t['prevent'], t['control']}
        for opts in pc.PROTECTION.values():
            for lst in opts.values():
                for o in lst:
                    out |= {o['name'], o['rate'], o['notes']}
        for f in pc.FERTILIZERS.values():
            out |= {f['name'], f['tip']}
        out |= {v[0] for v in wf._WMO_CONDITIONS.values()}
        out |= {cm.PROTECTION_NOTICE, cm.FERTILIZER_NOTICE}
        return {s for s in out if s}

    def test_every_data_text_has_french_and_arabic(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'locale'))
        from agronomy_pairs import AGRO_PAIRS
        have = {en for en, fr, ar in AGRO_PAIRS if fr and ar}
        self.assertEqual(sorted(self._data_texts() - have), [])

    def test_every_template_text_is_translated(self):
        import polib
        root = Path(__file__).resolve().parents[1]
        t = (root / 'templates' / 'dashboard' / 'farmer_home.html').read_text(encoding='utf-8')
        ids = set(re.findall(r"\{% trans '([^']*)' %\}", t)) | set(re.findall(r'\{% trans "([^"]*)" %\}', t))
        for lang in ('fr', 'ar'):
            po = {e.msgid: e.msgstr for e in polib.pofile(str(root / 'locale' / lang / 'LC_MESSAGES' / 'django.po'))}
            # {% trans %} looks "%" up doubled
            missing = sorted(i for i in ids if not po.get(i.replace('%', '%%')))
            self.assertEqual(missing, [], lang)

    def test_plan_products_and_alerts_come_out_in_arabic(self):
        from django.utils import translation
        from .services.crop_management import crop_plan, weather_alerts
        days = [{'date': f'2026-05-0{k}', 'label': 'x', 'tmin': 1, 'tmax': 36, 'precip': 25, 'precip_prob': 90,
                 'wind': 5, 'et0': 5, 'tmean': 15, 'humidity': 90} for k in range(1, 8)]
        with translation.override('ar'):
            texts = []
            for crop in ('olive', 'tomato', 'wheat'):
                p = crop_plan(crop, area_ha=2.0)
                texts += [p['fertilizer']['note'], p['fertilizer_notice'], p['protection_notice']]
                for s in p['fertilizer']['schedule']:
                    texts += [s['stage'], s['product'], s['rate']]
                    texts += [x['name'] for x in s['details']['products']] + [x['tip'] for x in s['details']['products']]
                    texts += list(s['details'].get('supplies', {}).values())
                for t in p['protection']:
                    texts += [t['name'], t['watch'], t['prevent'], t['control']]
                    texts += [o['name'] for o in t['products']] + [o['rate'] for o in t['products'] if o['rate']]
                    texts += [o['notes'] for o in t['products'] if o['notes']]
                texts += [e['title'] for e in p['calendar']['events']]
            for a in weather_alerts(days, 'tomato', today=date(2026, 5, 1)):
                texts += [a['title'], a['text']]
        english = [s for s in texts if s and not self.ARABIC.search(s)]
        self.assertEqual(english, [])

    def test_weather_labels_are_translated_without_touching_the_cache(self):
        from django.utils import translation
        from .services.farmer_service import _translated_forecast
        payload = {'days': [{'condition': {'label': 'Light rain', 'icon': 'rainy'}}]}
        with translation.override('fr'):
            out = _translated_forecast(payload)
        self.assertEqual(out['days'][0]['condition']['label'], 'Pluie faible')
        self.assertEqual(payload['days'][0]['condition']['label'], 'Light rain')


class MobileTokenLoginTests(TestCase):
    """The Flutter app signs in with a token instead of the browser session."""

    def setUp(self):
        User = get_user_model()
        self.farmer = User.objects.create_user('mobi', password='pw-12345', first_name='Mona')
        self.farmer.profile.role = 'farmer'
        self.farmer.profile.save()
        self.viewer = User.objects.create_user('just-a-viewer', password='pw-12345')
        p = mock.patch('dashboard.services.farmer_service.ensure_soil', return_value=None)
        p.start()
        self.addCleanup(p.stop)
        from django.test import Client
        self.app = Client(enforce_csrf_checks=True)       # a phone: no cookie, no CSRF token

    def login(self, username='mobi', password='pw-12345'):
        return self.app.post('/farmer/api/auth/login/', json.dumps({'username': username, 'password': password}),
                             content_type='application/json')

    def test_login_gives_a_token_that_works_on_the_farmer_api(self):
        r = self.login()
        self.assertEqual(r.status_code, 200, r.content)
        token = r.json()['token']
        self.assertEqual(r.json()['user'], {'username': 'mobi', 'name': 'Mona', 'role': 'farmer'})
        auth = {'HTTP_AUTHORIZATION': f'Token {token}'}
        self.assertEqual(self.app.get('/farmer/api/me/', **auth).json()['user']['username'], 'mobi')
        self.assertIn('wheat', [c['key'] for c in self.app.get('/farmer/api/crops/', **auth).json()['crops']])
        created = self.app.post('/farmer/api/farms/', json.dumps({'name': 'Phone farm', 'boundary': _SQUARE,
                                                                   'crop': 'olive'}),
                                content_type='application/json', **auth)
        self.assertEqual(created.status_code, 201, created.content)     # POST without CSRF: token request
        farms = self.app.get('/farmer/api/farms/', **auth).json()['farms']
        self.assertEqual([f['name'] for f in farms], ['Phone farm'])

    def test_wrong_password_and_non_farmers_are_refused(self):
        self.assertEqual(self.login(password='nope').status_code, 401)
        self.assertEqual(self.login(username='just-a-viewer').status_code, 403)

    def test_bad_or_revoked_token_and_other_pages(self):
        self.assertEqual(self.app.get('/farmer/api/farms/', HTTP_AUTHORIZATION='Token nope').status_code, 401)
        token = self.login().json()['token']
        auth = {'HTTP_AUTHORIZATION': f'Token {token}'}
        # the token opens the farmer API only, never the analyst pages
        self.assertEqual(self.app.get('/analysis/', **auth).status_code, 302)
        self.assertEqual(self.app.post('/farmer/api/auth/logout/', **auth).status_code, 200)
        self.assertEqual(self.app.get('/farmer/api/farms/', **auth).status_code, 401)

    def test_reminder_texts_match_the_web_page(self):
        from .services.task_text_msgids import TEXTS
        page = (Path(__file__).resolve().parents[1] / 'templates' / 'dashboard' / 'farmer_home.html').read_text(encoding='utf-8')
        found = dict((k, a or b) for k, a, b in re.findall(
            r"\b((?:tk|tip)_[a-z_]+): \"\{% filter escapejs %\}\{% trans (?:'([^']*)'|\"([^\"]*)\") %\}", page))
        self.assertEqual(TEXTS, found)   # regenerate task_text_msgids.py when the page texts change

    def test_tasks_arrive_written_in_the_phones_language(self):
        token = self.login().json()['token']
        auth = {'HTTP_AUTHORIZATION': f'Token {token}'}
        today = date.today()
        weather = [{'date': today + timedelta(days=k), 'precip': 0, 'et0': 6.0, 'tmax': 30, 'wind': 10,
                    'precip_prob': 0} for k in range(-60, 16)]
        farm = self.app.post('/farmer/api/farms/', json.dumps({'name': 'F', 'boundary': _SQUARE, 'crop': 'olive',
                                                                'irrigated': True}),
                             content_type='application/json', **auth).json()['farm']
        with mock.patch('dashboard.services.irrigation_schedule.fetch_daily_water', return_value=weather), \
                mock.patch('dashboard.services.farmer_service.farm_weather', return_value={'forecast': {}}):
            tasks = self.app.get(f"/farmer/api/farms/{farm['id']}/tasks/", HTTP_ACCEPT_LANGUAGE='ar', **auth).json()['tasks']
        last = next(t for t in tasks if t['key'] == 'irr-last')
        self.assertEqual(last['text']['title'], 'متى سقيت هذه الضيعة آخر مرة؟')
        self.assertTrue(all(re.search(r'[؀-ۿ]', x) for x in last['text']['why']))
        self.assertIsNone(re.search(r'\{\w+\}', json.dumps([t['text'] for t in tasks], ensure_ascii=False)))

    def test_app_language_comes_from_the_phone(self):
        token = self.login().json()['token']
        r = self.app.get('/farmer/api/farms/999/', HTTP_AUTHORIZATION=f'Token {token}', HTTP_ACCEPT_LANGUAGE='fr')
        self.assertEqual(r.json()['error'], 'Parcelle introuvable.')


class FarmerAppInstallTests(TestCase):
    """The farmer interface installs as a phone app (PWA) and opens offline."""

    def test_manifest_describes_an_installable_app(self):
        from django.contrib.staticfiles import finders
        r = self.client.get('/farmer/manifest.webmanifest')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r['Content-Type'].startswith('application/manifest+json'))
        m = json.loads(r.content)
        self.assertEqual((m['display'], m['scope'], m['start_url'][:8]), ('standalone', '/farmer/', '/farmer/'))
        sizes = {(i['sizes'], i['purpose']) for i in m['icons']}
        self.assertTrue({('192x192', 'any'), ('512x512', 'any'), ('512x512', 'maskable')} <= sizes)
        for icon in m['icons']:
            self.assertIn('/dashboard/pwa/', icon['src'])
        for name in ('icon-192.png', 'icon-512.png', 'icon-maskable-512.png', 'apple-touch-icon.png'):
            self.assertTrue(finders.find(f'dashboard/pwa/{name}'), name)
        self.assertTrue(any('tab=irrigation' in s['url'] for s in m['shortcuts']))

    def test_manifest_speaks_the_users_language(self):
        self.client.cookies['django_language'] = 'ar'
        m = json.loads(self.client.get('/farmer/manifest.webmanifest').content)
        self.assertEqual((m['lang'], m['dir'], m['name']), ('ar', 'rtl', 'APWRS الفلاح'))

    def test_service_worker_controls_only_the_farmer_app(self):
        r = self.client.get('/farmer/sw.js')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r['Content-Type'].startswith('application/javascript'))
        self.assertEqual(r['Service-Worker-Allowed'], '/farmer/')
        self.assertEqual(r['Cache-Control'], 'no-cache')
        body = r.content.decode()
        self.assertIn('/vendor/leaflet/leaflet', body)        # the map works offline
        self.assertIn("if (request.method !== 'GET') return;", body)   # changes are never cached or faked
        self.assertNotIn('{{', body)

    def test_page_links_the_app(self):
        user = get_user_model().objects.create_user('app-farmer', password='pw-12345')
        user.profile.role = 'farmer'
        user.profile.save()
        self.client.force_login(user)
        html = self.client.get('/farmer/').content.decode()
        self.assertIn('rel="manifest" href="/farmer/manifest.webmanifest"', html)
        self.assertIn("navigator.serviceWorker.register(\"/farmer/sw.js\"", html)
        self.assertIn('apple-touch-icon', html)
        self.assertIn('id="offline-bar"', html)


class FarmQuestionUnderstandingTests(SimpleTestCase):
    """Which farm topic a question asks about (three languages, typos)."""

    def test_question_bank(self):
        from .services.farm_qa import topics
        bank = {
            'When should I water and how much?': ['next_watering'],
            'how long should I run the pump': ['pump_time'],
            'is my soil dry?': ['soil_water'],
            "what happens if I don't water this week": ['skip_scenario'],
            'how much water in the next 16 days': ['water_16d'],
            'water need for the rest of the season': ['season_water'],
            'what should I do today?': ['todo'],
            'which fertilizer now and how much': ['fertilizer'],
            'when is the best day to spray': ['spray_day'],
            'will it rain tomorrow?': ['weather'],
            'any frost alert?': ['alerts'],
            'what should I plant now': ['what_to_plant'],
            'when is the harvest': ['crop_status'],
            'when did I last water': ['last_watering'],
            'how do you calculate the watering': ['how_calculated'],
            'Quand dois-je arroser et combien ?': ['next_watering'],
            'Va-t-il pleuvoir demain ?': ['weather'],
            'quel engrais maintenant': ['fertilizer'],
            'متى أسقي وكم؟': ['next_watering'],
            'ماذا أفعل اليوم؟': ['todo'],
            'هل ستمطر غدا؟': ['weather'],
            'ما هو أفضل يوم للرش؟': ['spray_day'],
            'whn shuld i watr': ['next_watering'],
            'wether tomorow': ['weather'],
            'ok and what are the most dangerous one the ones with low success rate': ['what_to_plant'],
            'which crops should I avoid': ['what_to_plant'],
            'what are the best and the worst crops': ['what_to_plant'],
            'quelles cultures éviter': ['what_to_plant'],
            'ما هي أسوأ محصول للزراعة الآن': ['what_to_plant'],
            'what is the most dangerous pest': ['pests'],
        }
        for question, expected in bank.items():
            self.assertEqual(topics(question), expected, question)

    def test_regional_and_unrelated_questions_are_not_farm_questions(self):
        from .services.farm_qa import topics, match_threat
        for q in ('Is drought expected next month?', 'what is SPEI', 'how much did it rain last month',
                  'hello', 'who won the football match', 'my leaves are yellow'):
            self.assertEqual(topics(q), [], q)
            self.assertIsNone(match_threat(q, 'olive'), q)

    def test_follow_up_keeps_the_previous_topic(self):
        from .services.farm_qa import topics
        self.assertEqual(topics('and the pump?', ['next_watering']), ['pump_time'])
        self.assertEqual(topics('why?', ['soil_water']), ['soil_water'])
        self.assertEqual(topics('why?'), [])

    def test_best_and_worst_crops_are_never_swapped(self):
        from types import SimpleNamespace
        from .services.farm_qa import a_what_to_plant
        ranking = [
            {'crop': 'barley', 'score': 100, 'class': 'S1', 'plantable_now': True, 'limiting_factor': None, 'factors': {}},
            {'crop': 'oats', 'score': 96, 'class': 'S1', 'plantable_now': True, 'limiting_factor': None, 'factors': {}},
            {'crop': 'tomato', 'score': 35, 'class': 'N', 'plantable_now': False, 'limiting_factor': 'temperature',
             'factors': {'temperature': 0.4},
             'if_sown_now': {'score': 12, 'class': 'N', 'limiting_factor': 'temperature', 'factors': {'temperature': 0.2}}},
            {'crop': 'pepper', 'score': 20, 'class': 'N', 'plantable_now': True, 'limiting_factor': 'ph',
             'factors': {'ph': 0.5}},
        ]
        data = SimpleNamespace(lang='en', advice={'ranking': ranking, 'plant_now': ranking[:2]})
        worst = ' '.join(a_what_to_plant(data, 'what are the most dangerous ones, with low success rate'))
        self.assertIn('Riskiest', worst)
        self.assertIn('Tomato (12/100): climate not ideal', worst)   # if sown now, not in its window
        self.assertIn('Pepper (20/100): soil pH not ideal', worst)
        self.assertNotIn('Best', worst)
        self.assertLess(worst.index('Tomato'), worst.index('Pepper'))   # lowest first
        best = ' '.join(a_what_to_plant(data, 'what is the best crop to plant now'))
        self.assertIn('Barley (100/100)', best)
        self.assertNotIn('Riskiest', best)
        both = ' '.join(a_what_to_plant(data, 'what are the best and the worst crops'))
        self.assertIn('Best crops', both)
        self.assertIn('Riskiest', both)

    def test_what_are_without_a_known_term_is_not_a_definition(self):
        from .services import assistant_brain as brain
        empty = ({'documents': [], 'data': [], 'numbers': [], 'signature': '', 'dense': False, 'chunks': 0}, [])
        with mock.patch.object(brain, '_retrieval', return_value=empty), \
                mock.patch.object(brain.nlu, 'resolve', return_value={
                    'crop': None, 'intent': 'knowledge', 'region': None, 'followup': False, 'inherited': {}}), \
                mock.patch.object(brain.Region.objects, 'all', return_value=[]), \
                mock.patch.object(brain, 'chat_completion') as chat:
            d = brain.answer_question('what are the most dangerous ones')
        chat.assert_not_called()
        self.assertEqual(d['intent'], 'out_of_scope')

    def test_pest_names_in_three_languages(self):
        from .services.farm_qa import match_threat
        cases = [('how do I treat the olive fly', 'olive', 'Olive fruit fly (Bactrocera oleae)'),
                 ('comment traiter la mouche de l olive', 'olive', 'Olive fruit fly (Bactrocera oleae)'),
                 ('كيف أعالج ذبابة الزيتون', 'olive', 'Olive fruit fly (Bactrocera oleae)'),
                 ('what product against tuta', 'tomato', 'Tomato leaf miner (Tuta absoluta)'),
                 ('my wheat has rust', 'wheat', 'Yellow and brown rust')]
        for q, crop, name in cases:
            self.assertEqual(match_threat(q, crop)[1]['name'], name, q)
        # a crop name alone is not a pest
        self.assertIsNone(match_threat('when is the olive harvest', 'olive'))


class FarmAssistantAnswerTests(TestCase):
    """Farm answers come from the farm's data, say only what was asked."""

    def setUp(self):
        User = get_user_model()
        self.farmer = User.objects.create_user('amel', password='pw-12345')
        self.farmer.profile.role = 'farmer'
        self.farmer.profile.save()
        self.other = User.objects.create_user('hedi', password='pw-12345')
        self.other.profile.role = 'farmer'
        self.other.profile.save()
        today = date.today()
        self.weather = [{'date': today + timedelta(days=k), 'precip': 12.0 if k == 4 else 0.0, 'et0': 6.0,
                         'tmax': 34, 'wind': 12, 'precip_prob': 70 if k == 4 else 5} for k in range(-60, 16)]
        forecast = {'forecast': {'days': [{'date': (today + timedelta(days=k)).isoformat(), 'tmax': 30, 'tmin': 18,
                                           'tmean': 24, 'precip': 12.0 if k == 4 else 0, 'humidity': 50,
                                           'precip_prob': 70 if k == 4 else 5, 'wind': 10,
                                           'condition': {'label': 'Clear sky'}} for k in range(16)]},
                    'alerts': []}
        for target, kw in (('dashboard.services.farmer_service.ensure_soil', {'return_value': None}),
                           ('dashboard.services.farmer_service.farm_weather', {'return_value': forecast}),
                           ('dashboard.services.irrigation_schedule.fetch_daily_water', {'return_value': self.weather}),
                           ('dashboard.services.assistant_brain._retrieval',
                            {'return_value': ({'documents': [], 'data': [], 'numbers': [], 'signature': '',
                                               'dense': False, 'chunks': 0}, [])}),
                           ('dashboard.services.assistant_brain.resolve_model', {'return_value': ''})):
            p = mock.patch(target, **kw)
            p.start()
            self.addCleanup(p.stop)
        self.client.force_login(self.farmer)
        body = {'name': 'South field', 'boundary': _SQUARE, 'crop': 'tomato', 'irrigated': True,
                'irrigation_method': 'drip', 'irrigation_flow_m3h': 25,
                'sowing_date': (today - timedelta(days=80)).isoformat()}
        self.farm_id = self.client.post('/farmer/api/farms/', json.dumps(body),
                                        content_type='application/json').json()['farm']['id']
        self.client.post(f'/farmer/api/farms/{self.farm_id}/activities/', json.dumps(
            {'kind': 'irrigation', 'date': (today - timedelta(days=3)).isoformat(), 'amount_mm': 20}),
            content_type='application/json')

    def ask(self, question, lang='en', **extra):
        r = self.client.post('/assistant/chat/', json.dumps(
            {'question': question, 'lang': lang, 'farm_id': self.farm_id, **extra}), content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def test_watering_answer_matches_the_water_tab_exactly(self):
        page = self.client.get(f'/farmer/api/farms/{self.farm_id}/irrigation/').json()
        d = self.ask('When should I water and how much?')
        self.assertEqual(d['engine'], 'farm_data')
        self.assertIsNone(d['model'])                       # written by code, no model
        nxt = page['next']
        from .services.farm_qa import n
        self.assertIn(f"{n(nxt['gross_mm'])} mm", d['answer'])
        self.assertIn(f"{n(nxt['m3_farm'], 0)} m³", d['answer'])
        self.assertIn(f"{n(nxt['hours'])} h", d['answer'])
        self.assertIn(f"{n(page['now']['available_pct'], 0)}%", d['answer'])
        # only what was asked: no drought score, no fertiliser, no pests
        for other in ('drought', 'SPEI', 'fertili', 'score', 'pest'):
            self.assertNotIn(other, d['answer'])

    def test_each_topic_answers_from_the_data(self):
        cases = {
            'how long should I run the pump': 'run the pump about',
            'is my soil dry?': 'Water in the soil now',
            "what happens if I don't water": 'If you do not water',
            'what should I do today?': 'To do:',
            'what product against tuta': 'Bacillus thuringiensis kurstaki',
            'will it rain this week?': 'Rain expected in the next 7 days: 12 mm',
            'when is the harvest': 'Expected harvest',
            'when did I last water': 'Your last recorded watering',
            'how do you calculate the watering': 'FAO-56',
        }
        for q, expected in cases.items():
            d = self.ask(q)
            self.assertEqual(d['engine'], 'farm_data', q)
            self.assertIn(expected, d['answer'], q)

    def test_impossible_pump_time_is_flagged(self):
        # 98.7 ha on a 25 m3/h pump: one watering takes days, the farmer must be told
        d = self.ask('how long should I run the pump')
        self.assertIn('days of pumping: check the flow you entered', d['answer'])

    def test_products_come_with_doses_for_this_farm(self):
        area = self.client.get(f'/farmer/api/farms/{self.farm_id}/').json()['farm']['area_ha']
        d = self.ask('which product against tuta and how much')
        from .services.product_catalog import _rng
        self.assertIn(f'0.5–1 kg/ha — for your farm: {_rng(0.5 * area, area, 1 if area < 10 else 0)} kg', d['answer'])
        self.assertIn('label', d['answer'])

    def test_follow_up_and_two_topics(self):
        d = self.ask('When should I water?')
        follow = self.ask('and the pump?', conversation={'farm_topics': d['understood']['farm_topics']})
        self.assertEqual(follow['understood']['farm_topics'], ['pump_time'])
        both = self.ask('when should I water and will it rain this week?')
        self.assertEqual(set(both['understood']['farm_topics']), {'next_watering', 'weather'})

    def test_answers_in_arabic_and_french(self):
        ar = self.ask('متى أسقي وكم؟', lang='ar')
        self.assertTrue(re.search(r'[؀-ۿ]', ar['answer']))
        self.assertNotIn('Next watering', ar['answer'])
        fr = self.ask('Quand dois-je arroser et combien ?', lang='fr')
        self.assertIn('Prochain arrosage', fr['answer'])

    def test_another_farmers_farm_is_never_used(self):
        self.client.force_login(self.other)
        d = self.ask('When should I water and how much?')
        self.assertNotEqual(d['engine'], 'farm_data')

    def test_unrelated_question_gets_an_honest_answer(self):
        d = self.ask('who won the football match yesterday?')
        self.assertEqual(d['intent'], 'out_of_scope')
        self.assertIn('no information', d['answer'])
        sugg = self.client.get(f'/assistant/chat/?lang=en&farm={self.farm_id}').json()['suggestions']
        self.assertIn('What should I do today?', sugg)

    def test_missing_crop_is_said_not_guessed(self):
        self.client.patch(f'/farmer/api/farms/{self.farm_id}/', json.dumps({'crop': ''}),
                          content_type='application/json')
        d = self.ask('When should I water?')
        self.assertIn('Tell me what grows on this farm first', d['answer'])


class AssistantGroundingTests(SimpleTestCase):
    """The model only writes documentation answers, and only from the sources."""

    FACTS = {'region': 'Testland', 'climate': {'rain_30d_mm': 12.5, 'rain_month_climatology_mm': 40.0,
                                                'tmean_30d_c': 18.2, 'tmax_30d_c': 27.0, 'tmin_30d_c': 9.0,
                                                'water_balance_30d_mm': -60.0, 'et0_30d_mm': 72.5},
             'drought': {'spei_3month': -1.1}, 'remote_sensing': {'ndvi': 0.41, 'soil_moisture_pct': 22},
             'summary': {'risk_level': 'moderate', 'risk_score': 55}}

    def test_regional_answers_say_only_the_asked_metric(self):
        from .services.assistant_brain import fallback_answer
        rain = fallback_answer(self.FACTS, 'rainfall', {}, 'en')
        self.assertIn('12.5 mm', rain)
        for other in ('SPEI', 'NDVI', 'temperature', 'score'):
            self.assertNotIn(other, rain)
        temp = fallback_answer(self.FACTS, 'temperature', {}, 'en')
        self.assertIn('18.2 °C', temp)
        self.assertNotIn('Rainfall', temp)
        soil = fallback_answer({**self.FACTS, 'remote_sensing': {}}, 'soil_moisture', {}, 'fr')
        self.assertIn('Aucune donnée', soil)                    # missing data is said, not guessed

    def test_unknown_question_template_is_out_of_scope(self):
        from .services.assistant_brain import fallback_answer
        self.assertIn('no information', fallback_answer(self.FACTS, 'freeform', {}, 'en'))

    def test_data_questions_never_reach_the_model(self):
        from .services import assistant_brain as brain
        self.assertNotIn('rainfall', brain.LLM_INTENTS)
        self.assertNotIn('drought_status', brain.LLM_INTENTS)
        self.assertNotIn('irrigation', brain.LLM_INTENTS)

    @override_settings(ASSISTANT_LLM_PROVIDER='openai', ASSISTANT_API_URL='https://api.example/v1',
                       ASSISTANT_API_KEY='k', ASSISTANT_API_MODEL='m', ASSISTANT_LLM_ENABLED=True)
    def test_hosted_api_first_then_local_model(self):
        from .services import assistant_brain as brain
        ok = mock.Mock(status_code=200)
        ok.json.return_value = {'choices': [{'message': {'content': 'From the API.'}}]}
        with mock.patch.object(brain.requests, 'post', return_value=ok) as post:
            self.assertEqual(brain.chat_completion([{'role': 'user', 'content': 'q'}]), ('From the API.', 'api:m'))
            self.assertIn('/chat/completions', post.call_args[0][0])
            self.assertEqual(post.call_args[1]['headers']['Authorization'], 'Bearer k')
            sent = json.dumps(post.call_args[1]['json'])
        self.assertNotIn('amel', sent)
        down = mock.Mock(status_code=503, text='busy')
        local = mock.Mock(status_code=200)
        local.json.return_value = {'message': {'content': 'From the local model.'}}
        with mock.patch.object(brain.requests, 'post', side_effect=[down, local]), \
                mock.patch.object(brain, 'resolve_local_model', return_value='gemma3:4b'):
            self.assertEqual(brain.chat_completion([{'role': 'user', 'content': 'q'}]),
                             ('From the local model.', 'gemma3:4b'))

    def test_prompt_forbids_outside_knowledge(self):
        from .services.assistant_brain import SYSTEM_PROMPT, NO_ANSWER
        self.assertIn(NO_ANSWER, SYSTEM_PROMPT)
        self.assertIn('Never use your general knowledge', SYSTEM_PROMPT)


class AssistantGroundingFlowTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()   # answers are cached by question: each test must reach the model
        self.region, _ = Region.objects.get_or_create(name='Grounding Testland')

    def _docs(self, relevance):
        return ({'documents': [{'source': 'docs/x.md', 'title': 'X', 'text': 'Some text.', 'relevance': relevance}],
                 'data': [], 'numbers': [], 'signature': 's', 'dense': False, 'chunks': 1},
                [{'source': 'docs/x.md', 'title': 'X', 'kind': 'document', 'relevance': relevance}])

    def test_model_saying_no_answer_gives_the_honest_reply(self):
        from .services import assistant_brain as brain
        with mock.patch.object(brain, '_retrieval', return_value=self._docs(0.9)), \
                mock.patch.object(brain, 'resolve_model', return_value='api:m'), \
                mock.patch.object(brain, 'chat_completion', return_value=('NO_ANSWER', 'api:m')):
            d = brain.answer_question('Tell me about the zorblax feature', region_id=self.region.id)
        self.assertIn('no information', d['answer'])
        self.assertEqual(d['engine'], 'template')

    def test_weakly_related_documents_are_not_sent_to_the_model(self):
        from .services import assistant_brain as brain
        with mock.patch.object(brain, '_retrieval', return_value=self._docs(0.05)), \
                mock.patch.object(brain, 'chat_completion') as chat:
            d = brain.answer_question('who won the football match', region_id=self.region.id)
        chat.assert_not_called()
        self.assertEqual(d['intent'], 'out_of_scope')

    def test_invented_numbers_are_rejected(self):
        from .services import assistant_brain as brain
        with mock.patch.object(brain, '_retrieval', return_value=self._docs(0.9)), \
                mock.patch.object(brain, 'resolve_model', return_value='api:m'), \
                mock.patch.object(brain, 'chat_completion',
                                  return_value=('This feature saves exactly 4321 litres every single day.', 'api:m')):
            d = brain.answer_question('Tell me about the zorblax feature', region_id=self.region.id)
        self.assertNotIn('4321', d['answer'])


class AssistantTranslationTests(SimpleTestCase):
    def test_every_farm_answer_text_is_translated(self):
        import ast
        import polib
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / 'dashboard' / 'services' / 'farm_qa.py').read_text(encoding='utf-8'))
        ids = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and getattr(node.func, 'id', None) == '_' and node.args
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                ids.add(node.args[0].value)
            if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', '') in (
                    'STAGE_MSG', 'METHOD_MSG', 'TEXTURE_MSG', 'CLASS_MSG', 'KIND_MSG', 'TASK_TITLE', 'SOURCES'):
                ids |= {v.value for v in node.value.values}
            if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', '') == 'SUGGESTIONS':
                ids |= {v.value for v in node.value.elts}
        for lang in ('fr', 'ar'):
            po = {e.msgid for e in polib.pofile(str(root / 'locale' / lang / 'LC_MESSAGES' / 'django.po')) if e.msgstr}
            self.assertEqual(sorted(ids - po), [], lang)


class FarmActivityAndTasksTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.farmer = User.objects.create_user('nour', password='pw-12345')
        self.farmer.profile.role = 'farmer'
        self.farmer.profile.save()
        self.other = User.objects.create_user('omar', password='pw-12345')
        self.other.profile.role = 'farmer'
        self.other.profile.save()
        for target, value in (('dashboard.services.farmer_service.ensure_soil', None),
                              ('dashboard.services.farmer_service.farm_weather', {'forecast': {}})):
            p = mock.patch(target, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        today = date.today()
        self.weather = [{'date': today + timedelta(days=k), 'precip': 0, 'et0': 6.0, 'tmax': 30,
                         'wind': 10, 'precip_prob': 0} for k in range(-60, 16)]
        p = mock.patch('dashboard.services.irrigation_schedule.fetch_daily_water', return_value=self.weather)
        p.start()
        self.addCleanup(p.stop)
        self.client.force_login(self.farmer)

    def _farm(self, **extra):
        body = {'name': 'Orchard', 'boundary': _SQUARE, 'crop': 'olive', 'irrigated': True,
                'irrigation_method': 'drip', **extra}
        r = self.client.post('/farmer/api/farms/', json.dumps(body), content_type='application/json')
        return r.json()['farm']['id']

    def _log(self, farm_id, **body):
        return self.client.post(f'/farmer/api/farms/{farm_id}/activities/', json.dumps(body),
                                content_type='application/json')

    def _tasks(self, farm_id):
        return self.client.get(f'/farmer/api/farms/{farm_id}/tasks/').json()['tasks']

    def test_watering_log_updates_the_farm_and_can_be_undone(self):
        farm_id = self._farm()
        day = (date.today() - timedelta(days=2)).isoformat()
        r = self._log(farm_id, kind='irrigation', date=day, amount_mm=12)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['farm']['last_irrigation_date'], day)
        ir = self.client.get(f'/farmer/api/farms/{farm_id}/irrigation/').json()
        self.assertEqual(ir['basis'], 'last_irrigation')
        self.assertEqual(ir['logged'], [{'date': day, 'gross_mm': 12.0}])

        aid = r.json()['activity']['id']
        gone = self.client.delete(f'/farmer/api/farms/{farm_id}/activities/{aid}/')
        self.assertIsNone(gone.json()['farm']['last_irrigation_date'])

    def test_activity_validation_and_isolation(self):
        farm_id = self._farm()
        future = (date.today() + timedelta(days=1)).isoformat()
        self.assertEqual(self._log(farm_id, kind='irrigation', date=future).status_code, 400)
        self.assertEqual(self._log(farm_id, kind='dance').status_code, 400)
        self.assertEqual(self._log(farm_id, kind='fertilizer', amount_mm=10).status_code, 400)
        self.assertEqual(self._log(farm_id, kind='irrigation', status='maybe').status_code, 400)
        aid = self._log(farm_id, kind='irrigation').json()['activity']['id']
        self.client.force_login(self.other)
        self.assertEqual(self._log(farm_id, kind='irrigation').status_code, 404)
        self.assertEqual(self.client.delete(f'/farmer/api/farms/{farm_id}/activities/{aid}/').status_code, 404)
        self.assertEqual(self.client.get(f'/farmer/api/farms/{farm_id}/tasks/').status_code, 404)

    def test_forgotten_watering_becomes_a_question_until_answered(self):
        farm_id = self._farm()
        self._log(farm_id, kind='irrigation', date=(date.today() - timedelta(days=25)).isoformat())
        tasks = self._tasks(farm_id)
        ask = next(t for t in tasks if t['key'].startswith('irr-missed:'))
        self.assertEqual(ask['state'], 'ask')
        self.assertEqual(tasks[0], ask)  # questions first
        self.assertTrue(any(t['key'].startswith('irr:') and t['state'] == 'today' for t in tasks))

        self._log(farm_id, kind='irrigation', status='skipped', task_key=ask['key'])
        self.assertFalse(any(t['key'].startswith('irr-missed:') for t in self._tasks(farm_id)))

        self._log(farm_id, kind='irrigation', amount_mm=40, task_key='irr:' + date.today().isoformat())
        ir = self.client.get(f'/farmer/api/farms/{farm_id}/irrigation/').json()
        self.assertGreater(ir['now']['available_pct'], 50)

    def test_unknown_history_asks_for_the_last_watering(self):
        farm_id = self._farm()
        self.assertTrue(any(t['key'] == 'irr-last' for t in self._tasks(farm_id)))

    def test_fertilizer_reminder_then_question(self):
        sowing = date.today() - timedelta(days=53)  # wheat: tillering N at day 50
        farm_id = self._farm(crop='wheat', irrigated=False, sowing_date=sowing.isoformat())
        ask = next(t for t in self._tasks(farm_id) if t['kind'] == 'fertilizer')
        self.assertEqual(ask['state'], 'ask')
        self.assertIn('Ammonium nitrate', ask['title']['params']['product'])
        self.assertIn('farm', ask['fertilizer'])  # quantity for this farm's area
        self.assertTrue(any(h['code'] == 'how_fert_alt' for h in ask['how']))
        self._log(farm_id, kind='fertilizer', task_key=ask['key'],
                  date=(sowing + timedelta(days=50)).isoformat())
        self.assertFalse(any(t['key'] == ask['key'] for t in self._tasks(farm_id)))

    def _edit(self, farm_id, aid, **body):
        return self.client.patch(f'/farmer/api/farms/{farm_id}/activities/{aid}/', json.dumps(body),
                                 content_type='application/json')

    def test_correcting_a_past_answer_changes_the_plan(self):
        farm_id = self._farm()
        self._log(farm_id, kind='irrigation', date=(date.today() - timedelta(days=25)).isoformat())
        ask = next(t for t in self._tasks(farm_id) if t['key'].startswith('irr-missed:'))
        # The farmer answered "not yet"... but in fact watered 2 days ago.
        aid = self._log(farm_id, kind='irrigation', status='skipped', task_key=ask['key']).json()['activity']['id']
        dry = self.client.get(f'/farmer/api/farms/{farm_id}/irrigation/').json()
        two_days = (date.today() - timedelta(days=2)).isoformat()
        r = self._edit(farm_id, aid, status='done', date=two_days, amount_mm=30)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['farm']['last_irrigation_date'], two_days)
        self.assertEqual(r.json()['activity']['task_key'], ask['key'])  # still answers that question
        wet = self.client.get(f'/farmer/api/farms/{farm_id}/irrigation/').json()
        self.assertGreater(wet['now']['available_pct'], dry['now']['available_pct'])

        # A smaller amount than recorded: less water in the soil again.
        self._edit(farm_id, aid, amount_mm=5)
        less = self.client.get(f'/farmer/api/farms/{farm_id}/irrigation/').json()
        self.assertLess(less['now']['available_pct'], wet['now']['available_pct'])

        # Wrong day: moving it back moves the farm's last watering back too.
        older = (date.today() - timedelta(days=10)).isoformat()
        r = self._edit(farm_id, aid, date=older)
        self.assertEqual(r.json()['farm']['last_irrigation_date'], older)

        # Back to "not done": no amount is kept.
        r = self._edit(farm_id, aid, status='skipped')
        self.assertIsNone(r.json()['activity']['amount_mm'])

    def test_forgotten_past_activity_and_sowing_correction(self):
        farm_id = self._farm(crop='wheat', irrigated=False)
        aid = self._log(farm_id, kind='sowing', date=(date.today() - timedelta(days=30)).isoformat()).json()['activity']['id']
        fixed = (date.today() - timedelta(days=40)).isoformat()
        self.assertEqual(self._edit(farm_id, aid, date=fixed).json()['farm']['sowing_date'], fixed)
        gone = self.client.delete(f'/farmer/api/farms/{farm_id}/activities/{aid}/').json()
        self.assertIsNone(gone['farm']['sowing_date'])

    def test_activity_edit_validation_and_isolation(self):
        farm_id = self._farm()
        aid = self._log(farm_id, kind='irrigation').json()['activity']['id']
        future = (date.today() + timedelta(days=3)).isoformat()
        self.assertEqual(self._edit(farm_id, aid, date=future).status_code, 400)
        self.assertEqual(self._edit(farm_id, aid, amount_mm=900).status_code, 400)
        self.assertEqual(self._edit(farm_id, aid, status='maybe').status_code, 400)
        self.client.force_login(self.other)
        self.assertEqual(self._edit(farm_id, aid, amount_mm=10).status_code, 404)

    def test_sowing_answer_sets_the_sowing_date(self):
        farm_id = self._farm(crop='wheat', irrigated=False)
        day = (date.today() - timedelta(days=3)).isoformat()
        r = self._log(farm_id, kind='sowing', date=day)
        self.assertEqual(r.json()['farm']['sowing_date'], day)


class FarmSoilLookupTests(SimpleTestCase):
    @staticmethod
    def _farm():
        from types import SimpleNamespace
        return SimpleNamespace(pk=None, soil=None, centroid_lat=37.0, centroid_lon=9.6)

    def test_masked_centre_falls_back_to_nearby_probe(self):
        from .services import farmer_service as fs
        found = {'sand': 30.0, 'silt': 30.0, 'clay': 40.0, 'ph': 7.6, 'om': 2.0}
        with mock.patch('dashboard.services.soilgrids.fetch_point',
                        side_effect=lambda lat, lon, timeout: found if lat > 37.0 else None):
            soil = fs.ensure_soil(self._farm())
        self.assertEqual(soil['clay'], 40.0)
        self.assertIn('note', soil)

    def test_no_data_is_remembered_but_network_errors_are_not(self):
        from .services import farmer_service as fs
        farm = self._farm()
        with mock.patch('dashboard.services.soilgrids.fetch_point', return_value=None) as fetch:
            self.assertIsNone(fs.ensure_soil(farm))
            self.assertIsNone(fs.ensure_soil(farm))
        self.assertEqual(farm.soil, {'unavailable': True})
        self.assertEqual(fetch.call_count, 5)  # centre + 4 probes, once only
        self.assertIsNone(fs.suitability_soil(farm.soil))

        farm = self._farm()
        with mock.patch('dashboard.services.soilgrids.fetch_point', side_effect=OSError('down')):
            self.assertIsNone(fs.ensure_soil(farm))
        self.assertIsNone(farm.soil)


def _fake_jwt(**payload):
    import base64 as _b64

    def part(o):
        return _b64.urlsafe_b64encode(json.dumps(o).encode()).decode().rstrip('=')
    return f"{part({'alg': 'HS256'})}.{part(payload)}.sig"


_SF_ENV = {
    'SMARTFARM_EMAIL': 'farmer@example.tn',
    'SMARTFARM_UID': 'u-42',
    'SMARTFARM_SENSOR': '88:57:21:D2:1C:08',
}


def _sf_env(**overrides):
    import time as _time
    now = int(_time.time())
    env = dict(_SF_ENV, SMARTFARM_PASSWORD='', SMARTFARM_REFRESH_TOKEN=_fake_jwt(
        email='farmer@example.tn', id='u-42', iat=now, exp=now + 60 * 86400))
    env.update(overrides)
    return mock.patch.dict('os.environ', env)


_SF_SENSORS = [{'code': '88:57:21:D2:1C:08', 'created_at': '2026-01-10', 'etat': 'optimal',
                'mv1': 20, 'mv2': 40, 'mv3': 60,
                'fields': {'name': 'Parcelle Mateur', 'Latitude': '37.04', 'Longitude': '9.66'}}]


def _sf_row(stamp, m=(35, 42, 50), niv=('2800', '2600', '2400'), ts='18.5'):
    return {'time': stamp + 'Z', 'timestamp_arduino': stamp, 'ts': ts,
            'niv1': niv[0], 'niv2': niv[1], 'niv3': niv[2], 'mv1': m[0], 'mv2': m[1], 'mv3': m[2]}


class SmartFarmParsingTests(SimpleTestCase):
    def test_probe_clock_is_tunis_wall_time(self):
        from .services import smartfarm
        r = smartfarm.parse_reading(_sf_row('2026-11-04T09:00:00'))
        self.assertEqual(r['measured_at'].isoformat(), '2026-11-04T08:00:00+00:00')

    def test_open_circuit_and_disconnected_temperature_are_dropped(self):
        from .services import smartfarm
        r = smartfarm.parse_reading(_sf_row('2026-11-04T09:00:00', m=(0, 41, 52),
                                            niv=('4095', '2600', '2400'), ts='-127'))
        self.assertIsNone(r['moisture_1'])
        self.assertEqual(r['moisture_2'], 41.0)
        self.assertIsNone(r['soil_temp_c'])

    def test_falls_back_to_server_time(self):
        from .services import smartfarm
        row = _sf_row('2026-11-04T09:00:00')
        row['timestamp_arduino'] = 'null'
        self.assertEqual(smartfarm.parse_reading(row)['measured_at'].isoformat(), '2026-11-04T09:00:00+00:00')

    def test_credential_problems_are_named(self):
        from .services import smartfarm
        import time as _time
        now = int(_time.time())
        base = {'email': 'farmer@example.tn', 'uid': 'u-42', 'sensor': 'x'}
        ok = _fake_jwt(email='farmer@example.tn', id='u-42', iat=now, exp=now + 60 * 86400)
        self.assertIsNone(smartfarm.credential_problem(dict(base, refresh_token=ok)))
        short = _fake_jwt(email='farmer@example.tn', id='u-42', iat=now, exp=now + 86400)
        self.assertIn('access token', smartfarm.credential_problem(dict(base, refresh_token=short)))
        self.assertIn('EMAIL', smartfarm.credential_problem(dict(base, email='Farmer@example.tn', refresh_token=ok)))
        self.assertIn('not a token', smartfarm.credential_problem(dict(base, refresh_token='abc')))

    def test_pasted_json_and_quotes_are_unwrapped(self):
        from .services import smartfarm
        with _sf_env(SMARTFARM_REFRESH_TOKEN='{"refreshToken": "a.b.c"}', SMARTFARM_EMAIL='"farmer@example.tn"'):
            c = smartfarm.credentials()
        self.assertEqual(c['refresh_token'], 'a.b.c')
        self.assertEqual(c['email'], 'farmer@example.tn')


class SmartFarmSyncTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        Region.objects.create(name='Mateur', latitude=37.04, longitude=9.66)
        # Readings 3 days ago and yesterday, 09:00 on the probe's (Tunis) clock;
        # nothing 2 days ago or today.
        import datetime as _dt
        from zoneinfo import ZoneInfo
        today = _dt.datetime.now(ZoneInfo('Africa/Tunis')).date()
        self.days = [today - _dt.timedelta(days=k) for k in (3, 2, 1, 0)]
        self.history = {'history': [_sf_row(f'{self.days[0]}T09:00:00'),
                                    _sf_row(f'{self.days[2]}T09:00:00', m=(31, 40, 49))], 'totalPages': 1}

        def fake_get(path):
            return _SF_SENSORS if path == '/sensor/sensors' else self.history
        p = mock.patch('dashboard.services.smartfarm._get', side_effect=fake_get)
        p.start()
        self.addCleanup(p.stop)
        e = _sf_env()
        e.start()
        self.addCleanup(e.stop)
        User = get_user_model()
        self.admin = User.objects.create_user('sf_admin', password='pw-12345')
        self.admin.profile.role = 'superadmin'
        self.admin.profile.save()

    def test_sync_creates_probe_and_is_idempotent(self):
        from .models import Sensor, SoilProbeReading
        from .services import smartfarm
        out = smartfarm.sync(30)
        self.assertEqual((out['fetched'], out['added']), (2, 2))
        s = Sensor.objects.get(external_source='smartfarm')
        self.assertEqual(s.sensor_type, 'soil')
        self.assertEqual(s.region.name, 'Mateur')
        self.assertEqual(s.external_meta['depths'], [20, 40, 60])
        self.assertEqual(smartfarm.sync(30)['added'], 0)
        self.assertEqual(SoilProbeReading.objects.count(), 2)

    def test_api_returns_latest_reading(self):
        self.client.force_login(self.admin)
        d = self.client.get('/api/sensors/smartfarm/').json()
        self.assertTrue(d['configured'])
        self.assertEqual(d['latest']['m'], [31.0, 40.0, 49.0])
        self.assertEqual(d['root_zone'], 40.0)
        self.assertEqual(d['levels'], ['good', 'good', 'good'])
        self.assertEqual(d['readings_total'], 2)

    def test_api_without_credentials(self):
        self.client.force_login(self.admin)
        with mock.patch.dict('os.environ', {'SMARTFARM_REFRESH_TOKEN': '', 'SMARTFARM_PASSWORD': ''}):
            self.assertEqual(self.client.get('/api/sensors/smartfarm/').json(), {'configured': False})

    def test_sync_failure_keeps_stored_readings(self):
        from .models import Sensor
        from .services import smartfarm
        smartfarm.sync(30)
        Sensor.objects.update(last_synced_at=None)
        self.client.force_login(self.admin)
        err = smartfarm.SmartFarmError('SmartFarm auth failed: 401')
        with mock.patch('dashboard.services.smartfarm._get', side_effect=err):
            d = self.client.get('/api/sensors/smartfarm/').json()
        self.assertIn('401', d['error'])
        self.assertEqual(d['latest']['m'], [31.0, 40.0, 49.0])

    def test_telemetry_for_probe_is_real(self):
        from .services import smartfarm
        sid = smartfarm.sync(30)['sensor_id']
        self.client.force_login(self.admin)
        d = self.client.get(f'/api/sensors/{sid}/telemetry/?range=24h').json()
        self.assertTrue(d['real'])
        self.assertEqual(d['sensor_type'], 'smartfarm')
        # One point per day from the first reading to today; empty days are gaps.
        self.assertEqual(d['series']['probe_moisture_1'], [35.0, None, 31.0, None])
        self.assertEqual(len(d['timestamps']), 4)

    def test_api_daily_series_has_every_day(self):
        self.client.force_login(self.admin)
        daily = self.client.get('/api/sensors/smartfarm/').json()['daily']
        self.assertEqual([x['date'] for x in daily], [str(x) for x in self.days])
        self.assertEqual([x['n'] for x in daily], [1, 0, 1, 0])
        self.assertEqual(daily[2]['m'], [31.0, 40.0, 49.0])

    def test_sensors_page_marks_probe_as_real(self):
        from .services import smartfarm
        smartfarm.sync(30)
        self.client.force_login(self.admin)
        html = self.client.get('/sensors/').content.decode()
        self.assertIn('id="smartfarm-panel"', html)
        self.assertIn('Real data · SmartFarm', html)


class SmartFarmPasswordLoginTests(TestCase):
    """Email + password, the way SmartFarm's own login form signs in."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        e = mock.patch.dict('os.environ', {'SMARTFARM_EMAIL': 'farmer@example.tn', 'SMARTFARM_PASSWORD': 'secret',
                                           'SMARTFARM_UID': '', 'SMARTFARM_REFRESH_TOKEN': '', 'SMARTFARM_SENSOR': ''})
        e.start()
        self.addCleanup(e.stop)

    def _resp(self, body, status=200):
        r = mock.Mock(status_code=status, ok=status < 400)
        r.json.return_value = body
        return r

    def test_email_and_password_are_enough(self):
        from .services import smartfarm
        self.assertTrue(smartfarm.configured())
        with mock.patch.dict('os.environ', {'SMARTFARM_PASSWORD': ''}):
            self.assertEqual(smartfarm.missing_settings(), ['SMARTFARM_PASSWORD'])

    def test_login_posts_credentials_and_uses_token(self):
        from .services import smartfarm
        with mock.patch('dashboard.services.smartfarm.requests.post',
                        return_value=self._resp({'token': 'tok', 'refreshToken': 'r', 'result': {}})) as post:
            self.assertEqual(smartfarm._access_token(), 'tok')
        url, kw = post.call_args[0][0], post.call_args[1]
        self.assertTrue(url.endswith('/login'))
        self.assertEqual(kw['json'], {'email': 'farmer@example.tn', 'password': 'secret'})

    def test_wrong_password_is_named(self):
        from .services import smartfarm
        with mock.patch('dashboard.services.smartfarm.requests.post',
                        return_value=self._resp({'type': 'danger', 'status': '400'})):
            with self.assertRaisesMessage(smartfarm.SmartFarmError, 'wrong password'):
                smartfarm._access_token()

    def test_first_probe_is_used_when_no_code_given(self):
        from .services import smartfarm

        def fake_get(path):
            if path == '/sensor/sensors':
                return _SF_SENSORS
            return {'history': [_sf_row('2026-11-04T09:00:00')], 'totalPages': 1}
        with mock.patch('dashboard.services.smartfarm._get', side_effect=fake_get):
            probe = smartfarm.fetch_probe(7)
        self.assertEqual(probe['code'], '88:57:21:D2:1C:08')
        self.assertEqual(len(probe['readings']), 1)


class NoFakeSensorTests(TestCase):
    """The sensors page never invents stations or readings."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user('nf_admin', password='pw-12345')
        self.admin.profile.role = 'superadmin'
        self.admin.profile.save()
        self.client.force_login(self.admin)

    def test_page_does_not_seed_demo_stations(self):
        from .models import Sensor
        self.assertEqual(self.client.get('/sensors/').status_code, 200)
        self.assertEqual(Sensor.objects.count(), 0)

    def test_pin_without_data_source_has_no_graph_data(self):
        from .models import Sensor
        s = Sensor.objects.create(name='Hand pin', sensor_type='aws', latitude=37, longitude=9.6)
        d = self.client.get(f'/api/sensors/{s.id}/telemetry/?range=7d').json()
        self.assertTrue(d['no_data'])
        self.assertEqual(d['series'], {})
        html = self.client.get('/sensors/').content.decode()
        self.assertNotIn('battery_pct', html)
        self.assertIn('No data connected', html)


class SentinelTileTests(TestCase):
    """Map-layer tiles over the catchment (Earth Engine mocked)."""

    META = {'version': 2,
            'windows': {k: ['2026-10-01', '2026-10-30'] for k in
                        ('ndvi', 'ndwi', 'temp', 'rain', 'spi', 'drought', 'drought_soil', 'drought_veg')},
            'domains': {'temp': [18.0, 22.0], 'rain': [0.0, 150.0]},
            'drought_km2': {'none': 1000.0, 'watch': 300.0, 'warning': 250.0, 'alert': 50.0}}

    def setUp(self):
        import numpy as np
        User = get_user_model()
        self.admin = User.objects.create_user('s2_admin', password='pw-12345')
        self.admin.profile.role = 'superadmin'
        self.admin.profile.save()
        self.client.force_login(self.admin)
        vals = np.full((256, 256), np.nan, dtype='float32')
        vals[:, 128:] = 0.6
        for target, kw in (('tile_values', {'return_value': vals}), ('day_meta', {'return_value': self.META})):
            p = mock.patch(f'dashboard.services.sentinel_tiles.{target}', **kw)
            p.start()
            self.addCleanup(p.stop)

    def _tile(self, z=11):
        from .services import sentinel_tiles as st
        w, s, e, n = st.basin_bounds()
        x, y = st.lonlat_to_tile((w + e) / 2, (s + n) / 2, z)
        return int(x), int(y)

    def test_tile_is_coloured_png_with_clear_no_data(self):
        import io
        from PIL import Image
        x, y = self._tile()
        r = self.client.get(f'/api/s2/ndvi/11/{x}/{y}.png')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'image/png')
        img = Image.open(io.BytesIO(r.content)).convert('RGBA')
        self.assertEqual(img.getpixel((10, 10))[3], 0)               # no value -> transparent
        self.assertEqual(img.getpixel((200, 10))[3], 255)
        # 0.6 on the NDVI scale 0..0.8 is in the green part of the ramp
        red, green, blue, _ = img.getpixel((200, 10))
        self.assertGreater(green, red)

    def test_tiles_outside_basin_and_unknown_index_are_refused(self):
        x, y = self._tile()
        self.assertEqual(self.client.get(f'/api/s2/ndvi/11/{x + 40}/{y}.png').status_code, 404)
        self.assertEqual(self.client.get('/api/s2/ndvi/5/0/0.png').status_code, 404)
        self.assertEqual(self.client.get(f'/api/s2/evi/11/{x}/{y}.png').status_code, 400)

    def test_value_at_point(self):
        from .services import sentinel_tiles as st
        w, s, e, n = st.basin_bounds()
        z = 11
        x, y = self._tile(z)
        # a point in the right half of that tile
        lon = (x + 0.75) / 2 ** z * 360 - 180
        import math
        lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 0.5) / 2 ** z))))
        d = self.client.get(f'/api/s2/ndvi/value/?lat={lat}&lon={lon}&z={z}').json()
        self.assertAlmostEqual(d['value'], 0.6, places=3)

    def test_earth_engine_failure_is_503(self):
        from .services import sentinel_tiles as st
        x, y = self._tile()
        with mock.patch('dashboard.services.sentinel_tiles.tile_values', side_effect=st.SentinelUnavailable('quota')):
            self.assertEqual(self.client.get(f'/api/s2/ndwi/11/{x}/{y}.png').status_code, 503)

    def test_legend_and_page_controls(self):
        d = self.client.get('/api/s2/legend/').json()
        self.assertEqual(d['ndvi']['domain'], [0.0, 0.8])
        self.assertEqual(d['ndwi']['domain'], [-0.3, 0.4])
        self.assertEqual(d['window']['days'], 30)
        html = self.client.get('/analysis/').content.decode()
        self.assertIn('data-mode="ndvi"', html)
        self.assertIn('data-mode="ndwi"', html)


class StationClimateTests(TestCase):
    """Continuing the two stations' daily climate (Earth Engine mocked)."""

    def setUp(self):
        import datetime as _dt
        import pandas as _pd
        from .services import station_climate as sc
        self.sc = sc
        self.region, _ = Region.objects.get_or_create(name='Ichkeul')
        days = [_dt.date(2026, 1, 1) + _dt.timedelta(days=i) for i in range(3)]
        self.days = days
        self.raw = _pd.DataFrame({'tmean': [12.0, 13.0, 14.0], 'tmin': [8.0, 9.0, 10.0], 'tmax': [16.0, 17.0, 18.0],
                                  'rh': [80.0, 75.0, 70.0], 'ws2': [2.0, 3.0, 4.0], 'solar': [9.0, 10.0, 11.0]}, index=days)
        flat = {str(m): 0.0 for m in range(1, 13)}
        one = {str(m): 1.0 for m in range(1, 13)}
        cal = {'add': {'tmean': dict(flat, **{'1': -0.5}), 'tmin': flat, 'tmax': flat, 'rh': flat},
               'ratio': {'ws2': dict(one, **{'1': 0.5})}}
        self.cal = {'stations': {st['key']: cal for st in sc.STATIONS}}
        self.chirps = _pd.Series({days[0]: 4.2, days[1]: 0.0})
        self.imerg = _pd.Series({days[2]: 7.0})
        for target, value in (('load_calibration', self.cal), ('_ee', object())):
            p = mock.patch(f'dashboard.services.station_climate.{target}', return_value=value)
            p.start()
            self.addCleanup(p.stop)
        for target, attr in (('pull_era5', 'raw'), ('pull_chirps', 'chirps'), ('pull_imerg', 'imerg')):
            p = mock.patch(f'dashboard.services.station_climate.{target}', side_effect=lambda *a, _a=attr, **k: getattr(self, _a))
            p.start()
            self.addCleanup(p.stop)

    def _rows(self, lat):
        from .models import ClimateMetrics
        return {r['measurement_date'].date() if hasattr(r['measurement_date'], 'date') else r['measurement_date']: r
                for r in ClimateMetrics.objects.filter(latitude=lat).values()}

    def test_corrections_rain_sources_and_et0(self):
        import datetime as _dt
        out = self.sc.update(end=_dt.date(2026, 1, 3))
        self.assertEqual(out['st1']['created'], 3)
        r = self._rows(37.010)
        first = r[self.days[0]]
        self.assertEqual(float(first['temperature_mean_c']), 11.5)          # +(-0.5) January offset
        self.assertEqual(float(first['wind_speed_ms']), 1.0)                # x0.5 January ratio
        self.assertEqual((float(first['rainfall_mm']), first['rainfall_source']), (4.2, 'CHIRPS'))
        self.assertEqual((float(r[self.days[2]]['rainfall_mm']), r[self.days[2]]['rainfall_source']), (7.0, 'IMERG'))
        self.assertGreater(float(first['evapotranspiration_et0_mmday']), 0.5)
        self.assertLess(float(first['evapotranspiration_et0_mmday']), 3.0)

    def test_provisional_rain_is_replaced_and_rerun_is_idempotent(self):
        import datetime as _dt
        import pandas as _pd
        self.sc.update(end=_dt.date(2026, 1, 3))
        # Next run restarts at the provisional IMERG day and swaps in CHIRPS.
        self.assertEqual(self.sc._pending_start(self.region, self.sc.STATIONS[0]), self.days[2])
        self.chirps = _pd.Series({d: v for d, v in zip(self.days, (4.2, 0.0, 6.1))})
        out = self.sc.update(end=_dt.date(2026, 1, 3))
        self.assertEqual(out['st1']['from'], '2026-01-03')
        r = self._rows(37.010)[self.days[2]]
        self.assertEqual((float(r['rainfall_mm']), r['rainfall_source']), (6.1, 'CHIRPS'))
        from .models import ClimateMetrics
        self.assertEqual(ClimateMetrics.objects.filter(latitude=37.010).count(), 3)

    def test_original_dataset_rows_are_never_touched(self):
        import datetime as _dt
        from .models import ClimateMetrics, ObservationYear
        y = ObservationYear.objects.create(label='2025')
        ClimateMetrics.objects.create(region=self.region, year=y, measurement_date=_dt.date(2025, 12, 31),
                                      latitude=37.010, longitude=9.731, rainfall_mm=1.0, temperature_mean_c=10.0)
        self.sc.update(start=_dt.date(2025, 12, 1), end=_dt.date(2026, 1, 3))
        old = ClimateMetrics.objects.get(latitude=37.010, measurement_date=_dt.date(2025, 12, 31))
        self.assertEqual((float(old.rainfall_mm), float(old.temperature_mean_c)), (1.0, 10.0))

    def test_corrected_temperatures_stay_ordered(self):
        import pandas as _pd
        raw = _pd.DataFrame({'tmean': [10.0], 'tmin': [9.9], 'tmax': [10.1], 'rh': [99.0], 'ws2': [1.0], 'solar': [5.0]},
                            index=[self.days[0]])
        cal = {'add': {'tmean': {'1': 0.0}, 'tmin': {'1': 0.5}, 'tmax': {'1': -0.5}, 'rh': {'1': 5.0}},
               'ratio': {'ws2': {'1': 1.0}}}
        out = self.sc.apply_calibration(raw, cal).iloc[0]
        self.assertLessEqual(out['tmin'], out['tmean'])
        self.assertGreaterEqual(out['tmax'], out['tmean'])
        self.assertEqual(out['rh'], 100.0)


class ClimateLayerTests(TestCase):
    """Temperature / rainfall / SPI-3 map layers (Earth Engine mocked)."""

    def setUp(self):
        User = get_user_model()
        admin = User.objects.create_user('layer_admin', password='pw-12345')
        admin.profile.role = 'superadmin'
        admin.profile.save()
        self.client.force_login(admin)
        p = mock.patch('dashboard.services.sentinel_tiles.day_meta', return_value=SentinelTileTests.META)
        p.start()
        self.addCleanup(p.stop)

    def _tile(self, z):
        from .services import sentinel_tiles as st
        w, s, e, n = st.basin_bounds()
        x, y = st.lonlat_to_tile((w + e) / 2, (s + n) / 2, z)
        return int(x), int(y)

    def test_spi_is_inverse_normal_of_rank_position(self):
        import numpy as np
        from .services import sentinel_tiles as st
        out = st._finish('spi', np.array([0.5, 0.8413, 0.0228, -9999], dtype='float32'))
        self.assertAlmostEqual(float(out[0]), 0.0, places=3)
        self.assertAlmostEqual(float(out[1]), 1.0, places=2)
        self.assertAlmostEqual(float(out[2]), -2.0, places=2)
        self.assertTrue(np.isnan(out[3]))

    def test_climate_values_are_not_limited_to_index_range(self):
        import numpy as np
        from .services import sentinel_tiles as st
        out = st._finish('temp', np.array([19.6, -9999], dtype='float32'))
        self.assertAlmostEqual(float(out[0]), 19.6, places=4)
        self.assertTrue(np.isnan(out[1]))

    def test_temperature_tile_uses_the_daily_stretched_scale(self):
        import io
        import numpy as np
        from PIL import Image
        hot = np.full((256, 256), 22.0, dtype='float32')     # top of the 18-22 scale
        with mock.patch('dashboard.services.sentinel_tiles.tile_values', return_value=hot):
            x, y = self._tile(10)
            r = self.client.get(f'/api/s2/temp/10/{x}/{y}.png')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Image.open(io.BytesIO(r.content)).convert('RGB').getpixel((5, 5)), (0xB8, 0x28, 0x2E))

    def test_coarse_layers_stop_at_their_zoom(self):
        x, y = self._tile(13)
        self.assertEqual(self.client.get(f'/api/s2/rain/13/{x}/{y}.png').status_code, 404)

    def test_legend_lists_units_windows_and_scales(self):
        d = self.client.get('/api/s2/legend/').json()
        self.assertEqual((d['temp']['unit'], d['temp']['domain']), ('°C', [18.0, 22.0]))
        self.assertEqual((d['rain']['unit'], d['rain']['domain']), ('mm', [0.0, 150.0]))
        self.assertEqual(d['spi']['domain'], [-2.0, 2.0])
        self.assertEqual(d['spi']['window'], {'from': '2026-10-01', 'to': '2026-10-30'})
        html = self.client.get('/analysis/').content.decode()
        for mode in ('temp', 'rain', 'spi'):
            self.assertIn(f'data-mode="{mode}"', html)

    def test_drought_classes_are_whole_levels(self):
        import numpy as np
        from .services import sentinel_tiles as st
        out = st._finish('drought', np.array([0, 1, 2, 3, 4, -9999], dtype='float32'))
        self.assertEqual(out[:4].tolist(), [0.0, 1.0, 2.0, 3.0])
        self.assertTrue(np.isnan(out[4]) and np.isnan(out[5]))

    def test_drought_tile_colours_each_level(self):
        import io
        import numpy as np
        from PIL import Image
        levels = np.zeros((256, 256), dtype='float32')
        levels[:, 64:128], levels[:, 128:192], levels[:, 192:] = 1, 2, 3
        with mock.patch('dashboard.services.sentinel_tiles.tile_values', return_value=levels):
            x, y = self._tile(10)
            img = Image.open(io.BytesIO(self.client.get(f'/api/s2/drought/10/{x}/{y}.png').content)).convert('RGB')
        self.assertEqual([img.getpixel((px, 5)) for px in (10, 70, 140, 200)],
                         [(0x38, 0xA8, 0x8A), (0xE7, 0xA8, 0x3B), (0xEE, 0x84, 0x34), (0xD9, 0x65, 0x65)])

    def test_drought_click_explains_the_level(self):
        import numpy as np
        detail = {'spi': -1.4, 'soil': -1.2, 'vegetation': -0.3, 'water': False}
        with mock.patch('dashboard.services.sentinel_tiles.tile_values', return_value=np.full((256, 256), 2.0, dtype='float32')),                 mock.patch('dashboard.services.sentinel_tiles.drought_detail', return_value=detail):
            d = self.client.get('/api/s2/drought/value/?lat=37.05&lon=9.6&z=11').json()
        self.assertEqual((d['value'], d['detail']), (2.0, detail))

    def test_legend_reports_measured_drought_areas(self):
        d = self.client.get('/api/s2/legend/').json()['drought']
        self.assertEqual(d['areas_km2']['warning'], 250.0)
        self.assertEqual(d['domain'], [0, 3])
        html = self.client.get('/analysis/').content.decode()
        self.assertIn('id="zone-alert-km2"', html)
        self.assertNotIn('2 Station Origin', html)


class StationSpeiTests(TestCase):
    """Monthly SPEI-3 continued after the station dataset."""

    def test_severity_classes_match_the_stored_thresholds(self):
        from .services.station_climate import severity_class
        self.assertEqual([severity_class(v) for v in (0.3, -0.48, -0.5, -0.99, -1.0, -1.5, -2.0, -3.0)],
                         ['None', 'None', 'Abnormally Dry', 'Abnormally Dry', 'Moderate Drought',
                          'Severe Drought', 'Extreme Drought', 'Extreme Drought'])

    def test_spei_is_standard_normal_on_its_reference(self):
        import numpy as np
        import pandas as pd
        from .services.station_climate import spei_from_balance
        rng = np.random.default_rng(1)
        idx = pd.date_range('1996-01-31', periods=360, freq='ME')
        # rain-like (right-skewed) monthly water balance, as at the stations
        bal = pd.Series(rng.gamma(2.0, 60.0, 360) - 150, index=idx)
        s = spei_from_balance(bal, bal).dropna()
        self.assertEqual(len(s), 360)
        self.assertLess(abs(s.mean()), 0.15)
        self.assertLess(abs(s.std() - 1), 0.15)
        # a month much drier than any reference value is strongly negative or out of range (NaN)
        low = spei_from_balance(pd.Series([-400.0], index=[pd.Timestamp('2026-07-31')]), bal)
        self.assertTrue(np.isnan(low.iloc[0]) or low.iloc[0] < -2)

    def test_new_months_only_and_basin_is_the_station_mean(self):
        import datetime as _dt
        import pandas as pd
        from .models import DroughtIndices, ObservationYear
        from .services import station_climate as sc
        region, _ = Region.objects.get_or_create(name='Ichkeul')
        y = ObservationYear.objects.create(label='2025')
        DroughtIndices.objects.create(region=region, year=y, measurement_date=_dt.date(2025, 12, 31),
                                      latitude=37.010, longitude=9.731, spei_3month=-0.55,
                                      drought_severity_class='Abnormally Dry')
        idx = pd.date_range('1996-01-31', '2026-02-28', freq='ME')
        fake = {'st1': pd.Series(-1.0, index=idx), 'st2': pd.Series(1.0, index=idx)}
        with mock.patch('dashboard.services.station_climate._monthly_balance',
                        side_effect=lambda reg, st: (pd.Series(range(len(idx)), index=idx, dtype=float), _dt.date(2026, 2, 28))), \
                mock.patch('dashboard.services.station_climate.spei_from_balance',
                           side_effect=[fake['st1'], fake['st2']]):
            out = sc.update_spei()
        self.assertEqual(out['months'], ['2026-01', '2026-02'])
        old = DroughtIndices.objects.get(latitude=37.010, measurement_date=_dt.date(2025, 12, 31))
        self.assertEqual(float(old.spei_3month), -0.55)
        basin = DroughtIndices.objects.get(latitude=37.0635, measurement_date=_dt.date(2026, 2, 28))
        self.assertEqual((float(basin.spei_3month), basin.subregion), (0.0, 'merged'))
        st1 = DroughtIndices.objects.get(latitude=37.010, measurement_date=_dt.date(2026, 1, 31))
        self.assertEqual((st1.drought_severity_class, st1.subregion), ('Moderate Drought', 'v8_st_sub_humide'))


class RiskScoreConsistencyTests(TestCase):
    """The analysis risk cards: measured SPI-3, one value per day, one score scale."""

    def test_spi_at_is_not_fooled_by_the_start_of_a_month(self):
        import numpy as np
        from .prediction_engine.physical_helpers import calculate_spi, spi_at
        idx = pd.date_range('1990-01-01', '2026-12-02', freq='D')
        rain = pd.Series(np.full(len(idx), 1.0), index=idx)   # the same rain every day
        # Calendar-month SPI on 2 Dec sees Oct + Nov + only 2 days of Dec: wrongly dry.
        self.assertLess(float(calculate_spi(rain, nmonth=3).iloc[-1]), -1)
        # The rolling 90-day window is exactly normal.
        self.assertAlmostEqual(spi_at(rain + np.random.default_rng(0).normal(0, 0.01, len(idx)).clip(0),
                                      '2026-12-02'), 0.0, delta=0.6)

    def test_two_stations_give_one_rain_value_per_day(self):
        region = Region.objects.create(name='Two Stations')
        year = ObservationYear.objects.create(label='2026')
        for lat, rain in ((37.01, 2.0), (37.117, 4.0)):
            for i in range(3):
                ClimateMetrics.objects.create(region=region, year=year, measurement_date=pd.Timestamp('2026-01-01') + pd.Timedelta(days=i),
                                              latitude=lat, longitude=9.5, rainfall_mm=rain)
        rain = DroughtPredictionPipeline()._observed_daily_rain(region)
        self.assertEqual(len(rain), 3)
        self.assertEqual(rain.tolist(), [3.0, 3.0, 3.0])

    def test_forecast_risk_uses_the_project_scale(self):
        import numpy as np
        from .services.assistant_brain import _score_from_spei
        region = Region.objects.create(name='Scale Region')
        year = ObservationYear.objects.create(label='2025')
        rng = np.random.default_rng(3)
        days = pd.date_range('2010-01-01', '2025-06-30', freq='D')
        ClimateMetrics.objects.bulk_create([ClimateMetrics(region=region, year=year, measurement_date=d,
                                                           rainfall_mm=float(max(0, rng.gamma(0.4, 4))))
                                            for d in days])
        r = DroughtPredictionPipeline().forecast_spi_risk(region, pd.Timestamp('2025-06-30'), 0)
        self.assertEqual(r['risk'], float(_score_from_spei(r['spi3'])))


class DroughtGridTests(TestCase):
    """Gridded SPEI forecast: index standardisation, leakage-free verification, API."""

    def test_glo_spei_is_standard_normal_on_reference_and_not_clipped_just_past_record(self):
        import numpy as np
        from scipy import stats
        from .prediction_engine.drought_grid import glo_cdf, glo_fit
        rng = np.random.default_rng(0)
        ref = -400 + 25 * rng.standard_normal(30)
        params = glo_fit(ref)
        z = stats.norm.ppf(np.clip(glo_cdf(ref, *params), 1e-4, 1 - 1e-4))
        self.assertAlmostEqual(float(z.mean()), 0.0, delta=0.1)
        self.assertAlmostEqual(float(z.std()), 1.0, delta=0.15)
        # 10 mm beyond the driest reference value: very dry, but a finite score,
        # not the clip bound that a maximum-likelihood fit would produce.
        z_new = stats.norm.ppf(glo_cdf(ref.min() - 10, *params))
        self.assertTrue(-3.6 < z_new < -1.5, z_new)

    def _noise_frame(self):
        import numpy as np
        rng = np.random.default_rng(1)
        months = pd.period_range('1981-01', '2016-12', freq='M')
        rows = []
        for cell, (lat, lon) in {'A': (37.0, 9.4), 'B': (37.1, 9.6)}.items():
            for m in months:
                rows.append({'cell': cell, 'month': m, 'moy': m.month, 'lat': lat, 'lon': lon,
                             'P': float(rng.gamma(2, 25)), 'PET': 90.0 + float(rng.normal(0, 5)),
                             'T': 18 + float(rng.normal()), 'SM': 0.25 + float(rng.normal(0, 0.02))})
        df = pd.DataFrame(rows)
        df['D'] = df.P - df.PET
        return df

    def test_verification_does_not_leak_future_information(self):
        from .prediction_engine import drought_grid as dg
        df = dg.add_indices(self._noise_frame())
        with mock.patch.object(dg, 'SCALES', (3, 12)), mock.patch.object(dg, 'LEADS', (1, 4)):
            skill = dg.verify(df, log=lambda s: None)
        # White-noise weather: once the target window is entirely in the future
        # (lead >= scale) nothing can be known -> no skill.
        self.assertLess(skill['3_4']['auc'], 0.65)
        self.assertFalse(skill['3_4']['skilful'])
        # SPEI-12 one month ahead shares 11 observed months -> genuinely skilful.
        self.assertTrue(skill['12_1']['skilful'])

    def test_long_scale_and_long_leads_are_leak_free(self):
        from .prediction_engine import drought_grid as dg
        self.assertEqual(max(dg.LEADS), 12)
        self.assertIn(24, dg.SCALES)
        # SPEI-24 models add their own index; shorter scales keep the shared set.
        self.assertIn('spei24', dg.features_for(24))
        self.assertEqual(dg.features_for(12), dg.BASE_FEATURES)
        df = dg.add_indices(self._noise_frame())
        with mock.patch.object(dg, 'SCALES', (12, 24)), mock.patch.object(dg, 'LEADS', (6, 12)):
            skill = dg.verify(df, log=lambda s: None)
        # Whole SPEI-12 window in the future -> white noise cannot be predicted.
        self.assertLess(skill['12_12']['auc'], 0.65)
        self.assertFalse(skill['12_12']['skilful'])
        # SPEI-24 six months ahead still holds 18 observed months.
        self.assertTrue(skill['24_6']['skilful'])
        # Half of the SPEI-24 window observed at +12: partial skill, well below +6.
        self.assertLess(skill['24_12']['msss'], skill['24_6']['msss'])

    def test_scenario_ensemble_uses_only_the_past_and_has_no_false_skill(self):
        import numpy as np
        from .prediction_engine import drought_grid as dg
        df = dg.add_indices(self._noise_frame())
        with mock.patch.object(dg, 'SCALES', (3, 12)), mock.patch.object(dg, 'LEADS', tuple(range(1, 13))):
            arr = dg.scenario_arrays(df)
            t = 300
            before = dg.scenario_ensemble(arr, t)
            # Corrupt everything after the issue month: the ensemble must not move.
            arr2 = dict(arr, P=arr['P'].copy(), PET=arr['PET'].copy())
            arr2['P'][:, t + 1:] = 1e6
            arr2['PET'][:, t + 1:] = -1e6
            after = dg.scenario_ensemble(arr2, t)
            for k in (3, 12):
                np.testing.assert_array_equal(before['spei'][k], after['spei'][k])
            self.assertTrue(all(y < arr['years'][t] for y in before['member_years']))
            skill = dg.verify_scenarios(arr, log=lambda s: None)
        # Whole window in the future on white noise -> no skill.
        self.assertLess(skill['3_4']['auc'], 0.65)
        self.assertFalse(skill['3_4']['skilful'])
        # 11 of 12 months observed -> skilful, and the 80 % range is about 80 %.
        self.assertTrue(skill['12_1']['skilful'])
        self.assertAlmostEqual(skill['12_6']['coverage80'], 0.8, delta=0.1)

    def test_scenarios_become_the_published_forecast_and_ridge_is_kept(self):
        from .prediction_engine import drought_grid as dg
        ridge_skill = {'12_6': {'auc': 0.88, 'skilful': True}}
        scen_skill = {'12_6': {'auc': 0.91, 'skilful': True}}
        payload = {
            'skill': ridge_skill,
            'cells': {'A': {'forecast': {'12': {'6': {
                'spei': -2.05, 'lo': -3.0, 'hi': -1.1, 'p_drought': 0.92, 'class': 'extreme', 'drivers': ['d']}}}}},
            'basin': {'12': {'6': {'spei': -2.0, 'p_drought': 0.9, 'target_month': '2027-03-01'}}},
            'scenarios': {
                'skill': scen_skill,
                'cells': {'A': {'12': {'6': {'p10': -1.9, 'p50': -1.1, 'p90': -0.1, 'p_drought': 0.6}}}},
                'basin': {'12': {'6': {'p50': -1.09, 'p_drought': 0.6}}},
            },
        }
        out = dg.promote_scenarios(payload)
        f = out['cells']['A']['forecast']['12']['6']
        self.assertEqual((f['spei'], f['lo'], f['hi'], f['p_drought'], f['class']), (-1.1, -1.9, -0.1, 0.6, 'moderate'))
        self.assertEqual(f['ridge'], {'spei': -2.05, 'p_drought': 0.92})
        self.assertEqual(f['drivers'], ['d'])
        b = out['basin']['12']['6']
        self.assertEqual((b['spei'], b['p_drought'], b['target_month']), (-1.09, 0.6, '2027-03-01'))
        self.assertIs(out['skill'], scen_skill)
        self.assertIs(out['skill_ridge'], ridge_skill)
        self.assertEqual(out['primary'], 'scenarios')
        # No scenario block (too little history): the ridge forecast stays as published.
        plain = {'skill': ridge_skill, 'scenarios': None}
        self.assertIs(dg.promote_scenarios(plain)['skill'], ridge_skill)

    def test_api_404_without_run_and_payload_with_run(self):
        from .models import DroughtGridForecast
        user = get_user_model().objects.create_user('dg', password='pw')
        self.client.force_login(user)
        self.assertEqual(self.client.get('/api/drought-grid/').status_code, 404)
        DroughtGridForecast.objects.create(issue_month=date(2026, 9, 1), model_version='t',
                                           payload={'issue_month': '2026-09-01', 'cells': {}})
        r = self.client.get('/api/drought-grid/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('months_behind_today', r.json())


class PageConsistencyTests(TestCase):
    """The analysis gauge and the forecast cards must say what they are based on."""

    def setUp(self):
        from .models import ObservationYear, Region
        # Migrations seed some regions and years, so use names of our own.
        self.region = Region.objects.create(name='Consistency Test Basin', latitude=37.06, longitude=9.52)
        self.year = ObservationYear.objects.get_or_create(label='2026')[0]

    def _reading(self, when, spei, subregion=''):
        from .models import DroughtIndices
        return DroughtIndices.objects.create(region=self.region, year=self.year, measurement_date=when,
                                             spei_3month=spei, subregion=subregion)

    def test_gauge_prefers_the_merged_series_whatever_the_row_order(self):
        from .views.utils import assess_drought_risk
        self._reading(date(2026, 9, 30), -1.47, 'v8_st_sub_humide')
        self._reading(date(2026, 10, 31), 0.23, 'merged')
        self._reading(date(2026, 10, 31), -0.52, 'v8_st_sub_humide')
        self._reading(date(2026, 10, 31), 0.98, 'v8_st_humide_inf')
        risk = assess_drought_risk(self.region, '', '', as_of=date(2026, 11, 11))
        self.assertEqual((risk['spei'], risk['source'], risk['n_readings']), (0.23, 'merged', 3))
        self.assertEqual(risk['measured_on'], date(2026, 10, 31))
        self.assertTrue(risk['source_label'])

    def test_gauge_averages_station_rows_when_no_merged_series_exists(self):
        from .views.utils import assess_drought_risk
        self._reading(date(2026, 10, 31), -0.52, 'v8_st_sub_humide')
        self._reading(date(2026, 10, 31), 0.98, 'v8_st_humide_inf')
        risk = assess_drought_risk(self.region, '', '', as_of=date(2026, 11, 11))
        self.assertEqual((risk['spei'], risk['source']), (0.23, 'mean'))

    def test_gauge_single_reading_and_no_reading(self):
        from .views.utils import assess_drought_risk
        self.assertIsNone(assess_drought_risk(self.region, '', '')['source'])
        self._reading(date(2026, 10, 31), -1.2)
        risk = assess_drought_risk(self.region, '', '', as_of=date(2026, 11, 11))
        self.assertEqual((risk['spei'], risk['source']), (-1.2, 'single'))

    # Plain static storage: the manifest one needs a collectstatic run first.
    @override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
    def test_forecast_card_is_marked_outdated_and_shows_a_percentage(self):
        from .models import SpeiForecast
        SpeiForecast.objects.create(
            region=self.region, feature_month=date(2025, 12, 1), target_month_t1=date(2026, 1, 1),
            target_month_t3=date(2026, 3, 1), spei_t1=0.30, score_t1=20, level_t1='Low',
            prob_drought_t1=0.141, validation_metrics={'months_behind_today': 0})
        user = get_user_model().objects.create_user('pc', password='pw')
        self.client.force_login(user)
        with mock.patch('dashboard.views.prediction_views.get_region_forecast', return_value=None), \
                mock.patch('dashboard.views.prediction_views.timezone.now',
                           return_value=datetime(2026, 11, 11, tzinfo=dt_timezone.utc)):
            response = self.client.get('/analysis/spei-outlook/')
        self.assertEqual(response.status_code, 200)
        card = response.context['forecasts'][0]
        # Lag is measured against today, not the value frozen at generation time.
        self.assertEqual(card.months_behind, 10)
        self.assertTrue(card.stale)
        self.assertEqual(card.prob_pct_t1, 14)
        html = response.content.decode()
        self.assertIn('OUTDATED', html)
        self.assertIn('14%', html)
        self.assertNotIn('0.141%', html)


class RiskBreakdownTests(TestCase):
    """'What's driving risk?': the score's own SPI-3 plus anomalies to watch."""

    def setUp(self):
        import numpy as np
        import pandas as _pd
        rng = np.random.default_rng(3)
        self.region = Region.objects.create(name='Breakdown', latitude=37.0, longitude=9.5)
        year = ObservationYear.objects.create(label=2024)
        days = _pd.date_range('1994-01-01', '2024-06-30', freq='D')
        temp = 18 + 8 * np.sin(2 * np.pi * (days.dayofyear - 110) / 365)
        rows = []
        for d, t in zip(days, temp):
            hot = 3.0 if d >= _pd.Timestamp('2024-06-01') else 0.0      # a heat wave in the last 30 days
            dry = d >= _pd.Timestamp('2024-04-01')                      # and a dry spring
            rows.append(ClimateMetrics(region=self.region, year=year, measurement_date=d.date(),
                                       rainfall_mm=0.0 if dry else float(rng.gamma(0.5, 4)),
                                       temperature_mean_c=float(t + hot + rng.normal(0, 0.5))))
        ClimateMetrics.objects.bulk_create(rows, batch_size=2000)

    def test_rain_sets_the_score_and_heat_is_a_signal(self):
        from .services import risk_breakdown as rb
        from .services.assistant_brain import _score_from_spei
        b = rb.build(self.region, '2024-06-30', satellite=False)
        sig = {s['key']: s for s in b['signals']}
        self.assertTrue(sig['rain_90']['in_score'])
        self.assertFalse(any(s['in_score'] for k, s in sig.items() if k != 'rain_90'))
        self.assertLess(b['spi3'], -1)                               # no rain for 90 days
        self.assertEqual(b['risk'], _score_from_spei(b['spi3']))     # the score is exactly SPI-3's
        self.assertEqual(sig['rain_90']['pct_of_normal'], 0)
        self.assertGreater(sig['temperature']['diff'], 2.0)          # +3 C heat wave
        self.assertGreater(sig['temperature']['stress'], 1.0)        # hotter = toward drought
        self.assertGreater(sig['rain_90']['stress'], 1.0)            # no rain = toward drought

    def test_legacy_drivers_report_a_real_deficit(self):
        from .services import risk_breakdown as rb
        d = rb.legacy_drivers(rb.build(self.region, '2024-06-30', satellite=False))
        self.assertEqual(d['rainfall_deficit'], 100)                 # 0 % of normal -> 100 % deficit
        self.assertIn('breakdown', d)
        rows = rb.signal_rows(d['breakdown'])
        self.assertTrue(rows[0][2].startswith('sets the score'))

    def test_strength_words(self):
        from .services.risk_breakdown import strength
        self.assertEqual(strength(0.2), 'near normal')
        self.assertEqual(strength(1.5), 'clearly drier')
        self.assertEqual(strength(-2.5), 'strongly wetter')
