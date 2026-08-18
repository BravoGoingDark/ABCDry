import os

from django.core.management.base import BaseCommand, CommandError

from dashboard.models import ObservationYear, Region
from dashboard.prediction_engine.pipeline import DroughtPredictionPipeline

MODEL_VERSION = 'v2-spi3-walkforward'


class Command(BaseCommand):
    help = ('Retrain XGBoost (nowcast + 7d/30d SPI-3 forecasts) + LSTM on full region history '
            'with walk-forward validation (train <=2022, validate 2023+), then generate + store '
            'predictions.')

    def add_arguments(self, parser):
        parser.add_argument('--region-id', type=int, default=None,
                            help='Region pk (default: all regions)')
        parser.add_argument('--epochs', type=int, default=50)
        parser.add_argument('--lookback-days', type=int, default=None,
                            help='Limit history (default: entire history)')
        parser.add_argument('--no-predict', action='store_true',
                            help='Train only, do not generate a stored prediction')
        parser.add_argument('--skip-lstm', action='store_true',
                            help='Skip LSTM training (torch not available)')

    def _torch_available(self):
        try:
            import torch  # noqa
            return True
        except Exception:
            return False

    def handle(self, *args, **options):
        regions = Region.objects.all()
        if options['region_id']:
            regions = regions.filter(pk=options['region_id'])

        year = ObservationYear.objects.order_by('-label').first()
        if year is None:
            raise CommandError('No observation years found.')

        for region in regions:
            self.stdout.write(f'\n== Retraining {region.name} ==')
            pipeline = DroughtPredictionPipeline()
            pipeline.set_soil_properties_from_metrics(region, year)

            history = pipeline.build_history_frame(region, lookback_days=options['lookback_days'])
            if len(history) < 120:
                self.stdout.write(self.style.WARNING(
                    f'  Only {len(history)} rows of history — skipping {region.name}.'))
                continue
            self.stdout.write(f'  History frame: {len(history)} rows, {len(history.columns)} cols')

            skip_lstm = options['skip_lstm'] or not self._torch_available()
            if skip_lstm:
                self.stdout.write(self.style.WARNING('  Skipping LSTM training (torch not available).'))
            pipeline.train(history, epochs=options['epochs'], skip_lstm=skip_lstm)

            metrics = pipeline.validation_metrics or {}
            for label, m in metrics.items():
                if m:
                    self.stdout.write(self.style.SUCCESS(
                        f"  [{label}] Validation {m.get('split', '')}: "
                        f"MAE={m.get('mae')} RMSE={m.get('rmse')} R2={m.get('r2')} "
                        f"(best threshold {m.get('prediction_threshold', 65)}: "
                        f"drought P={m.get('drought_precision')} R={m.get('drought_recall')} "
                        f"F1={m.get('drought_f1')}, caught {m.get('drought_days_caught')}/"
                        f"{m.get('drought_days_total')})"))
                else:
                    self.stdout.write(self.style.WARNING(f'  [{label}] No validation metrics produced.'))

            if options['no_predict']:
                continue

            result = pipeline.predict_for_region(region, year, use_llm=False)
            saved = pipeline.save_prediction(
                region,
                year,
                result,
                source_window_days=120,
                model_version=MODEL_VERSION,
                model_trained_at=pipeline.model_trained_at,
                validation_metrics=pipeline.validation_metrics,
            )
            self.stdout.write(self.style.SUCCESS(
                f'  Saved prediction #{saved.id}: risk_today={saved.current_risk_score} '
                f'7d={saved.risk_7day} 30d={saved.risk_30day}'))

        model_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        for fname in ['xgboost_risk_model.pkl', 'xgboost_scaler.pkl', 'xgboost_features.pkl',
                      'xgboost_risk_model_7d.pkl', 'xgboost_scaler_7d.pkl', 'xgboost_features_7d.pkl',
                      'xgboost_risk_model_30d.pkl', 'xgboost_scaler_30d.pkl', 'xgboost_features_30d.pkl',
                      'lstm_7day_best.pth', 'lstm_7day_stats.npz',
                      'lstm_30day_best.pth', 'lstm_30day_stats.npz']:
            path = os.path.join(model_dir, fname)
            if os.path.exists(path):
                self.stdout.write(f'  {fname} ({os.path.getsize(path) / 1024:.1f} KB)')
