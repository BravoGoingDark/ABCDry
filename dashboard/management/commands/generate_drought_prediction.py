from django.core.management.base import BaseCommand, CommandError

from dashboard.models import ObservationYear, Region
from dashboard.prediction_engine.pipeline import DroughtPredictionPipeline


class Command(BaseCommand):
    help = 'Generate and store a drought prediction for a region/year.'

    def add_arguments(self, parser):
        parser.add_argument('--region-id', type=int, help='Region primary key')
        parser.add_argument('--year-id', type=int, help='Observation year primary key')
        parser.add_argument('--use-llm', action='store_true', help='Use Ollama explanation if available')
        parser.add_argument('--refresh', action='store_true', help='Force regeneration even if a cached prediction exists')
        parser.add_argument('--lookback-days', type=int, default=120, help='Number of days to use from the source metrics')

    def handle(self, *args, **options):
        region = None
        year = None

        if options['region_id']:
            region = Region.objects.filter(pk=options['region_id']).first()
        else:
            region = Region.objects.order_by('name').first()

        if options['year_id']:
            year = ObservationYear.objects.filter(pk=options['year_id']).first()
        else:
            year = ObservationYear.objects.order_by('-label').first()

        if region is None or year is None:
            raise CommandError('A valid region and year are required.')

        pipeline = DroughtPredictionPipeline()
        try:
            result = pipeline.predict_for_region(region, year, use_llm=options['use_llm'], lookback_days=options['lookback_days'])
        except Exception as exc:
            raise CommandError(str(exc))

        saved = pipeline.save_prediction(region, year, result, source_window_days=options['lookback_days'])
        self.stdout.write(self.style.SUCCESS(f'Generated prediction #{saved.id} for {region.name} / {year.label}'))