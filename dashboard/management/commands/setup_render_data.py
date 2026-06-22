import os
from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User

from dashboard.models import (
    AgriculturalMetrics, ClimateMetrics, CropType, DroughtIndices,
    EnvironmentalSnapshot, HydrologyMetrics, IrrigationMethod,
    ObservationYear, Region, RemoteSensingMetrics, SoilMetrics,
)
from dashboard.data_ingestion_utils import create_reference_data
from dashboard.prediction_engine.physical_helpers import calculate_et0
from scripts.generate_sample_drought_data import generate_sample_drought_data


class Command(BaseCommand):
    help = 'Setup Render with reference data, synthetic metrics, and default admin user.'

    def handle(self, *args, **options):
        # 1. Ensure admin user exists
        username = os.getenv('DJANGO_SUPERUSER_USERNAME', 'admin')
        password = os.getenv('DJANGO_SUPERUSER_PASSWORD', 'admin123')
        email = os.getenv('DJANGO_SUPERUSER_EMAIL', 'admin@abcdry.com')
        if not User.objects.filter(is_superuser=True).exists():
            User.objects.create_superuser(username=username, email=email, password=password)
            self.stdout.write(self.style.SUCCESS(f'Created superuser: {username}'))
        else:
            self.stdout.write('Superuser already exists.')

        # 2. Create reference data (regions, years, crops, irrigation)
        create_reference_data()
        self.stdout.write(self.style.SUCCESS('Reference data created.'))

        # 3. Look up objects by name to avoid PK hardcoding
        region = Region.objects.filter(name__iexact='Ichkeul').first()
        if not region:
            region = Region.objects.first()
        year = ObservationYear.objects.filter(label='2024').first()
        if not year:
            year = ObservationYear.objects.last()
        crop = CropType.objects.first()
        irrigation = IrrigationMethod.objects.first()

        if not all([region, year, crop, irrigation]):
            self.stdout.write(self.style.WARNING('Missing reference data, cannot populate metrics.'))
            return

        self.stdout.write(f'Populating data for {region.name} / {year.label} ...')

        # 4. Generate synthetic data for the past 365 days
        end = date.today()
        start = end - timedelta(days=365)
        days = 365

        rng = np.random.default_rng(42)
        dates = pd.date_range(end=pd.Timestamp(end), periods=days, freq='D')
        trend = np.linspace(0, 1, days)

        # 5. Generate all metric columns
        rainfall = np.clip(rng.gamma(shape=0.8, scale=2.2, size=days) - trend * 0.7, 0, None)
        irrigation_arr = np.where(rng.random(days) < 0.12, rng.uniform(2, 10, size=days), 0)
        temp_max = 28 + trend * 5 + rng.normal(0, 1.1, days)
        temp_min = 16 + trend * 2.5 + rng.normal(0, 0.8, days)
        temp_mean = (temp_max + temp_min) / 2
        humidity = np.clip(72 - trend * 12 + rng.normal(0, 3, days), 30, 95)
        wind_speed_ms = np.clip(3.0 + rng.normal(0, 0.4, days), 0.5, 8)
        solar_rad_wm2 = np.clip(240 + trend * 45 + rng.normal(0, 12, days), 140, 380)
        solar_rad_mjm2 = solar_rad_wm2 * 0.0864
        ndvi = np.clip(0.75 - trend * 0.18 + rng.normal(0, 0.015, days), 0.2, 0.85)
        lst_c = np.clip(26 + trend * 4 + rng.normal(0, 0.7, days), 18, 42)
        satellite_sm = np.clip(30 + trend * -6 + rng.normal(0, 2.0, days), 0, 60)
        vci = ((ndvi - ndvi.min()) / (ndvi.max() - ndvi.min() + 1e-8)) * 100

        soil_moisture = np.empty(days)
        soil_water = np.empty(days)
        et0 = np.empty(days)
        etc_mm = np.empty(days)
        soil_moisture[0] = 34.0
        soil_water[0] = 180.0

        for idx in range(days):
            es = 0.6108 * np.exp(17.27 * temp_mean[idx] / (temp_mean[idx] + 237.3))
            ea = es * (humidity[idx] / 100)
            vpd = es - ea
            delta = 4098 * es / (temp_mean[idx] + 237.3) ** 2
            psychrometric = 0.000665 * 101.3
            rn = solar_rad_wm2[idx] * 0.0864
            wind_factor = 0.26 * (1 + 0.54 * wind_speed_ms[idx])
            et0[idx] = max(0, (0.408 * delta * rn + psychrometric * wind_factor * vpd) / (delta + psychrometric))
            etc_mm[idx] = et0[idx] * 1.0
            if idx > 0:
                drought_pull = max(0, 0.65 * (1 - rainfall[idx] / 10) + 0.35 * (temp_max[idx] - 28) / 10)
                recharge = rainfall[idx] * 0.8 + irrigation_arr[idx] * 0.9
                soil_moisture[idx] = np.clip(soil_moisture[idx - 1] + recharge - etc_mm[idx] * 0.25 - drought_pull, 5, 45)
                soil_water[idx] = np.clip(soil_water[idx - 1] + rainfall[idx] + irrigation_arr[idx] - etc_mm[idx] - 0.1, 20, 260)

        moisture_pct = np.clip(soil_moisture + rng.normal(0, 1.0, days), 5, 45)
        fc = np.round(np.clip(31 + rng.normal(0, 1.0, days), 20, 45), 2)
        wp = np.round(np.clip(14 + rng.normal(0, 0.8, days), 5, 25), 2)

        spi = np.round((rainfall - rainfall.mean()) / (rainfall.std() + 1e-8), 2)

        sand = np.round(np.clip(42 + rng.normal(0, 2.0, days), 30, 65), 2)
        clay = np.round(np.clip(24 + rng.normal(0, 1.5, days), 10, 45), 2)
        silt = np.round(np.clip(100 - sand - clay, 15, 55), 2)

        growth_stages = ['Germination'] * days
        growth_stages[days//5:days//3] = ['Vegetative'] * (days//3 - days//5)
        growth_stages[days//3:days//2] = ['Flowering'] * (days//2 - days//3)
        growth_stages[days//2:int(days*0.8)] = ['Grain Filling'] * (int(days*0.8) - days//2)
        growth_stages[int(days*0.8):] = ['Maturity'] * (days - int(days*0.8))

        kc = np.round(np.clip(0.65 + trend * 0.5 + rng.normal(0, 0.03, days), 0.4, 1.25), 2)
        aquifer_depth = 5 + trend * 1.2 + rng.normal(0, 0.4, days)

        leaf_temp = np.round(temp_max + 1.5 + rng.normal(0, 0.7, days), 1)
        stomatal = np.round(np.clip(0.45 - trend * 0.22 + rng.normal(0, 0.02, days), 0.05, 0.6), 3)

        def d(v, dig=2):
            try:
                return Decimal(str(round(float(v), dig)))
            except:
                return None

        def safe_int(v):
            try:
                return int(round(float(v)))
            except:
                return None

        # Delete old data for this region/year
        SoilMetrics.objects.filter(region=region, year=year).delete()
        ClimateMetrics.objects.filter(region=region, year=year).delete()
        DroughtIndices.objects.filter(region=region, year=year).delete()
        AgriculturalMetrics.objects.filter(region=region, year=year).delete()
        RemoteSensingMetrics.objects.filter(region=region, year=year).delete()
        HydrologyMetrics.objects.filter(region=region, year=year).delete()
        EnvironmentalSnapshot.objects.filter(region=region, year=year).delete()

        # Bulk insert
        soil_batch = []
        climate_batch = []
        drought_batch = []
        agri_batch = []
        remote_batch = []
        hydro_batch = []
        snapshot_batch = []

        for i in range(days):
            dt = dates[i].date()
            lat = d(region.latitude, 6) if region.latitude else None
            lng = d(region.longitude, 6) if region.longitude else None

            soil_batch.append(SoilMetrics(
                region=region, year=year, measurement_date=dt, latitude=lat, longitude=lng,
                moisture_content_percent=d(moisture_pct[i]),
                sand_ratio=d(sand[i]), clay_ratio=d(clay[i]), silt_ratio=d(silt[i]),
                root_zone_depth_mm=safe_int(420 + trend[i] * 60),
                organic_matter_percent=d(np.clip(2.2 + rng.normal(0, 0.15), 1.0, 5.0)),
                infiltration_rate_mmhr=d(np.clip(12 + rng.normal(0, 1.2), 3, 30)),
                field_capacity_percent=d(fc[i]),
                wilting_point_percent=d(wp[i]),
                salinity_ece_dsm=d(np.clip(0.8 + trend[i] * 0.35 + rng.normal(0, 0.05), 0.1, 5), 3),
                ph_level=d(np.clip(7.0 - trend[i] * 0.3 + rng.normal(0, 0.1), 5.5, 8.2), 1),
            ))
            climate_batch.append(ClimateMetrics(
                region=region, year=year, measurement_date=dt, latitude=lat, longitude=lng,
                rainfall_mm=d(rainfall[i], 1),
                seasonal_rainfall_variability='Moderate',
                temperature_max_c=d(temp_max[i], 1),
                temperature_min_c=d(temp_min[i], 1),
                temperature_mean_c=d(temp_mean[i], 1),
                relative_humidity_percent=safe_int(humidity[i]),
                wind_speed_ms=d(wind_speed_ms[i], 2),
                solar_radiation_mjm2day=d(solar_rad_mjm2[i], 2),
                evapotranspiration_et0_mmday=d(et0[i], 2),
                evapotranspiration_etc_mmday=d(etc_mm[i], 2),
            ))
            drought_batch.append(DroughtIndices(
                region=region, year=year, measurement_date=dt, latitude=lat, longitude=lng,
                spi_1month=d(spi[i]),
                spi_3month=d(spi[i] * 0.9),
                spi_12month=d(spi[i] * 0.7),
                spei_1month=d(spi[i] - 0.15 * (etc_mm[i] - rainfall[i])),
                spei_3month=d(spi[i] * 0.9 - 0.12 * (etc_mm[i] - rainfall[i])),
                spei_12month=d(spi[i] * 0.7 - 0.1 * (etc_mm[i] - rainfall[i])),
                pdsi_value=d(np.clip(spi[i] * 1.2, -6, 6)),
                drought_severity_class='None' if spi[i] > -0.5 else 'Abnormally Dry' if spi[i] > -1 else 'Moderate Drought',
            ))
            agri_batch.append(AgriculturalMetrics(
                region=region, year=year, crop=crop, measurement_date=dt, latitude=lat, longitude=lng,
                growth_stage=growth_stages[i],
                crop_coefficient_kc=d(kc[i]),
                crop_water_requirement_mmday=d(np.clip(etc_mm[i] * kc[i], 0, None)),
                yield_reduction_factor=d(np.clip(1 - soil_moisture[i] / 60, 0, 1), 3),
                irrigation_method=irrigation,
                irrigation_efficiency_percent=safe_int(np.clip(62 + trend[i] * 22, 40, 95)),
                water_applied_mm=d(irrigation_arr[i] + etc_mm[i] * kc[i] * 0.35),
                leaf_temperature_c=d(leaf_temp[i], 1),
                stomatal_conductance=d(stomatal[i], 3),
            ))
            remote_batch.append(RemoteSensingMetrics(
                region=region, year=year, measurement_date=dt, latitude=lat, longitude=lng,
                ndvi=d(ndvi[i], 3),
                ndwi=d(np.clip(0.2 + (rainfall[i] / (rainfall.max() + 1e-8)) * 0.5, -0.2, 0.6), 3),
                land_surface_temperature_c=d(lst_c[i], 2),
                satellite_soil_moisture_percent=d(satellite_sm[i], 2),
                satellite_source='MODIS',
                vegetation_condition_index=d(vci[i], 2),
                evapotranspiration_sebal_mmday=d(np.clip(etc_mm[i] * 0.9 + rng.normal(0, 0.05), 0, None), 2),
            ))
            hydro_batch.append(HydrologyMetrics(
                region=region, year=year, measurement_date=dt, latitude=lat, longitude=lng,
                precipitation_mm=d(rainfall[i], 1),
                evapotranspiration_mm=d(etc_mm[i], 1),
                groundwater_depth_m=d(np.clip(aquifer_depth[i], 0.5, 20), 2),
                runoff_mm=d(np.clip(rainfall[i] * 0.18 + rng.normal(0, 0.8), 0, None), 1),
                river_flow_m3s=d(np.clip(10 + rainfall[i] * 2.5 + rng.normal(0, 3.0), 0, None), 2),
                reservoir_storage_m3=safe_int(np.clip(5e6 + (rainfall[:i+1].sum() - etc_mm[:i+1].sum()) * 10000, 0, None)) if i > 0 else 5000000,
                irrigation_supply_available_m3=safe_int(np.clip(100000 + irrigation_arr[:i+1].sum() * 5000, 0, None)) if i > 0 else 100000,
                soil_water_deficit_index_mm=d(np.clip(etc_mm[i] - rainfall[i] - irrigation_arr[i] * 0.5, -50, 80), 2),
                water_balance_percent=d(np.clip(((rainfall[i] + irrigation_arr[i]) / (etc_mm[i] + 1e-8)) * 100, 0, 250), 2),
            ))
            snapshot_batch.append(EnvironmentalSnapshot(
                region=region, year=year,
                wind_speed_kmh=d(wind_speed_ms[i] * 3.6, 1),
                wind_gust_kmh=d(np.clip(wind_speed_ms[i] * 3.6 + rng.uniform(5, 18), 0, None), 1),
                wind_direction='NE',
                rainfall_mm=d(rainfall[i], 1),
                rainfall_delta_percent=safe_int(0),
                ph_level=d(np.clip(7.2 - trend[i] * 0.4 + rng.normal(0, 0.1), 5.5, 8.3), 1),
                npk_index='Med-High',
                temperature_c=d(temp_mean[i], 1),
                humidity_percent=safe_int(humidity[i]),
            ))

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
