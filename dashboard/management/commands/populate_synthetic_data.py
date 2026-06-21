from datetime import date, datetime
from decimal import Decimal

import numpy as np
import pandas as pd

from django.core.management.base import BaseCommand

from dashboard.models import (
    AgriculturalMetrics,
    ClimateMetrics,
    CropType,
    DroughtIndices,
    EnvironmentalSnapshot,
    HydrologyMetrics,
    IrrigationMethod,
    ObservationYear,
    Region,
    RemoteSensingMetrics,
    SoilMetrics,
)
from scripts.generate_sample_drought_data import generate_sample_drought_data


class Command(BaseCommand):
    help = 'Generate synthetic drought metric data for a region/year.'

    def add_arguments(self, parser):
        parser.add_argument('--region-id', type=int, default=4, help='Region pk (default 4 = Ichkeul)')
        parser.add_argument('--year-id', type=int, default=6, help='Year pk (default 6 = 2024)')
        parser.add_argument('--crop-id', type=int, default=5, help='Crop pk (default 5 = Wheat)')
        parser.add_argument('--irrigation-id', type=int, default=4, help='Irrigation pk (default 4 = Drip)')
        parser.add_argument('--days', type=int, default=365, help='Number of days to generate')
        parser.add_argument('--seed', type=int, default=42)
        parser.add_argument('--end-date', type=str, default='2024-12-31')
        parser.add_argument('--dry-run', action='store_true', help='Print counts without saving')

    def _to_decimal(self, value, max_digits=5, decimal_places=2):
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return None
        try:
            return Decimal(str(round(value, decimal_places)))
        except (ValueError, TypeError, Decimal.InvalidOperation):
            return None

    def handle(self, *args, **options):
        region_id = options['region_id']
        year_id = options['year_id']
        crop_id = options['crop_id']
        irrigation_id = options['irrigation_id']
        days = options['days']
        seed = options['seed']
        end_date = options['end_date']
        dry_run = options['dry_run']

        region = Region.objects.filter(pk=region_id).first()
        year = ObservationYear.objects.filter(pk=year_id).first()
        crop = CropType.objects.filter(pk=crop_id).first()
        irrigation = IrrigationMethod.objects.filter(pk=irrigation_id).first()

        if not region: raise CommandError(f'Region {region_id} not found')
        if not year: raise CommandError(f'Year {year_id} not found')
        if not crop: raise CommandError(f'Crop {crop_id} not found')
        if not irrigation: raise CommandError(f'Irrigation {irrigation_id} not found')

        self.stdout.write(f'Generating {days} days of data for {region.name} / {year.label} …')
        df = generate_sample_drought_data(
            days=days, seed=seed,
            region_id=region_id, year_id=year_id,
            crop_id=crop_id, irrigation_id=irrigation_id,
            end_date=end_date,
        )

        soil_batch = []
        climate_batch = []
        drought_batch = []
        agri_batch = []
        remote_batch = []
        hydro_batch = []
        snapshot_batch = []

        for _, row in df.iterrows():
            dt = row['time']
            if isinstance(dt, datetime):
                dt = dt.date()
            elif isinstance(dt, date):
                pass
            else:
                dt = pd.Timestamp(dt).date()

            lat = self._to_decimal(row.get('region_latitude'), 10, 6)
            lng = self._to_decimal(row.get('region_longitude'), 10, 6)

            soil_batch.append(SoilMetrics(
                region=region, year=year, measurement_date=dt, latitude=lat, longitude=lng,
                moisture_content_percent=self._to_decimal(row.get('moisture_content_percent')),
                sand_ratio=self._to_decimal(row.get('sand_ratio')),
                clay_ratio=self._to_decimal(row.get('clay_ratio')),
                silt_ratio=self._to_decimal(row.get('silt_ratio')),
                root_zone_depth_mm=int(row.get('root_zone_depth_mm', 0)) if not np.isnan(row.get('root_zone_depth_mm', 0)) else None,
                organic_matter_percent=self._to_decimal(row.get('organic_matter_percent')),
                infiltration_rate_mmhr=self._to_decimal(row.get('infiltration_rate_mmhr')),
                field_capacity_percent=self._to_decimal(row.get('field_capacity_percent')),
                wilting_point_percent=self._to_decimal(row.get('wilting_point_percent')),
                salinity_ece_dsm=self._to_decimal(row.get('salinity_ece_dsm'), 5, 3),
                ph_level=self._to_decimal(row.get('soil_ph_level'), 3, 1),
            ))

            climate_batch.append(ClimateMetrics(
                region=region, year=year, measurement_date=dt, latitude=lat, longitude=lng,
                rainfall_mm=self._to_decimal(row.get('rainfall_mm'), 6, 1),
                seasonal_rainfall_variability=row.get('seasonal_rainfall_variability', ''),
                temperature_max_c=self._to_decimal(row.get('temperature_max_c'), 4, 1),
                temperature_min_c=self._to_decimal(row.get('temperature_min_c'), 4, 1),
                temperature_mean_c=self._to_decimal(row.get('temperature_mean_c'), 4, 1),
                relative_humidity_percent=int(row['relative_humidity_percent']) if not np.isnan(row.get('relative_humidity_percent', 0)) else None,
                wind_speed_ms=self._to_decimal(row.get('wind_speed_ms'), 4, 2),
                solar_radiation_mjm2day=self._to_decimal(row.get('solar_radiation_mjm2day'), 6, 2),
                evapotranspiration_et0_mmday=self._to_decimal(row.get('evapotranspiration_et0_mmday'), 5, 2),
                evapotranspiration_etc_mmday=self._to_decimal(row.get('evapotranspiration_etc_mmday'), 5, 2),
            ))

            drought_batch.append(DroughtIndices(
                region=region, year=year, measurement_date=dt, latitude=lat, longitude=lng,
                spi_1month=self._to_decimal(row.get('spi_1month')),
                spi_3month=self._to_decimal(row.get('spi_3month')),
                spi_12month=self._to_decimal(row.get('spi_12month')),
                spei_1month=self._to_decimal(row.get('spei_1month')),
                spei_3month=self._to_decimal(row.get('spei_3month')),
                spei_12month=self._to_decimal(row.get('spei_12month')),
                pdsi_value=self._to_decimal(row.get('pdsi_value')),
                drought_severity_class=row.get('drought_severity_class', 'None'),
            ))

            agri_batch.append(AgriculturalMetrics(
                region=region, year=year, crop=crop, measurement_date=dt, latitude=lat, longitude=lng,
                growth_stage=row.get('growth_stage', 'Germination'),
                crop_coefficient_kc=self._to_decimal(row.get('crop_coefficient_kc')),
                crop_water_requirement_mmday=self._to_decimal(row.get('crop_water_requirement_mmday')),
                yield_reduction_factor=self._to_decimal(row.get('yield_reduction_factor'), 5, 3),
                irrigation_method=irrigation,
                irrigation_efficiency_percent=int(row['irrigation_efficiency_percent']) if not np.isnan(row.get('irrigation_efficiency_percent', 0)) else None,
                water_applied_mm=self._to_decimal(row.get('water_applied_mm'), 6, 2),
                leaf_temperature_c=self._to_decimal(row.get('leaf_temperature_c'), 4, 1),
                stomatal_conductance=self._to_decimal(row.get('stomatal_conductance'), 6, 3),
            ))

            remote_batch.append(RemoteSensingMetrics(
                region=region, year=year, measurement_date=dt, latitude=lat, longitude=lng,
                ndvi=self._to_decimal(row.get('ndvi'), 4, 3),
                ndwi=self._to_decimal(row.get('ndwi'), 4, 3),
                land_surface_temperature_c=self._to_decimal(row.get('land_surface_temperature_c'), 5, 2),
                satellite_soil_moisture_percent=self._to_decimal(row.get('satellite_soil_moisture_percent')),
                satellite_source='MODIS',
                vegetation_condition_index=self._to_decimal(row.get('vegetation_condition_index')),
                evapotranspiration_sebal_mmday=self._to_decimal(row.get('evapotranspiration_sebal_mmday'), 5, 2),
            ))

            hydro_batch.append(HydrologyMetrics(
                region=region, year=year, measurement_date=dt, latitude=lat, longitude=lng,
                precipitation_mm=self._to_decimal(row.get('precipitation_mm'), 6, 1),
                evapotranspiration_mm=self._to_decimal(row.get('evapotranspiration_mm'), 6, 1),
                groundwater_depth_m=self._to_decimal(row.get('groundwater_depth_m'), 6, 2),
                runoff_mm=self._to_decimal(row.get('runoff_mm'), 6, 1),
                river_flow_m3s=self._to_decimal(row.get('river_flow_m3s'), 10, 2),
                reservoir_storage_m3=int(row['reservoir_storage_m3']) if not np.isnan(row.get('reservoir_storage_m3', 0)) else None,
                irrigation_supply_available_m3=int(row['irrigation_supply_available_m3']) if not np.isnan(row.get('irrigation_supply_available_m3', 0)) else None,
                soil_water_deficit_index_mm=self._to_decimal(row.get('soil_water_deficit_index_mm'), 6, 2),
                water_balance_percent=self._to_decimal(row.get('water_balance_percent'), 6, 2),
            ))

            snapshot_batch.append(EnvironmentalSnapshot(
                region=region, year=year,
                wind_speed_kmh=self._to_decimal(row.get('wind_speed_kmh'), 5, 1),
                wind_gust_kmh=self._to_decimal(row.get('wind_gust_kmh'), 5, 1),
                wind_direction=row.get('wind_direction', 'NE'),
                rainfall_mm=self._to_decimal(row.get('rainfall_mm'), 6, 1),
                rainfall_delta_percent=int(row['rainfall_delta_percent']) if not np.isnan(row.get('rainfall_delta_percent', 0)) else 0,
                ph_level=self._to_decimal(row.get('ph_level'), 3, 1),
                npk_index=row.get('npk_index', 'Med-High'),
                temperature_c=self._to_decimal(row.get('temperature_c'), 4, 1),
                humidity_percent=int(row['humidity_percent']) if not np.isnan(row.get('humidity_percent', 0)) else 60,
            ))

        if dry_run:
            self.stdout.write(f'Would create: Soil={len(soil_batch)} Climate={len(climate_batch)} Drought={len(drought_batch)} '
                              f'Agri={len(agri_batch)} Remote={len(remote_batch)} Hydro={len(hydro_batch)} Snapshot={len(snapshot_batch)}')
            return

        SoilMetrics.objects.filter(region=region, year=year).delete()
        ClimateMetrics.objects.filter(region=region, year=year).delete()
        DroughtIndices.objects.filter(region=region, year=year).delete()
        AgriculturalMetrics.objects.filter(region=region, year=year).delete()
        RemoteSensingMetrics.objects.filter(region=region, year=year).delete()
        HydrologyMetrics.objects.filter(region=region, year=year).delete()
        EnvironmentalSnapshot.objects.filter(region=region, year=year).delete()

        SoilMetrics.objects.bulk_create(soil_batch, batch_size=200)
        ClimateMetrics.objects.bulk_create(climate_batch, batch_size=200)
        DroughtIndices.objects.bulk_create(drought_batch, batch_size=200)
        AgriculturalMetrics.objects.bulk_create(agri_batch, batch_size=200)
        RemoteSensingMetrics.objects.bulk_create(remote_batch, batch_size=200)
        HydrologyMetrics.objects.bulk_create(hydro_batch, batch_size=200)
        EnvironmentalSnapshot.objects.bulk_create(snapshot_batch, batch_size=200)

        self.stdout.write(self.style.SUCCESS(
            f'Inserted {len(soil_batch)} soil, {len(climate_batch)} climate, {len(drought_batch)} drought, '
            f'{len(agri_batch)} agri, {len(remote_batch)} remote, {len(hydro_batch)} hydro, '
            f'{len(snapshot_batch)} snapshot records for {region.name} / {year.label}.'
        ))
