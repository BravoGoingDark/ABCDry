import os
import warnings

from django.db import models
from django.core.management.base import BaseCommand, CommandError

from dashboard.models import ObservationYear, Region, SoilMetrics
from dashboard.prediction_engine.pipeline import DroughtPredictionPipeline


class Command(BaseCommand):
    help = 'Train XGBoost + LSTM models using existing metric data for a region/year.'

    def add_arguments(self, parser):
        parser.add_argument('--region-id', type=int, default=4)
        parser.add_argument('--year-id', type=int, default=6)
        parser.add_argument('--lookback-days', type=int, default=365)
        parser.add_argument('--epochs', type=int, default=50)
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--skip-lstm', action='store_true', help='Skip LSTM training (torch not available)')

    def _torch_available(self):
        try:
            import torch  # noqa
            return True
        except Exception:
            return False

    def handle(self, *args, **options):
        region = Region.objects.filter(pk=options['region_id']).first()
        year = ObservationYear.objects.filter(pk=options['year_id']).first()
        if not region or not year:
            raise CommandError('Region and year are required.')

        pipeline = DroughtPredictionPipeline()

        soil_qs = SoilMetrics.objects.filter(region=region, year=year).order_by('-measurement_date')
        latest = soil_qs.first()
        if not latest:
            raise CommandError('No soil metrics found — run populate_synthetic_data first.')

        avg = soil_qs.aggregate(
            sand=models.Avg('sand_ratio'),
            clay=models.Avg('clay_ratio'),
            silt=models.Avg('silt_ratio'),
            om=models.Avg('organic_matter_percent'),
            root=models.Avg('root_zone_depth_mm'),
        )
        sand = float(avg['sand'] or 40)
        clay = float(avg['clay'] or 25)
        silt = float(avg['silt'] or 35)
        om = float(avg['om'] or 2.5)
        root = int(avg['root'] or 600)
        self.stdout.write(f'Avg soil: sand={sand:.1f}% clay={clay:.1f}% silt={silt:.1f}% om={om:.2f}% root={root}mm')

        raw_df = pipeline.build_prediction_frame(region, year, lookback_days=options['lookback_days'])
        self.stdout.write(f'Training frame: {len(raw_df)} rows, {len(raw_df.columns)} cols')

        if options['dry_run']:
            return

        self.stdout.write('Training XGBoost …')
        pipeline.set_soil_properties(sand, clay, silt, om, root)
        prepared_df = pipeline.prepare_daily_data(raw_df)

        from dashboard.prediction_engine.xgboost_risk_predictor import XGBoostDroughtRiskPredictor
        pipeline.xgb_predictor = XGBoostDroughtRiskPredictor()
        pipeline.xgb_predictor.train(prepared_df, pipeline.available_water_capacity_mm, pipeline.field_capacity_pct)
        self.stdout.write(self.style.SUCCESS('XGBoost model saved.'))

        skip_lstm = options['skip_lstm'] or not self._torch_available()
        if skip_lstm:
            self.stdout.write(self.style.WARNING('Skipping LSTM training (torch not available). Pipeline will use heuristic fallback for forecasts.'))
            pipeline.is_trained = True
        else:
            self.stdout.write('Training LSTM-7d …')
            from dashboard.prediction_engine.lstm_forecaster import LSTMDroughtForecaster
            pipeline.lstm_7d = LSTMDroughtForecaster(sequence_length=30, n_features=10)
            pipeline.lstm_7d.train(prepared_df, forecast_days=7, epochs=options['epochs'])
            self.stdout.write(self.style.SUCCESS('LSTM-7d trained.'))

            self.stdout.write('Training LSTM-30d …')
            pipeline.lstm_30d = LSTMDroughtForecaster(sequence_length=60, n_features=10)
            pipeline.lstm_30d.train(prepared_df, forecast_days=30, epochs=options['epochs'])
            self.stdout.write(self.style.SUCCESS('LSTM-30d trained.'))
            pipeline.is_trained = True

        model_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        for fname in ['xgboost_risk_model.pkl', 'xgboost_scaler.pkl', 'xgboost_features.pkl',
                       'lstm_7day_best.pth', 'lstm_7day_stats.npz',
                       'lstm_30day_best.pth', 'lstm_30day_stats.npz']:
            path = os.path.join(model_dir, fname)
            if os.path.exists(path):
                self.stdout.write(f'  {fname} ({os.path.getsize(path) / 1024:.1f} KB)')
