import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')
django.setup()
from dashboard.models import (
    RemoteSensingMetrics, ClimateMetrics, SoilMetrics,
    DroughtIndices, AgriculturalMetrics, HydrologyMetrics,
)
from decimal import Decimal
from django.db.models import Q

POINTS = [
    (Decimal('37.117000'), Decimal('9.318000'), 'v8_st_humide_inf'),
    (Decimal('37.010000'), Decimal('9.731000'), 'v8_st_sub_humide'),
]

MODELS = [
    RemoteSensingMetrics, ClimateMetrics, SoilMetrics,
    DroughtIndices, AgriculturalMetrics, HydrologyMetrics,
]

total = 0
for model in MODELS:
    for lat, lon, sub in POINTS:
        # Approximate match on rounded lat/lon (exist rows may have varying scale)
        qs = model.objects.filter(
            region_id=4,
            latitude__isnull=False,
            longitude__isnull=False,
            subregion__isnull=True,
        ).filter(
            Q(latitude__gte=lat - Decimal('0.0001'), latitude__lte=lat + Decimal('0.0001')) &
            Q(longitude__gte=lon - Decimal('0.0001'), longitude__lte=lon + Decimal('0.0001'))
        )
        n = qs.update(subregion=sub)
        if n:
            print(f'{model.__name__}: {n} rows -> {sub}')
        total += n

print(f'\nTotal backfilled: {total}')