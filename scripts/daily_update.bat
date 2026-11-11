@echo off
rem Daily data update, run by the Windows scheduled task "APWRS daily data update".
rem   1. Two Ichkeul stations: new ERA5-Land / CHIRPS days (update_station_climate)
rem   2. SmartFarm soil probe: new readings (sync_smartfarm)
rem   3. Analysis map: today's NDVI / NDWI / temperature / rainfall / SPI tiles (warm_map_layers)
rem   4. Analysis risk cards: today's drought prediction for Ichkeul (generate_drought_prediction)
rem Output is appended to logs\daily_update.log.

cd /d "%~dp0.."
set "PY=C:\Users\Taha\AppData\Local\Programs\Python\Python311\python.exe"
set "PYTHONIOENCODING=utf-8"
if not exist logs mkdir logs

echo ===== %date% %time% =====>> logs\daily_update.log
"%PY%" manage.py update_station_climate >> logs\daily_update.log 2>&1
"%PY%" manage.py sync_smartfarm --days 14 >> logs\daily_update.log 2>&1
"%PY%" manage.py warm_map_layers >> logs\daily_update.log 2>&1
"%PY%" manage.py generate_drought_prediction --region-name Ichkeul >> logs\daily_update.log 2>&1
echo.>> logs\daily_update.log
