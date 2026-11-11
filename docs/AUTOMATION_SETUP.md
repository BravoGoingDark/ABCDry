# Automated Data Gathering Setup Guide

## Overview

Your agricultural dashboard now has automated data collection configured with Celery Beat. This guide explains how to activate it.

---

## What Gets Automated

| Task | Frequency | Time (UTC) | Purpose |
|------|-----------|-----------|---------|
| 🔄 Refresh Views | Daily | 2:00 AM | Refresh PostgreSQL materialized views |
| 🛰️ Pull Satellite | Daily | 3:00 AM | Fetch Sentinel-2, Sentinel-3, MODIS, SMAP data |
| 🤖 Retrain Models | Daily | 3:00 AM | Update ML models with latest satellite data |
| ⚠️ Risk Assessment | Daily | 4:00 AM | Generate daily drought risk predictions |
| 📊 SPI Validation | Weekly | 5:00 AM (Sun) | Validate SPI forecast accuracy |

---

## Quick Start (Windows)

### Option 1: Automatic Setup (Recommended)

```bash
startup_automation.bat
```

This will install dependencies and guide you through starting the services.

### Option 2: Manual Setup

**Step 1: Install dependencies**
```bash
pip install celery[redis] redis django-celery-beat
```

**Step 2: Run migrations**
```bash
python manage.py migrate
```

**Step 3: Start Celery Worker** (Terminal 1)
```bash
celery -A agri_dashboard worker -l info
```

**Step 4: Start Celery Beat** (Terminal 2)
```bash
celery -A agri_dashboard beat -l info
```

Both terminals should stay running. Your data will be gathered automatically at the scheduled times.

---

## Quick Start (Linux/Mac)

```bash
bash startup_automation.sh
```

Or manually:

**Terminal 1: Celery Worker**
```bash
celery -A agri_dashboard worker -l info
```

**Terminal 2: Celery Beat Scheduler**
```bash
celery -A agri_dashboard beat -l info
```

---

## Configuration

### Default Broker (In-Memory, Development Only)

By default, the system uses an in-memory message broker suitable for development:

```python
CELERY_BROKER_URL = 'memory://'  # Default for testing
CELERY_RESULT_BACKEND = 'cache+locmem://'
```

**Limitation**: Tasks are lost if workers restart. Not suitable for production.

### Production: Redis Broker (Recommended)

For reliable production automation, set up Redis:

**1. Install Redis**

Linux/Mac:
```bash
brew install redis  # Mac
sudo apt-get install redis-server  # Ubuntu
```

Windows: Download from https://github.com/microsoftarchive/redis/releases

**2. Set environment variable in `.env`**

```bash
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
```

**3. Start Redis server**

```bash
redis-server
```

**4. Start Celery services**

```bash
# Terminal 1
celery -A agri_dashboard worker -l info

# Terminal 2
celery -A agri_dashboard beat -l info
```

### Production: RabbitMQ Broker

For enterprise deployments:

**1. Install RabbitMQ** (https://www.rabbitmq.com/download.html)

**2. Set environment variable**

```bash
CELERY_BROKER_URL=amqp://guest:guest@localhost:5672//
```

---

## Monitoring & Debugging

### Check Scheduled Tasks

```bash
python manage.py shell
```

```python
from django_celery_beat.models import PeriodicTask
for task in PeriodicTask.objects.all():
    print(f"{task.name}: {task.task}")
```

### View Task Execution History

```bash
python manage.py shell
```

```python
from django_celery_beat.models import PeriodicTaskStatistic
for stat in PeriodicTaskStatistic.objects.all():
    print(f"{stat.periodic_task.name}: {stat.run_count} runs")
```

### Monitor Celery Flower (Web Dashboard)

Install Flower for visual monitoring:

```bash
pip install flower
flower -A agri_dashboard
```

Then visit: http://localhost:5555

---

## Troubleshooting

### "No tasks to run" error

This is normal! It means there's no data due for the scheduled time. Tasks will execute at their scheduled times.

### Tasks not executing

**Check 1: Is Celery Beat running?**
```bash
ps aux | grep celery  # Linux/Mac
tasklist | findstr celery  # Windows
```

**Check 2: Are worker and beat on the same machine?**
Both services should be running. If Beat schedules a task, Worker must be available to execute it.

**Check 3: Check logs**
```bash
tail -f logs/celery_worker.log
tail -f logs/celery_beat.log
```

### "broker connection refused"

Your Redis/RabbitMQ server isn't running. Start it:

```bash
redis-server  # For Redis
rabbitmq-server  # For RabbitMQ
```

### GEE authentication error during satellite pull

Ensure Google Earth Engine credentials are set:

```bash
export GEE_CREDENTIALS_FILE=./keys/gee-service-account.json
# OR add to .env
```

Then authenticate:

```bash
earthengine authenticate
```

---

## Automation Timeline (Daily)

```
2:00 AM UTC ┌─ Refresh PostgreSQL materialized views
            │  └─ Ensures metrics summary tables are up-to-date
            │
3:00 AM UTC ├─ Pull Satellite Data (Sentinel-2, Sentinel-3, MODIS, SMAP)
            │  └─ Fetches latest remote sensing metrics from Google Earth Engine
            │
            ├─ Retrain ML Models (LSTM, XGBoost)
            │  └─ Updates predictions with new satellite data
            │
4:00 AM UTC ├─ Generate Daily Risk Assessments
            │  └─ Runs drought prediction pipeline for each region
            │
5:00 AM UTC └─ (Sundays only) Validate SPI Forecasts
               └─ Checks 7-day and 30-day drought predictions
```

---

## Disabling Automation

To temporarily disable tasks:

```bash
python manage.py shell
```

```python
from django_celery_beat.models import PeriodicTask

# Disable a specific task
task = PeriodicTask.objects.get(name='pull-satellite-daily')
task.enabled = False
task.save()

# Disable all tasks
PeriodicTask.objects.all().update(enabled=False)
```

---

## Next Steps

1. ✅ Run `startup_automation.bat` or `startup_automation.sh`
2. ✅ Verify tasks appear in Celery logs
3. ✅ (Optional) Install Flower for monitoring: `pip install flower && flower -A agri_dashboard`
4. ✅ Monitor data collection at `/metrics/` in your dashboard

---

## Support

For issues or questions:
- Check `logs/celery_worker.log` for worker errors
- Check `logs/celery_beat.log` for scheduler errors
- Review Celery documentation: https://docs.celeryproject.io/

---

**Your data gathering is now automated! 🎉**
