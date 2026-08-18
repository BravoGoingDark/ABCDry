from django.core.management.base import BaseCommand, CommandError

from dashboard.models import Region
from dashboard.prediction_engine.pipeline import DroughtPredictionPipeline


class Command(BaseCommand):
    help = ('Backtest the GFS-forecast-augmented SPI-3 method over the 2023+ validation period. '
            'Reports climatology (no forecast), forecast7+climatology (realistic), and perfect '
            '(ceiling) rainfall scenarios.')

    def add_arguments(self, parser):
        parser.add_argument('--region-id', type=int, default=4, help='Region pk (default: 4 = Ichkeul)')
        parser.add_argument('--horizon', type=int, default=30, help='Forecast horizon in days (default 30)')
        parser.add_argument('--step', type=int, default=3, help='Sample every Nth day (default 3)')

    def handle(self, *args, **options):
        region = Region.objects.filter(pk=options['region_id']).first()
        if region is None:
            raise CommandError('Region not found.')

        pipeline = DroughtPredictionPipeline()
        result = pipeline.validate_spi_forecast(region, horizon_days=options['horizon'], step=options['step'])
        if result is None:
            self.stdout.write(self.style.WARNING(f'Not enough history to validate {region.name}.'))
            return

        self.stdout.write(f"== SPI-3 forecast backtest — {region.name} (+{result['horizon_days']}d) ==")
        for mode, m in (result.get('scenarios') or {}).items():
            if m is None:
                self.stdout.write(f'  {mode}: insufficient samples')
                continue
            self.stdout.write(self.style.SUCCESS(
                f"  {mode:<18} MAE={m['mae']:>6} RMSE={m['rmse']:>6} R2={m['r2']:>7} "
                f"drought recall {m['drought_days_caught']}/{m['drought_days_total']} "
                f"({m['drought_recall']:.0%})  n={m['n_samples']}"))
