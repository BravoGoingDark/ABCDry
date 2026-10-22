import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')
django.setup()
from dashboard.models import (
    Region, RemoteSensingMetrics, ClimateMetrics, SoilMetrics,
    DroughtIndices, AgriculturalMetrics, HydrologyMetrics, DroughtPrediction,
)

for model in [Region, RemoteSensingMetrics, ClimateMetrics, SoilMetrics,
              DroughtIndices, AgriculturalMetrics, HydrologyMetrics, DroughtPrediction]:
    print(f'\n=== {model.__name__} (db_table: {model._meta.db_table}) ===')
    for f in model._meta.get_fields():
        if f.is_relation and f.auto_created:
            continue
        name = f.name
        if hasattr(f, 'db_column') and f.db_column and f.db_column != name:
            col = f'{name} (col: {f.db_column})'
        else:
            col = name
        t = getattr(f, 'get_internal_type', lambda: '')()
        extra = ''
        if f.is_relation:
            extra = f' -> {f.related_model.__name__ if f.related_model else "?"}'
        if hasattr(f, 'choices') and f.choices:
            extra += f' choices={[c[0] for c in f.choices]}'
        null = ' NULL' if getattr(f, 'null', False) else ''
        print(f'  {col}: {t}{null}{extra}')