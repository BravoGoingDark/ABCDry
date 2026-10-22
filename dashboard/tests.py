from datetime import date, timedelta
import json

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
		request = RequestFactory().get('/metrics/export/climate/')
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
		self.assertIn('REFERENCE 1 (source: docs/SPEI_NOTES.md', block)

	def test_prompt_block_is_empty_without_context(self):
		self.assertEqual(retrieval.prompt_block({'documents': [], 'data': []}), '')

	def test_embed_texts_returns_none_when_ollama_is_unreachable(self):
		with override_settings(RAG_OLLAMA_URL='http://127.0.0.1:1', RAG_EMBED_TIMEOUT=1):
			self.assertIsNone(retrieval.embed_texts(['some text']))

	def test_gather_degrades_to_a_usable_shape_when_index_is_absent(self):
		import tempfile

		with tempfile.TemporaryDirectory() as docs, tempfile.TemporaryDirectory() as index_dir:
			retrieval.reset_index_cache()
			with override_settings(RAG_DOCS_DIR=docs, RAG_INDEX_DIR=index_dir):
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
