@echo off
REM startup_automation.bat - Start Celery and Celery Beat for automated data gathering (Windows)

echo =========================================
echo Agricultural Metrics - Automation Setup
echo =========================================

REM Check Python installation
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found!
    pause
    exit /b 1
)

echo.
echo Installing Celery and dependencies...
pip install celery[redis] -q
pip install redis -q
pip install django-celery-beat -q
echo ^✓ Dependencies installed

echo.
echo Running Django migrations...
python manage.py migrate

echo.
echo =========================================
echo Next Steps (run in separate terminals):
echo =========================================
echo.
echo 1. Start Celery Worker:
echo    celery -A agri_dashboard worker -l info
echo.
echo 2. Start Celery Beat (in another terminal):
echo    celery -A agri_dashboard beat -l info
echo.
echo OR use RabbitMQ/Redis for production:
echo    Set CELERY_BROKER_URL in .env or environment
echo    Example: CELERY_BROKER_URL=redis://localhost:6379/0
echo.
echo Scheduled Tasks:
echo   * 2:00 AM UTC - Refresh materialized views
echo   * 3:00 AM UTC - Pull satellite data ^& retrain models
echo   * 4:00 AM UTC - Generate daily risk assessments
echo   * 5:00 AM UTC ^(Sundays^) - Validate SPI forecasts
echo.
pause
