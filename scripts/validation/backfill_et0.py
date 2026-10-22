import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')
django.setup()

from dashboard.models import ClimateMetrics
from dashboard.prediction_engine.physical_helpers import calculate_et0

updated = 0
skipped = 0

for obj in ClimateMetrics.objects.filter(
    region_id=4,
    evapotranspiration_et0_mmday__isnull=True,
):
    if (obj.temperature_mean_c is not None and
        obj.relative_humidity_percent is not None and
        obj.wind_speed_ms is not None and
        obj.solar_radiation_mjm2day is not None):
        try:
            t_c = float(obj.temperature_mean_c)
            rh = float(obj.relative_humidity_percent)
            wind = float(obj.wind_speed_ms)
            solar_mj = float(obj.solar_radiation_mjm2day)
            solar_wm2 = solar_mj / 0.0864 if solar_mj > 0 else 0
            et0 = round(calculate_et0(t_c, wind, solar_wm2, rh), 2)
            obj.evapotranspiration_et0_mmday = et0
            obj.save(update_fields=['evapotranspiration_et0_mmday'])
            updated += 1
        except Exception as e:
            skipped += 1
    else:
        skipped += 1

print(f'ET0 backfill: updated={updated}, skipped={skipped}')
