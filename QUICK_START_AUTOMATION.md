# Automated Data Gathering - QUICK START

## ⚡ Start Automation (Right Now)

### Windows
```bash
# Terminal 1: Worker
celery -A agri_dashboard worker -l info

# Terminal 2: Scheduler (in another terminal)
celery -A agri_dashboard beat -l info
```

### Linux/Mac
```bash
# Terminal 1: Worker
celery -A agri_dashboard worker -l info --logfile=logs/celery_worker.log --detach

# Terminal 2: Scheduler
celery -A agri_dashboard beat -l info --logfile=logs/celery_beat.log --detach
```

---

## 📅 What Gets Automated

| Time (UTC) | Task | Data |
|-----------|------|------|
| **2:00 AM** | Refresh DB views | PostgreSQL materialized views |
| **3:00 AM** | **Pull Satellites** | Sentinel-2, Sentinel-3, MODIS, SMAP |
| **3:00 AM** | Retrain Models | LSTM, XGBoost predictions |
| **4:00 AM** | Generate Risk Assessments | Drought predictions per region |
| **5:00 AM (Sundays)** | Validate Forecasts | SPI accuracy check |

---

## ✅ Verification

```bash
python verify_automation.py
```

Expected output:
```
✅ Celery app configured
✅ 4 scheduled tasks ready
✅ All packages installed
✅ Database ready
```

---

## 🔍 Monitor (Optional - Flower Dashboard)

```bash
pip install flower
flower -A agri_dashboard
```

Visit: http://localhost:5555

---

## 🛑 Stop Automation

```bash
# Windows
taskkill /F /IM python.exe  # Stops all Python processes

# Linux/Mac
pkill -f celery
```

---

## 📊 Check Task Execution

```bash
python manage.py shell
```

```python
from django_celery_beat.models import PeriodicTask
for task in PeriodicTask.objects.all():
    print(f"{task.name}: {task.task} ({task.schedule})")
```

---

## 🚀 Production Setup (with Redis)

1. **Install & start Redis**
   ```bash
   # Mac
   brew install redis && redis-server
   
   # Ubuntu
   sudo apt-get install redis-server && redis-server
   ```

2. **Set environment variable (.env)**
   ```
   CELERY_BROKER_URL=redis://localhost:6379/0
   CELERY_RESULT_BACKEND=redis://localhost:6379/1
   ```

3. **Restart Celery services**
   ```bash
   celery -A agri_dashboard worker -l info
   celery -A agri_dashboard beat -l info
   ```

---

## 📝 Logs

Worker logs: `logs/celery_worker.log`  
Scheduler logs: `logs/celery_beat.log`  
Django logs: `logs/django.log`

View live:
```bash
tail -f logs/celery_worker.log
tail -f logs/celery_beat.log
```

---

## 🎯 Status

✅ **Configured**: Celery Beat scheduler ready  
✅ **Tasks**: 4 automated data gathering tasks  
✅ **Database**: Migrations applied  
⏳ **Ready to run**: Start workers above

**Your data will be automatically gathered every day!** 🎉
