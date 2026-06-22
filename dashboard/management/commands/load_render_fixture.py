import importlib
import os
import sys
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.apps import apps
from django.db import connection


# Delete in reverse-dependency order (metrics first, then reference tables)
MODELS_DELETE_ORDER = [
    "EnvironmentalSnapshot",
    "AgriculturalMetrics",
    "RemoteSensingMetrics",
    "HydrologyMetrics",
    "DroughtIndices",
    "ClimateMetrics",
    "SoilMetrics",
    "DroughtPrediction",
    "DataImportLog",
    "RiskAssessment",
    "Region",
    "ObservationYear",
    "CropType",
    "IrrigationMethod",
]


class Command(BaseCommand):
    help = "Clear dashboard data and load fixture.json (for fresh Render deploys)."

    def add_arguments(self, parser):
        parser.add_argument("fixture", nargs="?", default="fixture.json")

    def handle(self, *args, **options):
        fixture = options["fixture"]
        self.stdout.write(f"Python: {sys.version}")
        self.stdout.write(f"CWD: {os.getcwd()}")
        self.stdout.write(f"Fixture exists: {os.path.exists(fixture)}")
        if not os.path.exists(fixture):
            self.stdout.write(self.style.ERROR(f"Fixture {fixture} not found"))
            return

        for model_name in MODELS_DELETE_ORDER:
            model = apps.get_model("dashboard", model_name)
            if model is None:
                self.stdout.write(self.style.WARNING(f"  Model {model_name} not found, skipping"))
                continue
            if model.objects.exists():
                self.stdout.write(f"  Clearing {model_name} …")
                n, info = model.objects.all().delete()
                self.stdout.write(f"    Deleted {n} objects")

        self.stdout.write(self.style.SUCCESS("Cleared all dashboard data."))
        self.stdout.write(f"Loading fixture {fixture} …")
        call_command("loaddata", fixture)

        # Reset sequences on PostgreSQL
        engine = connection.vendor
        self.stdout.write(f"Database engine: {engine}")
        if engine == "postgresql":
            self.stdout.write("Resetting PostgreSQL sequences …")
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'public' AND tablename LIKE 'dashboard_%'"
                )
                tables = [row[0] for row in cursor.fetchall()]
                for table in tables:
                    seq = f"pg_get_serial_sequence('{table}', 'id')"
                    cursor.execute(
                        f"SELECT setval({seq}, "
                        f"GREATEST(COALESCE((SELECT MAX(id) FROM \"{table}\"), 1), 1))"
                    )
            self.stdout.write(f"  Reset sequences for {len(tables)} tables")

        self.stdout.write(self.style.SUCCESS("Fixture loaded successfully."))
