from dashboard.models import AgriculturalMetrics, CropType
import json
print('CropTypes:')
print(list(CropType.objects.values('id','name')))
print('\nAgricultural rows:')
rows=list(AgriculturalMetrics.objects.select_related('crop').values('id','crop_id','region_id','year_id','measurement_date'))
print(json.dumps(rows, default=str, indent=2))
for a in AgriculturalMetrics.objects.select_related('crop'):
    print('row', a.id, 'crop_id', a.crop_id, 'crop_name', a.crop.name if a.crop else None)
