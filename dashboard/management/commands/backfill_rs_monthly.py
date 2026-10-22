"""Backfill monthly remote-sensing features into RemoteSensingMetrics via GEE.

Per region and calendar month:
  - NDVI            MODIS/061/MOD13Q1  (16-day, 250 m, from 2000-02) -> monthly mean
  - LST (day, °C)   MODIS/061/MOD11A1  (daily, 1 km,   from 2000)    -> monthly mean
  - Soil moisture   NASA/SMAP/SPL4SMGP (0-5 cm, from 2015-03)       -> monthly mean, %

These are the land-memory features that give the T+3 SPEI forecast its only
genuine signal (vegetation/land-surface drought memory persists for months).

All months of a chunk are computed server-side and fetched in ONE getInfo call.

Usage:
    python manage.py backfill_rs_monthly                       # all regions, 2000-02 -> now
    python manage.py backfill_rs_monthly --region-id 4 --start 2024-01-01
"""
import os
from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from dashboard.models import ObservationYear, Region, RemoteSensingMetrics

try:
    import ee
    HAS_EE = True
except ImportError:  # pragma: no cover
    ee = None
    HAS_EE = False

SENTINEL = -9999.0


def _month_starts(start_year, start_month, end_year, end_month):
    out = []
    y, m = start_year, start_month
    while (y, m) <= (end_year, end_month):
        out.append('%04d-%02d-01' % (y, m))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


class Command(BaseCommand):
    help = 'Backfill monthly MODIS NDVI/LST + SMAP soil moisture rows.'

    def add_arguments(self, parser):
        parser.add_argument('--start', default='2000-02-01')
        parser.add_argument('--end', default=None,
                            help='Last month (exclusive); default: current month')
        parser.add_argument('--region-id', type=int, default=None)
        parser.add_argument('--chunk-years', type=int, default=8)
        parser.add_argument('--dry-run', action='store_true')

    def _init_ee(self):
        if not HAS_EE:
            raise CommandError('earthengine-api is not installed.')
        creds_file = os.getenv('GEE_CREDENTIALS_FILE') or os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
        try:
            if creds_file and os.path.exists(creds_file):
                import json as _json
                from google.oauth2 import service_account
                project = os.getenv('GEE_PROJECT')
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
                'Earth Engine auth failed. Set GEE_CREDENTIALS_FILE to a '
                f'service-account JSON.\nDetails: {exc}')

    def _per_month_feature(self, ms, modis_ndvi, modis_lst, smap, point):
        start = ee.Date(ms)
        end = start.advance(1, 'month')

        def monthly_mean(coll, band):
            filtered = coll.filterDate(start, end)
            return ee.Image(ee.Algorithms.If(
                filtered.size().gt(0),
                filtered.select(band).mean().unmask(SENTINEL).rename(band),
                ee.Image.constant(SENTINEL).rename(band),
            ))

        img = monthly_mean(modis_ndvi, 'NDVI').addBands([
            monthly_mean(modis_lst, 'LST_Day_1km'),
            monthly_mean(smap, 'sm_surface'),
        ])
        vals = img.reduceRegion(
            reducer=ee.Reducer.first(),
            geometry=point.buffer(1000),
            scale=1000,
            bestEffort=True,
        )
        return ee.Feature(None, {
            'month': ms,
            'ndvi': vals.get('NDVI'),
            'lst': vals.get('LST_Day_1km'),
            'sm': vals.get('sm_surface'),
        })

    @staticmethod
    def _sentinel_or_none(v, scale=1.0):
        if v is None:
            return None
        f = float(v)
        return None if f <= SENTINEL + 1 else round(f * scale, 4)

    def _to_row(self, feat):
        p = feat['properties']
        y, m = p['month'].split('-')[:2]
        d = date(int(y), int(m), 1)

        # NDVI: scaled DN -> -1..1
        ndvi = self._sentinel_or_none(p.get('ndvi'), 0.0001)
        # LST: raw DN * 0.02 = Kelvin -> Celsius
        lst_k = self._sentinel_or_none(p.get('lst'), 0.02)
        lst_c = None if lst_k is None else round(lst_k - 273.15, 2)
        # SMAP: volumetric m3/m3 -> percent
        sm = self._sentinel_or_none(p.get('sm'), 100.0)

        source = 'MODIS' if ndvi is not None else 'SMAP'
        return {
            'date': d,
            'ndvi': ndvi,
            'lst': lst_c,
            'sm': sm,
            'source': source,
        }

    def handle(self, *args, **options):
        self._init_ee()

        sy, sm_, _ = [int(x) for x in options['start'].split('-')]
        if options['end']:
            ey, em, _ = [int(x) for x in options['end'].split('-')]
        else:
            last_complete = date(date.today().year, date.today().month, 1) - timedelta(days=1)
            ey, em = last_complete.year, last_complete.month

        months = _month_starts(sy, sm_, ey, em)
        chunk_size = max(1, options['chunk_years']) * 12

        regions = Region.objects.filter(latitude__isnull=False)
        if options['region_id']:
            regions = regions.filter(id=options['region_id'])

        modis_ndvi = ee.ImageCollection('MODIS/061/MOD13Q1')
        modis_lst = ee.ImageCollection('MODIS/061/MOD11A1')
        smap = ee.ImageCollection('NASA/SMAP/SPL4SMGP/008')

        for region in regions:
            lat, lon = float(region.latitude), float(region.longitude)
            self.stdout.write(f'{region.name} (id={region.id}) @ ({lat}, {lon}): '
                              f'{len(months)} months...')
            point = ee.Geometry.Point([lon, lat])

            total = 0
            for i in range(0, len(months), chunk_size):
                chunk = months[i:i + chunk_size]
                fc = ee.FeatureCollection(ee.List(chunk).map(
                    lambda ms: self._per_month_feature(
                        ms, modis_ndvi, modis_lst, smap, point)))
                try:
                    feats = fc.getInfo().get('features', [])
                except Exception as exc:
                    self.stdout.write(self.style.WARNING(
                        f'  chunk {chunk[0]}..{chunk[-1]} failed: {exc}'))
                    continue

                rows = [self._to_row(f) for f in feats]
                if options['dry_run']:
                    self.stdout.write(f'  [dry-run] {len(rows)} rows; first: {rows[0] if rows else {}}')
                    total += len(rows)
                    continue

                with transaction.atomic():
                    for row in rows:
                        if all(v is None for v in (row['ndvi'], row['lst'], row['sm'])):
                            continue
                        year_obj, _ = ObservationYear.objects.get_or_create(
                            label=str(row['date'].year))
                        RemoteSensingMetrics.objects.update_or_create(
                            region=region,
                            year=year_obj,
                            measurement_date=row['date'],
                            latitude=lat,
                            longitude=lon,
                            defaults={
                                'ndvi': row['ndvi'],
                                'land_surface_temperature_c': row['lst'],
                                'satellite_soil_moisture_percent': row['sm'],
                                'satellite_source': row['source'],
                            },
                        )
                total += len(rows)
                self.stdout.write(f'  chunk {chunk[0]}..{chunk[-1]}: {len(rows)} rows')

            self.stdout.write(self.style.SUCCESS(f'  {region.name}: {total} monthly rows done'))
        self.stdout.write(self.style.SUCCESS('RS backfill complete.'))
