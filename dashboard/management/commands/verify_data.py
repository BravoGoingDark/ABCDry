from django.core.management.base import BaseCommand
from dashboard.models import (
    Region, ObservationYear, CropType, IrrigationMethod,
    SoilMetrics, ClimateMetrics, DroughtIndices, AgriculturalMetrics,
    RemoteSensingMetrics, HydrologyMetrics, EnvironmentalSnapshot,
)


class Command(BaseCommand):
    help = "Verify fixture data was loaded correctly."

    def handle(self, *args, **options):
        counts = {}
        for model in [
            Region, ObservationYear, CropType, IrrigationMethod,
            SoilMetrics, ClimateMetrics, DroughtIndices, AgriculturalMetrics,
            RemoteSensingMetrics, HydrologyMetrics, EnvironmentalSnapshot,
        ]:
            counts[model.__name__] = model.objects.count()
        total = sum(counts.values())
        for name, count in counts.items():
            label = "OK" if count > 0 else "EMPTY"
            self.stdout.write(f"  {label:6}  {name}: {count}")
        self.stdout.write(f"  {'OK' if total > 0 else 'EMPTY':6}  Total: {total}")
        if total == 0:
            raise SystemExit(1)
