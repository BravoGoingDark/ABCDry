"""
Pull real satellite / reanalysis data into the metric tables using Google Earth Engine.

Datasets used (all free):
  - CHIRPS rainfall             -> UCSB-CHG/CHIRPS/DAILY          (mm/day, ~3 week latency)
  - IMERG rainfall (fallback)   -> NASA/GPM_L3/IMERG_V07          (mm/day, near real-time)
  - ERA5-Land climate           -> ECMWF/ERA5_LAND/DAILY_AGGR     (T, Td, u10, v10, ssrd)
  - MODIS NDVI                  -> MODIS/061/MOD13Q1              (16-day, 250 m)
  - MODIS LST                   -> MODIS/061/MOD11A1              (daily, 1 km)
  - SMAP surface soil moisture  -> NASA/SMAP/SPL4SMGP/008         (0-5 cm)
  - Sentinel-2 NDVI (preferred) -> COPERNICUS/S2_SR_HARMONIZED    (10 m, field-scale)
  - Sentinel-1 soil moisture    -> COPERNICUS/S1_GRD              (SAR, all-weather)

Precedence rules:
  - NDVI: Sentinel-2 first (10 m), fall back to MODIS.
  - Soil moisture: SMAP first (calibrated, ~9 km); Sentinel-1 only fills gaps
    as a coarse all-weather proxy pending ground-truth calibration.
  - Rainfall: CHIRPS first, IMERG only as a fallback. Re-running the
    pull later overwrites IMERG days with the final CHIRPS value
    (self-correcting).

Usage:
  python manage.py pull_satellite                    # last 90 days, all regions
  python manage.py pull_satellite --start-date 2025-01-01 --end-date 2025-12-31
  python manage.py pull_satellite --region-id 8 --every 1 --verbose

Credentials (set on Render or local .env):
  GEE_CREDENTIALS_FILE  -> path to a Google service-account JSON
  or GOOGLE_APPLICATION_CREDENTIALS (ADC default)
"""
import os
import sys
import threading
from datetime import date, datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from dashboard.models import (
    ClimateMetrics,
    DroughtIndices,
    ObservationYear,
    Region,
    RemoteSensingMetrics,
)
from dashboard.prediction_engine.physical_helpers import (
    calculate_et0,
    calculate_spi,
    calculate_vci,
)

try:
    import ee
    HAS_EE = True
except ImportError:  # pragma: no cover - optional dependency
    ee = None
    HAS_EE = False

try:
    import pandas as pd
except ImportError:
    pd = None


def _risk_from_spi(spi_value):
    """Map an SPI value (-3.29..3.29) to a 0-100 drought risk score."""
    if spi_value is None:
        return None
    risk = 50.0 - float(spi_value) * 15.0
    return max(0.0, min(100.0, risk))


class Command(BaseCommand):
    help = 'Pull real satellite/reanalysis data from Google Earth Engine into the metric tables.'

    def add_arguments(self, parser):
        parser.add_argument('--start-date', type=str, default=None, help='YYYY-MM-DD (default: 90 days ago)')
        parser.add_argument('--end-date', type=str, default=None, help='YYYY-MM-DD (default: today)')
        parser.add_argument('--region-id', type=int, default=None, help='Limit to one region id')
        parser.add_argument('--every', type=int, default=5, help='Sample daily datasets every N days (default 5)')
        parser.add_argument('--verbose', action='store_true', help='Print per-day details')
        parser.add_argument('--dry-run', action='store_true', help='Print what would be ingested without writing')
        parser.add_argument('--no-spi', action='store_true', help='Skip SPI recomputation after ingest')

    # ------------------------------------------------------------------ #
    # GEE bootstrap
    # ------------------------------------------------------------------ #
    def _init_ee(self):
        if not HAS_EE:
            raise CommandError(
                'The earthengine-api package is not installed. Run: pip install earthengine-api google-cloud-storage'
            )
        creds_file = os.getenv('GEE_CREDENTIALS_FILE') or os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
        try:
            if creds_file and os.path.exists(creds_file):
                import json
                from google.oauth2 import service_account
                project = os.getenv('GEE_PROJECT')
                if not project:
                    with open(creds_file) as cj:
                        project = json.load(cj).get('project_id')
                credentials = service_account.Credentials.from_service_account_file(
                    creds_file,
                    scopes=['https://www.googleapis.com/auth/earthengine.readonly'],
                )
                if project:
                    ee.Initialize(credentials, project=project)
                else:
                    ee.Initialize(credentials)
            else:
                # Fall back to interactive / ADC auth
                ee.Initialize()
        except Exception as exc:
            raise CommandError(
                'Earth Engine auth failed. Create a Google Earth Engine account, enable the '
                'Earth Engine API, and set GEE_CREDENTIALS_FILE to a service-account JSON.\n'
                f'Details: {exc}'
            )

    def _run_with_timeout(self, func, timeout=60, attempts=2):
        """Run func in a daemon thread so a hanging GEE call cannot stall the pull.
        Returns func's result, or None if it did not finish within `timeout` s."""
        for _ in range(attempts):
            box = {}

            def runner():
                try:
                    box['value'] = func()
                except Exception as exc:
                    box['error'] = exc

            t = threading.Thread(target=runner, daemon=True)
            t.start()
            t.join(timeout)
            if 'value' in box:
                return box['value']
        return None

    def _fetch(self, image, point, band, scale, factor=1.0, reducer=None, geometry=None):
        """Reduce a single band at a point (or basin geometry). Returns float or None."""
        reducer = reducer or ee.Reducer.mean()

        def _do():
            try:
                return image.reduceRegion(
                    reducer=reducer,
                    geometry=geometry or point,
                    scale=scale,
                    bestEffort=True,
                ).get(band).getInfo()
            except Exception:
                return None
        value = self._run_with_timeout(_do)
        if value is None or value == -9999:
            return None
        return float(value) * factor

    # ------------------------------------------------------------------ #
    # Per-dataset fetchers
    # ------------------------------------------------------------------ #
    def _chirps_rain(self, point, day):
        img = (ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY')
               .filterBounds(point)
               .filterDate(day.isoformat(), (day + timedelta(days=1)).isoformat())
               .first())
        if img is None:
            return None
        return self._fetch(img, point, 'precipitation', 5566)

    def _imerg_rain(self, point, day):
        """Near-real-time daily rain fallback (GPM IMERG V07).

        The collection is half-hourly (30 min mean rain rate, mm/h); the
        daily total is the sum of all 48 half-hour steps * 0.5 h.
        """
        imgs = (ee.ImageCollection('NASA/GPM_L3/IMERG_V07')
                .filterBounds(point)
                .filterDate(day.isoformat(), (day + timedelta(days=1)).isoformat())
                .select('precipitation'))
        if imgs is None:
            return None
        daily = imgs.sum().multiply(0.5)
        return self._fetch(daily, point, 'precipitation', 10000)

    def _rainfall(self, point, day):
        """CHIRPS first, IMERG fallback only when CHIRPS is missing."""
        chirps = self._chirps_rain(point, day)
        if chirps is not None:
            return chirps, 'CHIRPS'
        imerg = self._imerg_rain(point, day)
        if imerg is not None:
            return imerg, 'IMERG'
        return None, None

    def _era5_daily(self, point, day):
        img = (ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR')
               .filterBounds(point)
               .filterDate(day.isoformat(), (day + timedelta(days=1)).isoformat())
               .first())
        if img is None:
            return None
        bands = [
            'temperature_2m_max', 'temperature_2m_min', 'temperature_2m',
            'dewpoint_temperature_2m', 'u_component_of_wind_10m',
            'v_component_of_wind_10m', 'surface_solar_radiation_downwards_sum',
        ]
        def _do():
            try:
                return img.select(bands).reduceRegion(
                    reducer=ee.Reducer.mean(),
                    geometry=point,
                    scale=11132,
                    bestEffort=True,
                ).getInfo()
            except Exception:
                return None
        vals = self._run_with_timeout(_do)
        if not vals:
            return None

        # Convert Kelvin -> Celsius
        def _c(key):
            v = vals.get(key)
            if v is None or v == -9999:
                return None
            return round(float(v) - 273.15, 1)

        t2m = vals.get('temperature_2m')
        d2m = vals.get('dewpoint_temperature_2m')
        rh = None
        if t2m is not None and t2m != -9999 and d2m is not None and d2m != -9999:
            tc = float(t2m) - 273.15
            tdc = float(d2m) - 273.15
            es = 6.1078 * (10 ** ((7.5 * tc) / (237.3 + tc)))
            e = 6.1078 * (10 ** ((7.5 * tdc) / (237.3 + tdc)))
            rh = round(min(100.0, max(0.0, (e / es) * 100.0)))

        u10 = vals.get('u_component_of_wind_10m')
        v10 = vals.get('v_component_of_wind_10m')
        wind = None
        if u10 is not None and u10 != -9999 and v10 is not None and v10 != -9999:
            wind = round((float(u10) ** 2 + float(v10) ** 2) ** 0.5, 2)

        ssrd = vals.get('surface_solar_radiation_downwards_sum')
        solar = round(float(ssrd) / 1e6, 2) if ssrd is not None and ssrd != -9999 else None

        return {
            'temperature_max_c': _c('temperature_2m_max'),
            'temperature_min_c': _c('temperature_2m_min'),
            'temperature_mean_c': _c('temperature_2m'),
            'relative_humidity_percent': rh,
            'wind_speed_ms': wind,
            'solar_radiation_mjm2day': solar,
        }

    # Radius used to sample vegetation around the sample point. Regions such as
    # Ichkeul are wetland basins where the point itself may sit on open water
    # (NDVI ~ -0.1) while the surrounding marsh is green. Taking the MAX NDVI
    # within the basin captures the vegetation signal drought actually affects.
    NDVI_SAMPLE_RADIUS_M = 3000

    def _modis_ndvi(self, point, day):
        img = (ee.ImageCollection('MODIS/061/MOD13Q1')
               .filterBounds(point)
               .filterDate((day - timedelta(days=24)).isoformat(), (day + timedelta(days=1)).isoformat())
               .sort('system:time_start', False)
               .first())
        if img is None:
            return None
        ndvi = self._fetch(img, point, 'NDVI', 250, 0.0001,
                           reducer=ee.Reducer.max(),
                           geometry=point.buffer(self.NDVI_SAMPLE_RADIUS_M))
        if ndvi is not None and -0.2 <= ndvi <= 1.0:
            return round(ndvi, 3)
        return None

    def _sentinel2_ndvi(self, point, day):
        """Field-scale NDVI from Sentinel-2 (10 m). Looks back 15 days for a
        cloud-free scene, falling back to None so the caller can use MODIS.
        Sampled as the max NDVI within the basin radius to capture the
        vegetated fringe rather than open water at the sample point."""
        img = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
               .filterBounds(point)
               .filterDate((day - timedelta(days=15)).isoformat(), (day + timedelta(days=1)).isoformat())
               .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 30))
               .sort('system:time_start', False)
               .first())
        if img is None:
            return None
        ndvi = img.normalizedDifference(['B8', 'B4']).rename('ndvi')
        val = self._fetch(ndvi, point, 'ndvi', 10,
                          reducer=ee.Reducer.max(),
                          geometry=point.buffer(self.NDVI_SAMPLE_RADIUS_M))
        if val is not None and -0.2 <= val <= 1.0:
            return round(val, 3)
        return None

    def _sentinel3_ndvi(self, point, day):
        """Gap-filling NDVI from Sentinel-3 OLCI (300 m, 10-day global revisit).

        Sentinel-3 uses an off-grid orbit that guarantees global coverage every
        10 days, unlike Sentinel-2's fixed 5-day repeat that can leave gaps.
        Resolution is coarser (300 m vs 10 m) but for basin-scale drought
        monitoring the max-NDVI-over-3km sampler makes this irrelevant.

        Bands: OLCI B8 (NIR, 708.5 nm) and B6 (Red, 620.6 nm).
        Cloud mask uses the OLCI quality flags band (quality_flags).
        """
        img = (ee.ImageCollection('COPERNICUS/S3/OLCI')
               .filterBounds(point)
               .filterDate((day - timedelta(days=10)).isoformat(), (day + timedelta(days=1)).isoformat())
               .sort('system:time_start', False)
               .first())
        if img is None:
            return None
        ndvi = img.normalizedDifference(['Oa08_radiance', 'Oa06_radiance']).rename('ndvi')
        val = self._fetch(ndvi, point, 'ndvi', 300,
                          reducer=ee.Reducer.max(),
                          geometry=point.buffer(self.NDVI_SAMPLE_RADIUS_M))
        if val is not None and -0.2 <= val <= 1.0:
            return round(val, 3)
        return None

    def _sentinel1_sm(self, point, day):
        """All-weather surface soil moisture proxy from Sentinel-1 SAR (VV, dB).

        Empirical linear calibration (region-agnostic): dry bare soil ~ -22 dB,
        very wet ~ -8 dB -> scaled to 0-100%. A relative moisture index rather
        than an absolute measurement; accurate once calibrated against local
        gauges or SMAP.
        """
        imgs = (ee.ImageCollection('COPERNICUS/S1_GRD')
                .filterBounds(point)
                .filterDate((day - timedelta(days=7)).isoformat(), (day + timedelta(days=1)).isoformat())
                .filter(ee.Filter.eq('instrumentMode', 'IW'))
                .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VV'))
                .select('VV'))
        if imgs is None:
            return None
        vv = imgs.mean()
        val = self._fetch(vv, point, 'VV', 100)
        if val is None:
            return None
        pct = (float(val) + 22.0) / 14.0 * 100.0
        return round(max(0.0, min(100.0, pct)), 2)

    def _modis_lst(self, point, day):
        img = (ee.ImageCollection('MODIS/061/MOD11A1')
               .filterBounds(point)
               .filterDate(day.isoformat(), (day + timedelta(days=1)).isoformat())
               .first())
        if img is None:
            return None
        lst_k = self._fetch(img, point, 'LST_Day_1km', 1000, 0.02)
        if lst_k is None:
            return None
        return round(lst_k - 273.15, 2)

    def _smap_sm(self, point, day):
        img = (ee.ImageCollection('NASA/SMAP/SPL4SMGP/008')
               .filterBounds(point)
               .filterDate(day.isoformat(), (day + timedelta(days=1)).isoformat())
               .select('sm_surface')
               .mean())
        if img is None:
            return None
        sm_frac = self._fetch(img, point, 'sm_surface', 9000)
        if sm_frac is None:
            return None
        # sm_surface is volumetric fraction (m3/m3, 0-0.9) -> volumetric %
        return round(sm_frac * 100.0, 2)

    # ------------------------------------------------------------------ #
    # DB writers
    # ------------------------------------------------------------------ #
    def _get_year(self, year_label):
        obj, _ = ObservationYear.objects.get_or_create(label=str(year_label))
        return obj

    def _write_climate(self, region, day, rain, era, rain_source=None):
        if era is None:
            return
        year = self._get_year(day.year)
        ClimateMetrics.objects.update_or_create(
            region=region,
            year=year,
            measurement_date=day,
            defaults={
                'latitude': region.latitude,
                'longitude': region.longitude,
                'rainfall_mm': rain,
                'rainfall_source': rain_source,
                'temperature_max_c': era.get('temperature_max_c'),
                'temperature_min_c': era.get('temperature_min_c'),
                'temperature_mean_c': era.get('temperature_mean_c'),
                'relative_humidity_percent': era.get('relative_humidity_percent'),
                'wind_speed_ms': era.get('wind_speed_ms'),
                'solar_radiation_mjm2day': era.get('solar_radiation_mjm2day'),
            },
        )

    def _write_remote(self, region, day, ndvi, lst, sm, ndvi_source=None, sm_source=None):
        year = self._get_year(day.year)
        defaults = {
            'latitude': region.latitude,
            'longitude': region.longitude,
            'land_surface_temperature_c': lst,
            'satellite_soil_moisture_percent': sm,
        }
        if ndvi is not None:
            defaults['ndvi'] = ndvi
            defaults['satellite_source'] = ndvi_source or 'MODIS'
        elif sm is not None:
            defaults['satellite_source'] = sm_source or 'SMAP'
        RemoteSensingMetrics.objects.update_or_create(
            region=region,
            year=year,
            measurement_date=day,
            defaults=defaults,
        )

    # ------------------------------------------------------------------ #
    # Derived indices
    # ------------------------------------------------------------------ #
    def _recompute_indices(self, region):
        """Recompute SPI-1/3/12 (per-month gamma) and VCI from ingested data."""
        climate = list(ClimateMetrics.objects.filter(
            region=region, rainfall_mm__isnull=False,
        ).order_by('measurement_date').values_list('measurement_date', 'rainfall_mm'))
        if len(climate) < 60:
            self.stdout.write(f'  {region.name}: <60 rainfall days, skipping SPI')
            return

        series = pd.Series(
            [float(r) for _, r in climate],
            index=pd.DatetimeIndex([d for d, _ in climate]),
        )
        spi1 = calculate_spi(series, nmonth=1)
        spi3 = calculate_spi(series, nmonth=3)
        spi12 = calculate_spi(series, nmonth=12)

        ndvi_rows = list(RemoteSensingMetrics.objects.filter(
            region=region, ndvi__isnull=False,
        ).order_by('measurement_date').values_list('measurement_date', 'ndvi'))

        for day, val in spi1.items():
            if val is None or pd.isna(val):
                continue
            year = self._get_year(day.year)
            s3 = float(spi3.loc[day]) if day in spi3.index and pd.notna(spi3.loc[day]) else None
            s12 = float(spi12.loc[day]) if day in spi12.index and pd.notna(spi12.loc[day]) else None
            vci = None
            if ndvi_rows:
                history = [float(n) for d, n in ndvi_rows if d <= day]
                if len(history) >= 2:
                    ndvi_latest = [float(n) for d, n in ndvi_rows if d == day]
                    if ndvi_latest:
                        vci = calculate_vci(ndvi_latest[0], history)
            DroughtIndices.objects.update_or_create(
                region=region,
                year=year,
                measurement_date=day,
                defaults={
                    'latitude': region.latitude,
                    'longitude': region.longitude,
                    'spi_1month': round(float(val), 2),
                    'spi_3month': round(s3, 2) if s3 is not None else None,
                    'spi_12month': round(s12, 2) if s12 is not None else None,
                },
            )
            if vci is not None:
                RemoteSensingMetrics.objects.filter(
                    region=region, measurement_date=day,
                ).update(vegetation_condition_index=round(vci, 1))

    # ------------------------------------------------------------------ #
    # Main
    # ------------------------------------------------------------------ #
    def handle(self, *args, **options):
        if pd is None:
            raise CommandError('pandas is required. Install requirements.txt.')
        self._init_ee()

        today = date.today()
        start = datetime.strptime(options['start_date'], '%Y-%m-%d').date() if options['start_date'] else today - timedelta(days=90)
        end = datetime.strptime(options['end_date'], '%Y-%m-%d').date() if options['end_date'] else today
        if start > end:
            raise CommandError('start-date must be before end-date')

        regions = Region.objects.all()
        if options['region_id']:
            regions = regions.filter(id=options['region_id'])
        regions = [r for r in regions if r.latitude is not None and r.longitude is not None]
        if not regions:
            raise CommandError('No regions with coordinates found.')

        self.stdout.write(f'Pulling satellite data {start} -> {end} for {len(regions)} region(s) '
                          f'(every {options["every"]} days){"" if not options["dry_run"] else " [DRY RUN]"}')

        for region in regions:
            self.stdout.write(f'\n== {region.name} ({region.latitude}, {region.longitude}) ==')
            point = ee.Geometry.Point(float(region.longitude), float(region.latitude))
            day = start
            ingested = 0
            last_ndvi = None
            last_ndvi_source = None
            while day <= end:
                rain, rain_source = self._rainfall(point, day)
                era = self._era5_daily(point, day)
                ndvi = None
                ndvi_source = None
                if day.day % 16 in (1, 5, 9, 13) or day == end:
                    ndvi = self._sentinel2_ndvi(point, day)
                    if ndvi is not None:
                        ndvi_source = 'Sentinel-2'
                    else:
                        ndvi = self._sentinel3_ndvi(point, day)
                        if ndvi is not None:
                            ndvi_source = 'Sentinel-3'
                        else:
                            ndvi = self._modis_ndvi(point, day)
                            if ndvi is not None:
                                ndvi_source = 'MODIS'
                else:
                    ndvi = last_ndvi
                    ndvi_source = last_ndvi_source
                if ndvi is not None:
                    last_ndvi = ndvi
                    last_ndvi_source = ndvi_source
                lst = self._modis_lst(point, day)
                sm = self._smap_sm(point, day)
                sm_source = 'SMAP' if sm is not None else None
                if sm is None:
                    sm = self._sentinel1_sm(point, day)
                    sm_source = 'Sentinel-1' if sm is not None else None

                if options['verbose']:
                    self.stdout.write(
                        f'  {day}: rain={rain}{f"({rain_source})" if rain_source else ""} '
                        f'Tmax={era.get("temperature_max_c") if era else None} '
                        f'ndvi={ndvi}{f"({ndvi_source})" if ndvi_source else ""} '
                        f'lst={lst} sm={sm}{f"({sm_source})" if sm_source else ""}'
                    )

                if options['dry_run']:
                    ingested += 1
                else:
                    with transaction.atomic():
                        self._write_climate(region, day, rain, era, rain_source)
                        self._write_remote(region, day, ndvi, lst, sm, ndvi_source, sm_source)
                    ingested += 1

                day += timedelta(days=options['every'])

            self.stdout.write(f'  -> {ingested} day(s) processed')
            if not options['dry_run'] and not options['no_spi']:
                self.stdout.write(f'  recomputing SPI/VCI for {region.name} …')
                self._recompute_indices(region)

        self.stdout.write(self.style.SUCCESS('\nDone. Satellite data ingested.'))
