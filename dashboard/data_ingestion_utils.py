# dashboard/data_ingestion_utils.py
# Utility functions for data ingestion and import handling

import json
import numpy as np
import pandas as pd
from datetime import datetime
from django.contrib.auth.models import User
from django.db import transaction
from django.utils.translation import gettext as _

from .models import (
    Region, ObservationYear, CropType, IrrigationMethod,
    SoilMetrics, ClimateMetrics, DroughtIndices,
    AgriculturalMetrics, RemoteSensingMetrics, HydrologyMetrics,
    DataImportLog
)


class DataIngestionError(Exception):
    """Custom exception for data ingestion errors"""
    pass


class DataImporter:
    """Main handler for importing metrics from various sources"""
    
    def __init__(self, source='Manual', username='Unknown'):
        self.source = source
        self.username = username
        self.imported_records = 0
        self.errors = []
        self.warnings = []
    
    def import_soil_metrics(self, data_dict):
        """Import soil metrics from dictionary/form data"""
        def _get(key, caster=float, default=None, allow_partial=False):
            v = data_dict.get(key)
            if v is None or v == '':
                if allow_partial:
                    return default
                raise KeyError(key)
            try:
                return caster(v)
            except Exception:
                if allow_partial:
                    return default
                raise

        # Remote sensing data often misses some columns; allow partial by default
        allow_partial = data_dict.get('allow_partial') or data_dict.get('force_partial') or True
        try:
            region = Region.objects.get(id=data_dict['region_id'])
            year = ObservationYear.objects.get(id=data_dict['year_id'])

            defaults = {
                'moisture_content_percent': _get('moisture_content_percent', float, None, allow_partial),
                'sand_ratio': _get('sand_ratio', float, None, allow_partial),
                'clay_ratio': _get('clay_ratio', float, None, allow_partial),
                'silt_ratio': _get('silt_ratio', float, None, allow_partial),
                'root_zone_depth_mm': _get('root_zone_depth_mm', int, None, allow_partial),
                'organic_matter_percent': _get('organic_matter_percent', float, None, allow_partial),
                'infiltration_rate_mmhr': _get('infiltration_rate_mmhr', float, None, allow_partial),
                'field_capacity_percent': _get('field_capacity_percent', float, None, allow_partial),
                'wilting_point_percent': _get('wilting_point_percent', float, None, allow_partial),
                'salinity_ece_dsm': _get('salinity_ece_dsm', float, None, allow_partial),
                'ph_level': _get('ph_level', float, None, allow_partial),
                'latitude': data_dict.get('latitude'),
                'longitude': data_dict.get('longitude'),
            }

            obj, created = SoilMetrics.objects.update_or_create(
                region=region,
                year=year,
                measurement_date=data_dict.get('measurement_date'),
                defaults=defaults,
            )
            self.last_action = 'created' if created else 'updated'
            # Count as an imported record whether created or updated
            self.imported_records += 1
            return obj
        except Exception as e:
            self.errors.append(f"Soil import error: {str(e)}")
            raise
    
    def _calculate_and_save_spi(self, region, measurement_date, rainfall_mm):
        """Calculate SPI-1/3/12 from historical rainfall using gamma distribution and save."""
        from scipy import stats as scipy_stats
        all_climate = ClimateMetrics.objects.filter(
            region=region,
            rainfall_mm__isnull=False,
        ).order_by('measurement_date')

        vals = [float(c.rainfall_mm) for c in all_climate]
        if len(vals) < 2:
            return

        series = pd.Series(vals)
        overall_mean = float(series.mean())
        overall_std = float(series.std())
        if overall_std == 0:
            return

        def _gamma_spi(rainfall_val, mean, std):
            if std == 0 or mean == 0:
                return 0.0
            variance = std ** 2
            alpha = (mean ** 2) / variance if variance > 0 else 1.0
            scale = variance / mean if mean > 0 else 1.0
            gamma_cdf = scipy_stats.gamma.cdf(max(0, rainfall_val), a=alpha, scale=scale)
            gamma_cdf = max(1e-15, min(1 - 1e-15, gamma_cdf))
            return float(scipy_stats.norm.ppf(gamma_cdf))

        spi_1 = round(max(-3.29, min(3.29, _gamma_spi(rainfall_mm, overall_mean, overall_std))), 2)

        spi_3 = spi_1
        if len(series) >= 90:
            m90 = float(series.rolling(90, min_periods=1).mean().iloc[-1])
            s90 = float(series.rolling(90, min_periods=1).std(ddof=0).iloc[-1])
            if s90 > 0:
                spi_3 = round(max(-3.29, min(3.29, _gamma_spi(rainfall_mm, m90, s90))), 2)

        spi_12 = spi_1
        if len(series) >= 365:
            m365 = float(series.rolling(365, min_periods=1).mean().iloc[-1])
            s365 = float(series.rolling(365, min_periods=1).std(ddof=0).iloc[-1])
            if s365 > 0:
                spi_12 = round(max(-3.29, min(3.29, _gamma_spi(rainfall_mm, m365, s365))), 2)

        year_label = str(measurement_date.year)
        year = ObservationYear.objects.filter(label=year_label).first()
        if not year:
            year = ObservationYear.objects.create(label=year_label)

        DroughtIndices.objects.update_or_create(
            region=region,
            year=year,
            measurement_date=measurement_date,
            defaults={
                'spi_1month': spi_1,
                'spi_3month': spi_3,
                'spi_12month': spi_12,
            },
        )

    def import_climate_metrics(self, data_dict):
        """Import climate metrics from dictionary/form data"""
        def _get(key, caster=float, default=None, allow_partial=False):
            v = data_dict.get(key)
            if v is None or v == '':
                if allow_partial:
                    return default
                raise KeyError(key)
            try:
                return caster(v)
            except Exception:
                if allow_partial:
                    return default
                raise

        allow_partial = data_dict.get('allow_partial') or data_dict.get('force_partial') or True
        try:
            region = Region.objects.get(id=data_dict['region_id'])
            year = ObservationYear.objects.get(id=data_dict['year_id'])

            defaults = {
                'temperature_max_c': _get('temperature_max_c', float, None, allow_partial),
                'temperature_min_c': _get('temperature_min_c', float, None, allow_partial),
                'temperature_mean_c': _get('temperature_mean_c', float, None, allow_partial),
                'relative_humidity_percent': _get('relative_humidity_percent', int, None, allow_partial),
                'rainfall_mm': _get('rainfall_mm', float, None, allow_partial),
                'wind_speed_ms': _get('wind_speed_ms', float, None, allow_partial),
                'solar_radiation_mjm2day': _get('solar_radiation_mjm2day', float, None, allow_partial),
                'evapotranspiration_et0_mmday': _get('evapotranspiration_et0_mmday', float, None, allow_partial),
                'evapotranspiration_etc_mmday': _get('evapotranspiration_etc_mmday', float, None, allow_partial),
                'seasonal_rainfall_variability': data_dict.get('seasonal_rainfall_variability', ''),
                'latitude': data_dict.get('latitude'),
                'longitude': data_dict.get('longitude'),
            }

            obj, created = ClimateMetrics.objects.update_or_create(
                region=region,
                year=year,
                measurement_date=data_dict.get('measurement_date'),
                defaults=defaults,
            )
            self.last_action = 'created' if created else 'updated'
            self.imported_records += 1

            # Auto-calculate SPI from rainfall if rainfall was provided
            rainfall_val = defaults.get('rainfall_mm')
            if rainfall_val is not None:
                self._calculate_and_save_spi(region, data_dict.get('measurement_date'), rainfall_val)

            return obj
        except Exception as e:
            self.errors.append(f"Climate import error: {str(e)}")
            raise
    
    def import_drought_indices(self, data_dict):
        """Import drought indices from dictionary/form data"""
        def _safe_float(v):
            try:
                return float(v)
            except Exception:
                return None

        try:
            region = Region.objects.get(id=data_dict['region_id'])
            year = ObservationYear.objects.get(id=data_dict['year_id'])

            defaults = {
                'spi_1month': _safe_float(data_dict.get('spi_1month')),
                'spi_3month': _safe_float(data_dict.get('spi_3month')),
                'spi_12month': _safe_float(data_dict.get('spi_12month')),
                'spei_1month': _safe_float(data_dict.get('spei_1month')),
                'spei_3month': _safe_float(data_dict.get('spei_3month')),
                'spei_12month': _safe_float(data_dict.get('spei_12month')),
                'pdsi_value': _safe_float(data_dict.get('pdsi_value')),
                'drought_severity_class': data_dict.get('drought_severity_class', 'None'),
                'latitude': data_dict.get('latitude'),
                'longitude': data_dict.get('longitude'),
            }

            obj, created = DroughtIndices.objects.update_or_create(
                region=region,
                year=year,
                measurement_date=data_dict.get('measurement_date'),
                defaults=defaults,
            )
            self.last_action = 'created' if created else 'updated'
            self.imported_records += 1
            return obj
        except Exception as e:
            self.errors.append(f"Drought import error: {str(e)}")
            raise
    
    def import_agricultural_metrics(self, data_dict):
        """Import agricultural metrics from dictionary/form data"""
        def _get(key, caster=float, default=None, allow_partial=False):
            v = data_dict.get(key)
            if v is None or v == '':
                if allow_partial:
                    return default
                raise KeyError(key)
            try:
                return caster(v)
            except Exception:
                if allow_partial:
                    return default
                raise

        allow_partial = data_dict.get('allow_partial') or data_dict.get('force_partial') or True
        try:
            region = Region.objects.get(id=data_dict['region_id'])
            year = ObservationYear.objects.get(id=data_dict['year_id'])
            crop = CropType.objects.get(id=data_dict['crop_id'])
            irrigation = None
            if data_dict.get('irrigation_id'):
                try:
                    irrigation = IrrigationMethod.objects.get(id=data_dict['irrigation_id'])
                except Exception:
                    irrigation = None

            defaults = {
                'growth_stage': data_dict.get('growth_stage'),
                'crop_coefficient_kc': _get('crop_coefficient_kc', float, None, allow_partial),
                'crop_water_requirement_mmday': _get('crop_water_requirement_mmday', float, None, allow_partial),
                'yield_reduction_factor': _get('yield_reduction_factor', float, None, allow_partial),
                'irrigation_method': irrigation,
                'irrigation_efficiency_percent': _get('irrigation_efficiency_percent', int, None, allow_partial),
                'water_applied_mm': _get('water_applied_mm', float, None, allow_partial),
                'leaf_temperature_c': _get('leaf_temperature_c', float, None, allow_partial),
                'stomatal_conductance': _get('stomatal_conductance', float, None, allow_partial),
                'latitude': data_dict.get('latitude'),
                'longitude': data_dict.get('longitude'),
            }

            obj, created = AgriculturalMetrics.objects.update_or_create(
                region=region,
                year=year,
                crop=crop,
                measurement_date=data_dict.get('measurement_date'),
                defaults=defaults,
            )
            self.last_action = 'created' if created else 'updated'
            self.imported_records += 1
            return obj
        except Exception as e:
            self.errors.append(f"Agricultural import error: {str(e)}")
            raise
    
    def import_remote_sensing_metrics(self, data_dict):
        """Import remote sensing metrics from dictionary/form data"""
        def _get(key, caster=float, default=None, allow_partial=False):
            v = data_dict.get(key)
            if v is None or v == '':
                if allow_partial:
                    return default
                raise KeyError(key)
            try:
                return caster(v)
            except Exception:
                if allow_partial:
                    return default
                raise

        # Remote sensing imports are commonly partial; default to allow_partial
        allow_partial = data_dict.get('allow_partial') or data_dict.get('force_partial') or True
        try:
            region = Region.objects.get(id=data_dict['region_id'])
            year = ObservationYear.objects.get(id=data_dict['year_id'])

            defaults = {
                'ndvi': _get('ndvi', float, None, allow_partial),
                'ndwi': _get('ndwi', float, None, allow_partial),
                'land_surface_temperature_c': _get('land_surface_temperature_c', float, None, allow_partial),
                'satellite_soil_moisture_percent': _get('satellite_soil_moisture_percent', float, None, allow_partial),
                'satellite_source': data_dict.get('satellite_source', 'Sentinel-2'),
                'vegetation_condition_index': _get('vegetation_condition_index', float, None, allow_partial),
                'evapotranspiration_sebal_mmday': _get('evapotranspiration_sebal_mmday', float, None, allow_partial),
                'latitude': data_dict.get('latitude'),
                'longitude': data_dict.get('longitude'),
            }

            obj, created = RemoteSensingMetrics.objects.update_or_create(
                region=region,
                year=year,
                measurement_date=data_dict.get('measurement_date'),
                defaults=defaults,
            )
            self.last_action = 'created' if created else 'updated'
            self.imported_records += 1
            return obj
        except Exception as e:
            self.errors.append(f"Remote sensing import error: {str(e)}")
            raise
    
    def import_hydrology_metrics(self, data_dict):
        """Import hydrology metrics from dictionary/form data"""
        def _get(key, caster=float, default=None, allow_partial=False):
            v = data_dict.get(key)
            if v is None or v == '':
                if allow_partial:
                    return default
                raise KeyError(key)
            try:
                return caster(v)
            except Exception:
                if allow_partial:
                    return default
                raise

        allow_partial = data_dict.get('allow_partial') or data_dict.get('force_partial') or False
        try:
            region = Region.objects.get(id=data_dict['region_id'])
            year = ObservationYear.objects.get(id=data_dict['year_id'])

            defaults = {
                'precipitation_mm': _get('precipitation_mm', float, None, allow_partial),
                'evapotranspiration_mm': _get('evapotranspiration_mm', float, None, allow_partial),
                'groundwater_depth_m': _get('groundwater_depth_m', float, None, allow_partial),
                'runoff_mm': _get('runoff_mm', float, None, allow_partial),
                'river_flow_m3s': _get('river_flow_m3s', float, None, allow_partial),
                'reservoir_storage_m3': _get('reservoir_storage_m3', float, None, allow_partial),
                'irrigation_supply_available_m3': _get('irrigation_supply_available_m3', float, None, allow_partial),
                'soil_water_deficit_index_mm': _get('soil_water_deficit_index_mm', float, None, allow_partial),
                'water_balance_percent': _get('water_balance_percent', float, None, allow_partial),
                'latitude': data_dict.get('latitude'),
                'longitude': data_dict.get('longitude'),
            }

            obj, created = HydrologyMetrics.objects.update_or_create(
                region=region,
                year=year,
                measurement_date=data_dict.get('measurement_date'),
                defaults=defaults,
            )
            self.last_action = 'created' if created else 'updated'
            self.imported_records += 1
            return obj
        except Exception as e:
            self.errors.append(f"Hydrology import error: {str(e)}")
            raise
    
    @transaction.atomic
    def submit_form_data(self, metric_type, data_dict):
        """Submit manually entered form data"""
        try:
            if metric_type == 'soil':
                return self.import_soil_metrics(data_dict)
            elif metric_type == 'climate':
                return self.import_climate_metrics(data_dict)
            elif metric_type == 'drought':
                return self.import_drought_indices(data_dict)
            elif metric_type == 'agricultural':
                return self.import_agricultural_metrics(data_dict)
            elif metric_type == 'remote_sensing':
                return self.import_remote_sensing_metrics(data_dict)
            elif metric_type == 'hydrology':
                return self.import_hydrology_metrics(data_dict)
            else:
                raise DataIngestionError(f"Unknown metric type: {metric_type}")
        except Exception as e:
            raise DataIngestionError(f"Failed to submit {metric_type} data: {str(e)}")
    
    def log_import(self, metric_type, filename='', notes=''):
        """Log the import operation to database"""
        status = 'Partial' if self.errors else 'Success'
        if not filename:
            filename = f'manual_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        
        import_log = DataImportLog.objects.create(
            source=self.source,
            filename=filename,
            metric_type=metric_type,
            records_imported=self.imported_records,
            status=status,
            imported_by=self.username,
            notes=notes or (f'{len(self.errors)} errors' if self.errors else 'No errors'),
            error_details=json.dumps(self.errors) if self.errors else None,
        )
        return import_log


def create_reference_data():
    """Create or verify reference data exists"""
    # Regions
    regions_data = ['Ichkeul', 'Kairouan', 'Meknes', 'Skhira', 'Tunisia', 'Morocco', 'Algeria', 'Bizerte']
    for name in regions_data:
        Region.objects.get_or_create(name=name)
    
    # Years
    years_data = [str(y) for y in range(2006, 2027)]
    for label in years_data:
        ObservationYear.objects.get_or_create(label=label)
    
    # Crops
    crops = ['Wheat', 'Barley', 'Olive', 'Date Palm', 'Alfalfa']
    for crop in crops:
        CropType.objects.get_or_create(name=crop)
    
    # Irrigation Methods
    irrigations = ['Drip Irrigation', 'Sprinkler', 'Flood/Basin', 'Furrow', 'Center Pivot']
    for irrigation in irrigations:
        IrrigationMethod.objects.get_or_create(name=irrigation)
