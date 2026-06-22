import os, sys
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import connection
from django.apps import apps


# Truncation order: metric/data tables first (they FK to reference tables),
# then reference tables last. Models not listed are skipped.
TRUNCATE_ORDER = [
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
    help = "Clear dashboard data and load fixture (for fresh Render deploys)."

    def add_arguments(self, parser):
        parser.add_argument("fixture", nargs="?", default="fixture.json")

    def handle(self, *args, **options):
        fixture = options["fixture"]
        fixture = os.path.abspath(fixture)
        self.stdout.write(f"Python: {sys.version}, CWD: {os.getcwd()}")
        self.stdout.write(f"Fixture: {fixture}")

        if not os.path.exists(fixture):
            self.stdout.write(self.style.WARNING(f"Fixture not found: {fixture}"))
            self.stdout.write("Falling back to setup_render_data …")
            call_command("setup_render_data")
            call_command("verify_data")
            return

        engine = connection.vendor
        self.stdout.write(f"Engine: {engine}")

        # Build a lookup of model name -> model class
        app_models = {}
        for m in apps.get_app_config("dashboard").get_models():
            app_models[m.__name__] = m

        self.stdout.write("Deleting dashboard data …")
        with connection.cursor() as cursor:
            for name in TRUNCATE_ORDER:
                m = app_models.get(name)
                if m is None:
                    continue
                table = m._meta.db_table
                cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
                count = cursor.fetchone()[0]
                if count > 0:
                    self.stdout.write(f"  {name}: {count} rows")
                    cursor.execute(f'DELETE FROM "{table}"')
        self.stdout.write("All dashboard data cleared.")

        self.stdout.write("Loading fixture …")
        call_command("loaddata", fixture)

        # Reset sequences so auto-increment picks up after fixture PKs
        if engine == "postgresql":
            try:
                self.stdout.write("Syncing sequences …")
                with connection.cursor() as cursor:
                    for name in TRUNCATE_ORDER:
                        m = app_models.get(name)
                        if m is None:
                            continue
                        table = m._meta.db_table
                        pk_col = m._meta.pk.db_column or m._meta.pk.column
                        seq = f"pg_get_serial_sequence('{table}', '{pk_col}')"
                        cursor.execute(
                            f"SELECT setval({seq}, "
                            f"GREATEST(COALESCE((SELECT MAX(\"{pk_col}\") FROM \"{table}\"), 1), 1))"
                        )
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"Sequence sync: {e}"))

        # Ensure admin user has a UserProfile (may have been cascaded away)
        from django.contrib.auth.models import User
        from dashboard.models import UserProfile
        for u in User.objects.filter(is_superuser=True):
            UserProfile.objects.get_or_create(user=u, defaults={"role": "superadmin"})
            self.stdout.write(f"  UserProfile OK for {u.username}")

        self.stdout.write(self.style.SUCCESS("Fixture loaded successfully."))
