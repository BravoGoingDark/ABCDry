"""Backfill historical monthly climate data for all regions via Google Earth Engine.

Fetches, per region and per calendar month:
  - CHIRPS rainfall      (UCSB-CHG/CHIRPS/DAILY, from 1981)  -> monthly sum (mm)
  - ERA5-Land climate    (ECMWF/ERA5_LAND/DAILY_AGGR)        -> monthly means of
    Tmax/Tmin/Tmean, dewpoint -> RH, u/v wind -> speed, ssrd -> solar radiation
  - ET0 computed with FAO-56 Penman-Monteith from those monthly means

One row per (region, month) is written into ClimateMetrics with
measurement_date = first day of the month (daily-schema compatible: monthly
resampling downstream yields correct monthly totals/means).

All months of a chunk are computed server-side and fetched in ONE getInfo
call, so a 45-year backfill per region costs ~5 requests.

Usage:
    python manage.py backfill_climate_monthly                     # all regions, 1981 -> now
    python manage.py backfill_climate_monthly --region-id 5       # one region
    python manage.py backfill_climate_monthly --dry-run
"""
import math
import os
from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from dashboard.models import ClimateMetrics, ObservationYear, Region
from dashboard.prediction_engine.physical_helpers import calculate_et0

try:
    import ee
    HAS_EE = True
except ImportError:  # pragma: no cover
    ee = None
    HAS_EE = False


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
    help = 'Backfill monthly CHIRPS + ERA5-Land climate rows into ClimateMetrics.'

    def add_arguments(self, parser):
        parser.add_argument('--start', default='1981-01-01', help='First month YYYY-MM-DD')
        parser.add_argument('--end', default=None,
                            help='Last month (exclusive) YYYY-MM-DD; default: current month')
        parser.add_argument('--region-id', type=int, default=None)
        parser.add_argument('--include-ichkeul', action='store_true',
                            help='Also (re)fetch region 4, which already has daily data')
        parser.add_argument('--chunk-years', type=int, default=10,
                            help='Months are fetched in chunks of this many years')
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

    def _per_month_feature(self, ms, chirps, era, point):
        """Server-side: aggregate one month into a Feature (single getInfo for many)."""
        start = ee.Date(ms)
        end = start.advance(1, 'month')
        chirps_m = chirps.filterDate(start, end)
        rain = ee.Image(ee.Algorithms.If(
            chirps_m.size().gt(0),
            chirps_m.sum().rename('rain'),
            ee.Image.constant(-9999).rename('rain'),
        ))
        era_m = era.filterDate(start, end)
        img = rain.addBands([
            era_m.select('temperature_2m_max').mean(),
            era_m.select('temperature_2m_min').mean(),
            era_m.select('temperature_2m').mean(),
            era_m.select('dewpoint_temperature_2m').mean(),
            era_m.select('u_component_of_wind_10m').mean(),
            era_m.select('v_component_of_wind_10m').mean(),
            era_m.select('surface_solar_radiation_downwards_sum').mean(),
        ])
        vals = img.reduceRegion(
            reducer=ee.Reducer.first(),
            geometry=point.buffer(11132),
            scale=11132,
            bestEffort=True,
        )
        return ee.Feature(None, {
            'month': ms,
            'rain': vals.get('rain'),
            'tmax': vals.get('temperature_2m_max'),
            'tmin': vals.get('temperature_2m_min'),
            'tmean': vals.get('temperature_2m'),
            'tdew': vals.get('dewpoint_temperature_2m'),
            'u': vals.get('u_component_of_wind_10m'),
            'v': vals.get('v_component_of_wind_10m'),
            'ssrd': vals.get('surface_solar_radiation_downwards_sum'),
        })

    @staticmethod
    def _kelvin_to_c(v):
        return None if v is None else round(float(v) - 273.15, 2)

    def _to_row(self, feat):
        """Convert one server-side Feature dict into a ClimateMetrics row dict."""
        p = feat['properties']
        y, m = p['month'].split('-')[:2]
        d = date(int(y), int(m), 1)

        def num(key, scale=1.0, digits=2):
            v = p.get(key)
            return None if v is None else round(float(v) * scale, digits)

        tmean = self._kelvin_to_c(p.get('tmean'))
        tmax = self._kelvin_to_c(p.get('tmax'))
        tmin = self._kelvin_to_c(p.get('tmin'))
        tdew = self._kelvin_to_c(p.get('tdew'))

        rh = None
        if tdew is not None and tmean is not None:
            es_t = 0.6108 * math.exp(17.27 * tmean / (tmean + 237.3))
            es_td = 0.6108 * math.exp(17.27 * tdew / (tdew + 237.3))
            if es_t > 0:
                rh = round(max(1.0, min(100.0, 100.0 * es_td / es_t)), 1)

        wind = None
        u, v = p.get('u'), p.get('v')
        if u is not None and v is not None:
            wind = round(math.sqrt(float(u) ** 2 + float(v) ** 2), 2)

        solar_mj = num('ssrd', 1e-6)  # J/m2/day mean -> MJ/m2/day
        et0 = None
        if None not in (tmean, wind, solar_mj, rh):
            solar_wm2 = solar_mj / 0.0864 if solar_mj > 0 else 0
            et0 = round(calculate_et0(tmean, wind, solar_wm2, rh), 2)

        rain_raw = p.get('rain')
        rainfall = None if rain_raw is None or float(rain_raw) <= -9998 else round(float(rain_raw), 2)

        return {
            'date': d,
            'rainfall_mm': rainfall,
            'temperature_max_c': tmax,
            'temperature_min_c': tmin,
            'temperature_mean_c': tmean,
            'relative_humidity_percent': rh,
            'wind_speed_ms': wind,
            'solar_radiation_mjm2day': solar_mj,
            'evapotranspiration_et0_mmday': et0,
        }

    def handle(self, *args, **options):
        self._init_ee()

        sy, sm, _ = [int(x) for x in options['start'].split('-')]
        if options['end']:
            ey, em, _ = [int(x) for x in options['end'].split('-')]
        else:
            # default: last COMPLETE month (a partial current month would bias SPEI)
            last_complete = date(date.today().year, date.today().month, 1) - timedelta(days=1)
            ey, em = last_complete.year, last_complete.month

        months = _month_starts(sy, sm, ey, em)
        chunk_size = max(1, options['chunk_years']) * 12

        regions = Region.objects.filter(latitude__isnull=False)
        if options['region_id']:
            regions = regions.filter(id=options['region_id'])
        elif options['include_ichkeul']:
            pass  # all regions incl. 4
        else:
            regions = regions.exclude(id=4)

        chirps = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').select('precipitation')
        era = ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR')

        for region in regions:
            lat, lon = float(region.latitude), float(region.longitude)
            self.stdout.write(f'{region.name} (id={region.id}) @ ({lat}, {lon}): '
                              f'{len(months)} months...')
            point = ee.Geometry.Point([lon, lat])

            total = 0
            for i in range(0, len(months), chunk_size):
                chunk = months[i:i + chunk_size]
                fc = ee.FeatureCollection(ee.List(chunk).map(
                    lambda ms: self._per_month_feature(ms, chirps, era, point)))
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
                        year_obj, _ = ObservationYear.objects.get_or_create(
                            label=str(row['date'].year))
                        ClimateMetrics.objects.update_or_create(
                            region=region,
                            year=year_obj,
                            measurement_date=row['date'],
                            latitude=lat,
                            longitude=lon,
                            defaults={
                                'rainfall_mm': row['rainfall_mm'],
                                'temperature_max_c': row['temperature_max_c'],
                                'temperature_min_c': row['temperature_min_c'],
                                'temperature_mean_c': row['temperature_mean_c'],
                                'relative_humidity_percent': row['relative_humidity_percent'],
                                'wind_speed_ms': row['wind_speed_ms'],
                                'solar_radiation_mjm2day': row['solar_radiation_mjm2day'],
                                'evapotranspiration_et0_mmday': row['evapotranspiration_et0_mmday'],
                                'rainfall_source': 'CHIRPS',
                            },
                        )
                total += len(rows)
                self.stdout.write(f'  chunk {chunk[0]}..{chunk[-1]}: {len(rows)} rows written')

            self.stdout.write(self.style.SUCCESS(f'  {region.name}: {total} monthly rows done'))
        self.stdout.write(self.style.SUCCESS('Climate backfill complete.'))
