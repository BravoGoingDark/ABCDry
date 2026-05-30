from dashboard.data_ingestion_utils import DataImporter
from dashboard.models import Region, ObservationYear

region = Region.objects.first()
year = ObservationYear.objects.first()
print('Using region', region.id, region.name, 'and year', year.id, year.label)

importer = DataImporter(source='test', username='tester')
data = {
    'region_id': region.id,
    'year_id': year.id,
    'measurement_date': '2026-05-28',
    # 'ndwi' intentionally omitted
    'ndvi': 0.45,
}
try:
    obj = importer.submit_form_data('remote_sensing', data)
    print('Import success, last_action:', importer.last_action)
except Exception as e:
    import traceback
    print('Import failed:', str(e))
    traceback.print_exc()
    print('Errors:', importer.errors)
