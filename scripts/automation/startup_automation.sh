#!/usr/bin/env bash
# startup_automation.sh - Start Celery and Celery Beat for automated data gathering

echo "========================================="
echo "Agricultural Metrics - Automation Setup"
echo "========================================="

# Check if virtual environment is activated
if [ -z "$VIRTUAL_ENV" ]; then
    echo "ERROR: Virtual environment not activated!"
    echo "Run: python -m venv venv && source venv/bin/activate (Linux/Mac)"
    echo "Run: python -m venv venv && venv\Scripts\activate (Windows)"
    exit 1
fi

echo "✅ Virtual environment activated"

# Install required packages
echo ""
echo "Installing Celery and dependencies..."
pip install celery[redis] -q
pip install redis -q
pip install django-celery-beat -q
echo "✅ Dependencies installed"

# Start Redis (if using Redis broker)
echo ""
echo "Starting Redis in background..."
redis-server --daemonize yes 2>/dev/null || echo "⚠️  Redis server not available. Using memory broker (local testing only)."

# Run Django migrations for Celery Beat
echo ""
echo "Running Django migrations..."
python manage.py migrate

# Start Celery worker in background
echo ""
echo "Starting Celery worker..."
celery -A agri_dashboard worker -l info --logfile=logs/celery_worker.log --detach

# Start Celery Beat scheduler
echo ""
echo "Starting Celery Beat scheduler..."
celery -A agri_dashboard beat -l info --logfile=logs/celery_beat.log --detach

echo ""
echo "========================================="
echo "✅ AUTOMATION STARTED"
echo "========================================="
echo ""
echo "Scheduled Tasks:"
echo "  • 2:00 AM UTC - Refresh materialized views"
echo "  • 3:00 AM UTC - Pull satellite data & retrain models"
echo "  • 4:00 AM UTC - Generate daily risk assessments"
echo "  • 5:00 AM UTC (Sundays) - Validate SPI forecasts"
echo ""
echo "Logs:"
echo "  • Worker: logs/celery_worker.log"
echo "  • Scheduler: logs/celery_beat.log"
echo ""
echo "To stop automation:"
echo "  celery -A agri_dashboard control shutdown"
echo ""
