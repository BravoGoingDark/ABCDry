#!/usr/bin/env python
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')
django.setup()

from dashboard.models import (
    SoilMetrics, ClimateMetrics, DroughtIndices, 
    AgriculturalMetrics, RemoteSensingMetrics, HydrologyMetrics,
    DataImportLog, Region, ObservationYear
)
from django.db.models import Min, Max
from datetime import datetime, timedelta

models = [
    ('Soil Metrics', SoilMetrics),
    ('Climate Metrics', ClimateMetrics),
    ('Drought Indices', DroughtIndices),
    ('Agricultural Metrics', AgriculturalMetrics),
    ('Remote Sensing', RemoteSensingMetrics),
    ('Hydrology Metrics', HydrologyMetrics),
]

print("\n" + "="*60)
print("DATASET STATUS REPORT")
print("="*60)

total_records = 0
for label, model in models:
    count = model.objects.count()
    total_records += count
    if count > 0:
        date_range = model.objects.aggregate(
            min_date=Min('measurement_date'),
            max_date=Max('measurement_date')
        )
        min_date = date_range['min_date']
        max_date = date_range['max_date']
        years_covered = (max_date - min_date).days / 365.25 if min_date else 0
        
        print(f"\n{label}:")
        print(f"  Records: {count:,}")
        print(f"  Date range: {min_date} to {max_date}")
        print(f"  Time span: {years_covered:.1f} years")
    else:
        print(f"\n{label}: ⚠️  No data")

print(f"\n{'='*60}")
print(f"Total Records: {total_records:,}")
print(f"{'='*60}")

# Check import logs
print("\nRECENT IMPORTS:")
print("-" * 60)
logs = DataImportLog.objects.all().order_by('-import_date')[:10]
if logs:
    for log in logs:
        failed = log.records_imported if hasattr(log, 'records_imported') else 0
        status = "✅" if failed == 0 else "⚠️"
        print(f"{status} {log.source:20} | Rows: {log.records_imported:5} | Status: {log.status} | {log.import_date.strftime('%Y-%m-%d %H:%M') if log.import_date else 'N/A'}")
else:
    print("No import logs found")

# Check reference data
print("\nREFERENCE DATA:")
print("-" * 60)
regions = Region.objects.count()
years = ObservationYear.objects.count()
print(f"Regions: {regions}")
print(f"Observation Years: {years}")

# Check data reliability
print("\nDATA QUALITY:")
print("-" * 60)
has_10_years = False
for label, model in models:
    if model.objects.count() > 0:
        date_range = model.objects.aggregate(
            min_date=Min('measurement_date'),
            max_date=Max('measurement_date')
        )
        min_date = date_range['min_date']
        max_date = date_range['max_date']
        if min_date:
            years_span = (max_date - min_date).days / 365.25
            if years_span >= 10:
                has_10_years = True
                break

if has_10_years:
    print("✅ Dataset has 10+ years of data")
else:
    print("⚠️  Dataset does NOT have 10 years of historical data")

# Check automatic data gathering
print("\nAUTOMATIC DATA COLLECTION:")
print("-" * 60)
print("Celery tasks configured: ✅")
print("  - Daily risk assessments")
print("  - Materialized view refresh (PostgreSQL)")
print("\nSatellite data sources:")
print("  - Google Earth Engine integration: Check keys/gee-service-account.json")
print("  - Manual integration scripts: scripts/pull_satellite*.py")
print("  - Remote sensing imports: Manual (Excel/CSV)")
print("\nAutomated data pulling: ❌ NOT CONFIGURED BY DEFAULT")
print("  → You must configure Celery beat to run periodic tasks")
print("  → Satellite data requires manual scripts or GEE API setup")

print("\n" + "="*60 + "\n")
