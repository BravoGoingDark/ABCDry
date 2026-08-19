import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')

app = Celery('agri_dashboard')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
