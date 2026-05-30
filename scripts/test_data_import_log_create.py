from dashboard.models import DataImportLog
obj = DataImportLog.objects.create(
    source='Manual',
    filename='seq_test',
    metric_type='Soil',
    records_imported=0,
    status='Success',
    imported_by='system',
    notes='sequence test',
)
print('created_id', obj.id)
obj.delete()
print('deleted_test_row')
