"""
Repair known satellite-data quality issues found during the audit:

  1. --fix-soil-moisture: SMAP `sm_surface` is volumetric fraction (m3/m3),
     but the original pull stored it as if it were kg/m2 (value * 2). The
     correct volumetric percent is value * 100, so previously stored SMAP
     values are ~50x too small. This multiplies SMAP-sourced rows by 50
     (idempotent: only touches values <= 5, which are the mis-scaled ones).

  2. --clear-water-ndvi: wetland sample points can sit on open water, where
     NDVI is ~ -0.1 (not vegetation). Values below 0.1 are treated as
     non-vegetation and set to NULL so they cannot poison the model or the
     vegetation-stress drivers. (Genuine healthy vegetation NDVI >= 0.1.)

  3. --re-pull-ndvi: re-fetch NDVI with the corrected basin sampler (max NDVI
     within a 3 km radius instead of the bare point) from Google Earth Engine
     and update the rows. Requires Earth Engine auth
     (`earthengine authenticate` or GEE_CREDENTIALS_FILE).

Usage:
  python manage.py repair_satellite --region-id 4 --fix-soil-moisture
  python manage.py repair_satellite --region-id 4 --clear-water-ndvi
  python manage.py repair_satellite --region-id 4 --re-pull-ndvi --start-date 2015-01-01
"""
from datetime import date, datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from dashboard.models import ObservationYear, Region, RemoteSensingMetrics
from dashboard.prediction_engine.physical_helpers import calculate_vci

try:
    import ee
    HAS_EE = True
except ImportError:  # pragma: no cover
    ee = None
    HAS_EE = False


class Command(BaseCommand):
    help = 'Repair known satellite data quality issues (SMAP units, water-NDVI, basin NDVI re-pull).'

    def add_arguments(self, parser):
        parser.add_argument('--region-id', type=int, required=True)
        parser.add_argument('--start-date', type=str, default=None, help='YYYY-MM-DD (default: 2015-01-01)')
        parser.add_argument('--end-date', type=str, default=None, help='YYYY-MM-DD (default: today)')
        parser.add_argument('--fix-soil-moisture', action='store_true',
                            help='Rescale SMAP soil moisture from the mis-scaled value to true volumetric %.')
        parser.add_argument('--clear-water-ndvi', action='store_true',
                            help='Set NDVI < 0.1 to NULL (open-water pixels are not vegetation).')
        parser.add_argument('--re-pull-ndvi', action='store_true',
                            help='Re-fetch NDVI with the basin sampler from Google Earth Engine.')
        parser.add_argument('--dry-run', action='store_true')

    # ------------------------------------------------------------------ #
    # Helpers (mirror pull_satellite.py so the corrected logic is shared)
    # ------------------------------------------------------------------ #
    def _init_ee(self):
        if not HAS_EE:
            raise CommandError('The earthengine-api package is not installed. Run: pip install earthengine-api')
        creds_file = __import__('os').getenv('GEE_CREDENTIALS_FILE') or __import__('os').getenv('GOOGLE_APPLICATION_CREDENTIALS')
        try:
            if creds_file and __import__('os').path.exists(creds_file):
                import json as _json
                import os as _os
                from google.oauth2 import service_account
                project = _os.getenv('GEE_PROJECT')
                if not project:
                    with open(creds_file) as cj:
                        project = _json.load(cj).get('project_id')
                credentials = service_account.Credentials.from_service_account_file(
                    creds_file,
                    scopes=['https://www.googleapis.com/auth/earthengine.readonly'],
                )
                if project:
                    ee.Initialize(credentials, project=project)
                else:
                    ee.Initialize(credentials)
            else:
                ee.Initialize()
        except Exception as exc:
            raise CommandError(
                'Earth Engine auth failed. Run `earthengine authenticate` (interactive) or set '
                'GEE_CREDENTIALS_FILE / GOOGLE_APPLICATION_CREDENTIALS to a service-account JSON.\n'
                f'Details: {exc}'
            )

    def _fetch_max_ndvi(self, image, point, band, scale, factor=1.0):
        import threading

        box = {}

        def runner():
            try:
                box['value'] = image.reduceRegion(
                    reducer=ee.Reducer.max(),
                    geometry=point.buffer(3000),
                    scale=scale,
                    bestEffort=True,
                ).get(band).getInfo()
            except Exception:
                box['error'] = True

        for _ in range(2):
            t = threading.Thread(target=runner, daemon=True)
            t.start()
            t.join(60)
            if 'value' in box:
                value = box['value']
                if value is None or value == -9999:
                    return None
                return float(value) * factor
        return None

    def _basin_ndvi(self, point, day):
        try:
            img_s2 = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                      .filterBounds(point)
                      .filterDate((day - timedelta(days=15)).isoformat(), (day + timedelta(days=1)).isoformat())
                      .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 30))
                      .sort('system:time_start', False)
                      .first())
            if img_s2 is not None:
                ndvi = img_s2.normalizedDifference(['B8', 'B4']).rename('ndvi')
                val = self._fetch_max_ndvi(ndvi, point, 'ndvi', 10)
                if val is not None and -0.2 <= val <= 1.0:
                    return round(val, 3), 'Sentinel-2'
        except Exception:
            pass

        try:
            img_m = (ee.ImageCollection('MODIS/061/MOD13Q1')
                     .filterBounds(point)
                     .filterDate((day - timedelta(days=24)).isoformat(), (day + timedelta(days=1)).isoformat())
                     .sort('system:time_start', False)
                     .first())
            if img_m is not None:
                val = self._fetch_max_ndvi(img_m, point, 'NDVI', 250, 0.0001)
                if val is not None and -0.2 <= val <= 1.0:
                    return round(val, 3), 'MODIS'
        except Exception:
            pass
        return None, None

    def _recompute_vci(self, region):
        rows = list(RemoteSensingMetrics.objects.filter(
            region=region, ndvi__isnull=False,
        ).order_by('measurement_date'))
        history = []
        updated = 0
        for obj in rows:
            if len(history) >= 2:
                vci = calculate_vci(float(obj.ndvi), history)
                if vci is not None and obj.vegetation_condition_index != vci:
                    obj.vegetation_condition_index = vci
                    obj.save(update_fields=['vegetation_condition_index'])
                    updated += 1
            history.append(float(obj.ndvi))
        return updated

    # ------------------------------------------------------------------ #
    # Main
    # ------------------------------------------------------------------ #
    def handle(self, *args, **options):
        region = Region.objects.filter(pk=options['region_id']).first()
        if region is None:
            raise CommandError(f'Region {options["region_id"]} not found.')

        start = datetime.strptime(options['start_date'], '%Y-%m-%d').date() if options['start_date'] else date(2015, 1, 1)
        end = datetime.strptime(options['end_date'], '%Y-%m-%d').date() if options['end_date'] else date.today()

        self.stdout.write(f'== Repairing satellite data for {region.name} (id={region.id}) ==')

        if options['fix_soil_moisture']:
            # The satellite_source tag is unreliable (days with NDVI carry the
            # NDVI source even though moisture came from SMAP), so detect the
            # mis-scaled rows by VALUE: the bug stored sm_surface (m3/m3, 0-1)
            # as value*2, i.e. 0.1-0.7. True volumetric % is 7-35. Any value
            # <= 5 is therefore the mis-scaled one; x50 makes it correct and
            # is idempotent (corrected values are > 5).
            qs = RemoteSensingMetrics.objects.filter(
                region=region,
                satellite_soil_moisture_percent__isnull=False,
                satellite_soil_moisture_percent__lte=5.0,
            ).exclude(satellite_source='Sentinel-1')
            n = qs.count()
            self.stdout.write(f'  SMAP soil moisture rows to rescale (x50): {n}')
            if not options['dry_run']:
                with transaction.atomic():
                    for obj in qs:
                        obj.satellite_soil_moisture_percent = round(float(obj.satellite_soil_moisture_percent) * 50.0, 2)
                        obj.save(update_fields=['satellite_soil_moisture_percent'])
                self.stdout.write(self.style.SUCCESS('  Done rescaling SMAP soil moisture.'))

        if options['clear_water_ndvi']:
            qs = RemoteSensingMetrics.objects.filter(
                region=region,
                ndvi__isnull=False,
                ndvi__lt=0.1,
            )
            n = qs.count()
            self.stdout.write(f'  Water-like NDVI rows to set NULL (< 0.1): {n}')
            if not options['dry_run']:
                with transaction.atomic():
                    for obj in qs:
                        obj.ndvi = None
                        obj.save(update_fields=['ndvi'])
                self.stdout.write(self.style.SUCCESS('  Done clearing water-like NDVI.'))

        if options['re_pull_ndvi']:
            self._init_ee()
            if region.latitude is None or region.longitude is None:
                raise CommandError('Region has no coordinates.')
            point = ee.Geometry.Point(float(region.longitude), float(region.latitude))
            day = start
            updated = 0
            while day <= end:
                ndvi, source = self._basin_ndvi(point, day)
                if ndvi is not None:
                    year, _ = ObservationYear.objects.get_or_create(label=str(day.year))
                    if not options['dry_run']:
                        RemoteSensingMetrics.objects.update_or_create(
                            region=region,
                            year=year,
                            measurement_date=day,
                            defaults={'ndvi': ndvi, 'satellite_source': source},
                        )
                    updated += 1
                day += timedelta(days=4)
            self.stdout.write(self.style.SUCCESS(f'  Re-pulled NDVI for {updated} days (basin sampler).'))
            if not options['dry_run']:
                vci_updated = self._recompute_vci(region)
                self.stdout.write(self.style.SUCCESS(f'  Recomputed VCI: {vci_updated} rows updated.'))

        self.stdout.write(self.style.SUCCESS('\nRepair complete.'))
