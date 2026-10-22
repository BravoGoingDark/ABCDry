import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')
django.setup()
from dashboard.models import ClimateMetrics, RemoteSensingMetrics

print('ClimateMetrics total:', ClimateMetrics.objects.count())
print('ClimateMetrics region 4:', ClimateMetrics.objects.filter(region_id=4).count())

print('RemoteSensingMetrics total:', RemoteSensingMetrics.objects.count())
print('RemoteSensingMetrics region 4:', RemoteSensingMetrics.objects.filter(region_id=4).count())

# Check all regions
from django.db.models import Count
print('\nClimateMetrics by region:')
for r in ClimateMetrics.objects.values('region_id').annotate(c=Count('id')):
    print(f'  region {r["region_id"]}: {r["c"]}')
print('\nRemoteSensingMetrics by region:')
for r in RemoteSensingMetrics.objects.values('region_id').annotate(c=Count('id')):
    print(f'  region {r["region_id"]}: {r["c"]}')
