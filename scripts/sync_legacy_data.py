import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agri_dashboard.settings')
import django
django.setup()
from django.db import connection, transaction
from django.utils import timezone
from dashboard.models import (
    Region,
    ObservationYear,
    CropType,
    IrrigationMethod,
    EnvironmentalSnapshot,
    SoilMetrics,
    ClimateMetrics,
    DroughtIndices,
    AgriculturalMetrics,
    RemoteSensingMetrics,
    HydrologyMetrics,
    RiskAssessment,
    DataImportLog,
)


def fetch_rows(table_name):
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT * FROM public.{table_name} ORDER BY 1')
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def sync_simple(model, source_table, defaults_fields):
    for row in fetch_rows(source_table):
        defaults = {field: row.get(field) for field in defaults_fields}
        model.objects.update_or_create(id=row['id'], defaults=defaults)


def reset_sequence(table_name, pk_column):
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT setval(
                pg_get_serial_sequence(%s, %s),
                COALESCE((SELECT MAX({pk_column}) FROM {table_name}), 1),
                (SELECT MAX({pk_column}) IS NOT NULL FROM {table_name})
            )
            """,
            [table_name, pk_column],
        )


with transaction.atomic():
    sync_simple(Region, 'dashboard_region', ['name'])
    sync_simple(ObservationYear, 'dashboard_observationyear', ['label'])
    sync_simple(CropType, 'dashboard_croptype', ['name'])
    sync_simple(IrrigationMethod, 'dashboard_irrigationmethod', ['name'])

    for row in fetch_rows('dashboard_environmentalsnapshot'):
        obj, _ = EnvironmentalSnapshot.objects.update_or_create(
            id=row['id'],
            defaults={
                'region_id': row['region_id'],
                'year_id': row['year_id'],
                'wind_speed_kmh': row.get('wind_speed_kmh'),
                'wind_gust_kmh': row.get('wind_gust_kmh'),
                'wind_direction': row.get('wind_direction'),
                'rainfall_mm': row.get('rainfall_mm'),
                'rainfall_delta_percent': row.get('rainfall_delta_percent'),
                'ph_level': row.get('ph_level'),
                'npk_index': row.get('npk_index'),
                'temperature_c': row.get('temperature_c'),
                'humidity_percent': row.get('humidity_percent'),
                'updated_at': row.get('updated_at') or timezone.now(),
            },
        )
        EnvironmentalSnapshot.objects.filter(id=obj.id).update(time=row.get('updated_at') or timezone.now())

    for row in fetch_rows('dashboard_soilmetrics'):
        SoilMetrics.objects.update_or_create(
            id=row['id'],
            defaults={
                'region_id': row['region_id'],
                'year_id': row['year_id'],
                'measurement_date': row.get('measurement_date'),
                'moisture_content_percent': row.get('moisture_content_percent'),
                'sand_ratio': row.get('sand_ratio'),
                'clay_ratio': row.get('clay_ratio'),
                'silt_ratio': row.get('silt_ratio'),
                'root_zone_depth_mm': row.get('root_zone_depth_mm'),
                'organic_matter_percent': row.get('organic_matter_percent'),
                'infiltration_rate_mmhr': row.get('infiltration_rate_mmhr'),
                'field_capacity_percent': row.get('field_capacity_percent'),
                'wilting_point_percent': row.get('wilting_point_percent'),
                'salinity_ece_dsm': row.get('salinity_ece_dsm'),
                'ph_level': row.get('ph_level'),
                'updated_at': row.get('updated_at') or timezone.now(),
            },
        )

    for row in fetch_rows('dashboard_climatemetrics'):
        ClimateMetrics.objects.update_or_create(
            id=row['id'],
            defaults={
                'region_id': row['region_id'],
                'year_id': row['year_id'],
                'measurement_date': row.get('measurement_date'),
                'rainfall_mm': row.get('rainfall_mm'),
                'seasonal_rainfall_variability': row.get('seasonal_rainfall_variability'),
                'temperature_max_c': row.get('temperature_max_c'),
                'temperature_min_c': row.get('temperature_min_c'),
                'temperature_mean_c': row.get('temperature_mean_c'),
                'relative_humidity_percent': row.get('relative_humidity_percent'),
                'wind_speed_ms': row.get('wind_speed_ms'),
                'solar_radiation_mjm2day': row.get('solar_radiation_mjm2day'),
                'evapotranspiration_et0_mmday': row.get('evapotranspiration_et0_mmday'),
                'evapotranspiration_etc_mmday': row.get('evapotranspiration_etc_mmday'),
                'updated_at': row.get('updated_at') or timezone.now(),
            },
        )

    for row in fetch_rows('dashboard_droughtindices'):
        DroughtIndices.objects.update_or_create(
            id=row['id'],
            defaults={
                'region_id': row['region_id'],
                'year_id': row['year_id'],
                'measurement_date': row.get('measurement_date'),
                'spi_1month': row.get('spi_1month'),
                'spi_3month': row.get('spi_3month'),
                'spi_12month': row.get('spi_12month'),
                'spei_1month': row.get('spei_1month'),
                'spei_3month': row.get('spei_3month'),
                'spei_12month': row.get('spei_12month'),
                'pdsi_value': row.get('pdsi_value'),
                'drought_severity_class': row.get('drought_severity_class') or 'None',
                'updated_at': row.get('updated_at') or timezone.now(),
            },
        )

    for row in fetch_rows('dashboard_agriculturalmetrics'):
        AgriculturalMetrics.objects.update_or_create(
            id=row['id'],
            defaults={
                'region_id': row['region_id'],
                'year_id': row['year_id'],
                'crop_id': row['crop_id'],
                'measurement_date': row.get('measurement_date'),
                'growth_stage': row.get('growth_stage'),
                'crop_coefficient_kc': row.get('crop_coefficient_kc'),
                'crop_water_requirement_mmday': row.get('crop_water_requirement_mmday'),
                'yield_reduction_factor': row.get('yield_reduction_factor'),
                'irrigation_method_id': row.get('irrigation_method_id'),
                'irrigation_efficiency_percent': row.get('irrigation_efficiency_percent'),
                'water_applied_mm': row.get('water_applied_mm'),
                'leaf_temperature_c': row.get('leaf_temperature_c'),
                'stomatal_conductance': row.get('stomatal_conductance'),
                'updated_at': row.get('updated_at') or timezone.now(),
            },
        )

    for row in fetch_rows('dashboard_remotesensingmetrics'):
        RemoteSensingMetrics.objects.update_or_create(
            id=row['id'],
            defaults={
                'region_id': row['region_id'],
                'year_id': row['year_id'],
                'measurement_date': row.get('measurement_date'),
                'ndvi': row.get('ndvi'),
                'ndwi': row.get('ndwi'),
                'land_surface_temperature_c': row.get('land_surface_temperature_c'),
                'satellite_soil_moisture_percent': row.get('satellite_soil_moisture_percent'),
                'satellite_source': row.get('satellite_source'),
                'vegetation_condition_index': row.get('vegetation_condition_index'),
                'evapotranspiration_sebal_mmday': row.get('evapotranspiration_sebal_mmday'),
                'updated_at': row.get('updated_at') or timezone.now(),
            },
        )

    for row in fetch_rows('dashboard_hydrologymetrics'):
        HydrologyMetrics.objects.update_or_create(
            id=row['id'],
            defaults={
                'region_id': row['region_id'],
                'year_id': row['year_id'],
                'measurement_date': row.get('measurement_date'),
                'precipitation_mm': row.get('precipitation_mm'),
                'evapotranspiration_mm': row.get('evapotranspiration_mm'),
                'groundwater_depth_m': row.get('groundwater_depth_m'),
                'runoff_mm': row.get('runoff_mm'),
                'river_flow_m3s': row.get('river_flow_m3s'),
                'reservoir_storage_m3': row.get('reservoir_storage_m3'),
                'irrigation_supply_available_m3': row.get('irrigation_supply_available_m3'),
                'soil_water_deficit_index_mm': row.get('soil_water_deficit_index_mm'),
                'water_balance_percent': row.get('water_balance_percent'),
                'updated_at': row.get('updated_at') or timezone.now(),
            },
        )

    for row in fetch_rows('dashboard_riskassessment'):
        RiskAssessment.objects.update_or_create(
            id=row['id'],
            defaults={
                'region_id': row['region_id'],
                'year_id': row['year_id'],
                'crop_id': row['crop_id'],
                'irrigation_id': row.get('irrigation_id'),
                'risk_level': row.get('risk_level'),
                'recommendation': row.get('recommendation'),
                'created_at': row.get('created_at') or timezone.now(),
            },
        )

    for row in fetch_rows('dashboard_dataimportlog'):
        DataImportLog.objects.update_or_create(
            id=row['id'],
            defaults={
                'source': row.get('source'),
                'filename': row.get('filename') or '',
                'metric_type': row.get('metric_type'),
                'records_imported': row.get('records_imported') or 0,
                'import_date': row.get('import_date') or timezone.now(),
                'imported_by': row.get('imported_by') or '',
                'notes': row.get('notes') or '',
                'status': row.get('status') or 'Success',
                'error_details': row.get('error_details'),
            },
        )

    reset_sequence('regions', 'region_id')
    reset_sequence('observation_years', 'year_id')
    reset_sequence('crop_types', 'crop_id')
    reset_sequence('irrigation_methods', 'irrigation_id')
    reset_sequence('environmental_snapshots', 'snapshot_id')
    reset_sequence('soil_metrics', 'metric_id')
    reset_sequence('climate_metrics', 'metric_id')
    reset_sequence('drought_indices', 'metric_id')
    reset_sequence('agricultural_metrics', 'metric_id')
    reset_sequence('remote_sensing_metrics', 'metric_id')
    reset_sequence('hydrology_metrics', 'metric_id')
    reset_sequence('risk_assessments', 'assessment_id')
    reset_sequence('data_import_logs', 'log_id')

print('sync complete')
