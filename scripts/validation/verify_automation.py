#!/usr/bin/env python
"""
Verify Celery and Celery Beat configuration
"""
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')
django.setup()

from django.conf import settings
from celery import current_app as celery_app

print("\n" + "="*80)
print("CELERY CONFIGURATION VERIFICATION")
print("="*80 + "\n")

# Check Celery app
print("1. CELERY APP")
print(f"   Broker: {celery_app.conf.broker_url}")
print(f"   Result Backend: {celery_app.conf.result_backend}")
print(f"   Timezone: {celery_app.conf.timezone}")
print(f"   Task Serializer: {celery_app.conf.task_serializer}")

# Check available tasks
print("\n2. REGISTERED TASKS")
tasks = celery_app.tasks
for name in sorted(tasks.keys()):
    if 'dashboard' in name:
        print(f"   ✅ {name}")

# Check Beat schedule
print("\n3. CELERY BEAT SCHEDULE")
beat_schedule = getattr(settings, 'CELERY_BEAT_SCHEDULE', {})
if beat_schedule:
    for task_name, task_config in beat_schedule.items():
        print(f"\n   Task: {task_name}")
        print(f"   ├─ Function: {task_config['task']}")
        print(f"   ├─ Schedule: {task_config['schedule']}")
        print(f"   └─ Status: {'✅ Enabled' if task_config.get('enabled', True) else '❌ Disabled'}")
else:
    print("   ⚠️  No Celery Beat schedule configured")

# Check dependencies
print("\n4. REQUIRED PACKAGES")
packages = {
    'celery': 'Celery task queue',
    'redis': 'Redis broker (optional)',
    'django_celery_beat': 'Celery Beat scheduler',
}

for pkg, description in packages.items():
    try:
        __import__(pkg)
        print(f"   ✅ {pkg:20} - {description}")
    except ImportError:
        print(f"   ❌ {pkg:20} - {description} [NOT INSTALLED]")

# Check Django DB for Celery Beat
print("\n5. CELERY BEAT DATABASE")
try:
    from django_celery_beat.models import PeriodicTask
    count = PeriodicTask.objects.count()
    print(f"   ✅ Django Celery Beat tables ready")
    print(f"   └─ Periodic tasks in database: {count}")
except Exception as e:
    print(f"   ⚠️  {e}")
    print(f"   Run: python manage.py migrate")

# Configuration summary
print("\n" + "="*80)
print("CONFIGURATION SUMMARY")
print("="*80 + "\n")

broker = celery_app.conf.broker_url
if 'memory://' in broker or 'locmem' in broker:
    print("⚠️  DEVELOPMENT MODE (Memory Broker)")
    print("   └─ Tasks will be lost on restart")
    print("   └─ For production, set CELERY_BROKER_URL to Redis/RabbitMQ")
elif 'redis' in broker:
    print("✅ PRODUCTION MODE (Redis Broker)")
    print("   └─ Tasks are persistent")
elif 'amqp' in broker:
    print("✅ PRODUCTION MODE (RabbitMQ Broker)")
    print("   └─ Tasks are persistent")
else:
    print(f"ℹ️  Custom broker: {broker}")

print("\n" + "="*80)
print("NEXT STEPS")
print("="*80 + "\n")
print("1. Start Celery Worker:")
print("   celery -A agri_dashboard worker -l info")
print("\n2. Start Celery Beat (in another terminal):")
print("   celery -A agri_dashboard beat -l info")
print("\n3. Monitor with Flower (optional):")
print("   pip install flower")
print("   flower -A agri_dashboard")
print("\n" + "="*80 + "\n")
