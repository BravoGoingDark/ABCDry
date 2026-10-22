from django.core.management.base import BaseCommand
from django.db import connection
from dashboard.models import (
    Region, ObservationYear, CropType, IrrigationMethod,
    SoilMetrics, ClimateMetrics, DroughtIndices, AgriculturalMetrics,
    RemoteSensingMetrics, HydrologyMetrics, EnvironmentalSnapshot,
    RiskAssessment, DroughtPrediction, Sensor, DataImportLog
)


class Command(BaseCommand):
    help = "Inspect database table counts, schemas, and legacy data."

    def add_arguments(self, parser):
        parser.add_argument(
            '--counts',
            action='store_true',
            help='Display row counts for all dashboard tables',
        )
        parser.add_argument(
            '--tables',
            action='store_true',
            help='List all tables present in the database',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("=== APWRS Database Inspection Tool ==="))

        if options['tables'] or not options['counts']:
            self.stdout.write("\n-- Database Tables --")
            with connection.cursor() as cursor:
                tables = connection.introspection.table_names(cursor)
                for table in sorted(tables):
                    self.stdout.write(f"  • {table}")

        models = [
            ("Regions", Region),
            ("Observation Years", ObservationYear),
            ("Crop Types", CropType),
            ("Irrigation Methods", IrrigationMethod),
            ("Soil Metrics", SoilMetrics),
            ("Climate Metrics", ClimateMetrics),
            ("Drought Indices", DroughtIndices),
            ("Agricultural Metrics", AgriculturalMetrics),
            ("Remote Sensing Metrics", RemoteSensingMetrics),
            ("Hydrology Metrics", HydrologyMetrics),
            ("Environmental Snapshots", EnvironmentalSnapshot),
            ("Risk Assessments", RiskAssessment),
            ("Drought Predictions", DroughtPrediction),
            ("Sensors", Sensor),
            ("Data Import Logs", DataImportLog),
        ]

        self.stdout.write("\n-- Model Record Counts --")
        for label, model in models:
            count = model.objects.count()
            self.stdout.write(f"  {label:<25}: {count:,}")

        self.stdout.write(self.style.SUCCESS("\nInspection complete."))
