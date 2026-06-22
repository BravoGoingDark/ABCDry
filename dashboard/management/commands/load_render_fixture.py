import os
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.apps import apps


MODELS_IN_ORDER = [
    "ObservationYear",
    "CropType",
    "IrrigationMethod",
    "Region",
    "SoilMetrics",
    "ClimateMetrics",
    "DroughtIndices",
    "AgriculturalMetrics",
    "RemoteSensingMetrics",
    "HydrologyMetrics",
    "EnvironmentalSnapshot",
    "DroughtPrediction",
    "DataImportLog",
]


class Command(BaseCommand):
    help = "Clear dashboard data and load fixture.json (for fresh Render deploys)."

    def add_arguments(self, parser):
        parser.add_argument("fixture", nargs="?", default="fixture.json")

    def handle(self, *args, **options):
        fixture = options["fixture"]
        if not os.path.exists(fixture):
            self.stdout.write(self.style.ERROR(f"Fixture {fixture} not found"))
            return

        for model_name in MODELS_IN_ORDER:
            model = apps.get_model("dashboard", model_name)
            if model.objects.exists():
                self.stdout.write(f"  Clearing {model_name} …")
                model.objects.all().delete()

        self.stdout.write(self.style.SUCCESS("Cleared all dashboard data."))
        self.stdout.write(f"Loading fixture {fixture} …")
        call_command("loaddata", fixture)
        self.stdout.write(self.style.SUCCESS("Fixture loaded successfully."))
