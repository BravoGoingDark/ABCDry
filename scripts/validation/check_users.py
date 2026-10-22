import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')
django.setup()
from django.contrib.auth.models import User

for u in User.objects.filter(is_staff=True):
    try:
        role = u.profile.role
        region = u.profile.region
    except Exception as e:
        role = 'ERR'
        region = None
    print(f'{u.username}: role={role}, region={region}')