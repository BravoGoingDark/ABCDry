"""Fill SoilMetrics from ISRIC SoilGrids 2.0 (250 m, global, no API key).

Queries the REST point endpoint for every region centre / sample point and
stores the 0-30 cm depth-weighted mean of sand, silt, clay, pH(H2O) and
organic matter, plus field capacity / wilting point from the project's
pedotransfer functions. Salinity (ECe) is not in SoilGrids and stays empty.

    python manage.py fetch_soilgrids
    python manage.py fetch_soilgrids --region 4

SoilGrids is a modelled product with large local uncertainty; field samples
entered through the metrics form should take precedence.
"""
import datetime as dt
import time

import requests
from django.core.management.base import BaseCommand

from dashboard.models import ObservationYear, Region, SoilMetrics
from dashboard.prediction_engine.physical_helpers import (
    calculate_field_capacity, calculate_wilting_point)
from dashboard.services.soilgrids import fetch_point


class Command(BaseCommand):
    help = 'Fetch 0-30 cm soil properties from SoilGrids 2.0 into SoilMetrics.'

    def add_arguments(self, parser):
        parser.add_argument('--region', type=int, help='Region id (default: all with coordinates)')

    def handle(self, *args, **options):
        regions = Region.objects.exclude(latitude__isnull=True)
        if options.get('region'):
            regions = regions.filter(id=options['region'])
        today = dt.date.today()
        year, _ = ObservationYear.objects.get_or_create(label=str(today.year))

        for region in regions:
            if region.sample_points:
                points = [(float(p['lat']), float(p['lon'])) for p in region.sample_points]
            else:
                points = [(float(region.latitude), float(region.longitude))]
            for lat, lon in points:
                try:
                    soil = fetch_point(lat, lon)
                except (requests.RequestException, KeyError, ValueError) as exc:
                    self.stderr.write(f'{region.name} ({lat}, {lon}): {exc}')
                    continue
                if soil is None:
                    self.stderr.write(f'{region.name} ({lat}, {lon}): no SoilGrids data (water/urban?)')
                    continue
                fc = wp = None
                if None not in (soil['sand'], soil['clay'], soil['silt']):
                    fc = calculate_field_capacity(soil['sand'], soil['clay'], soil['silt'], soil['om'] or 0)
                    wp = calculate_wilting_point(soil['sand'], soil['clay'], soil['silt'])

                def r(v, n=2):
                    return None if v is None else round(v, n)

                SoilMetrics.objects.update_or_create(
                    region=region, year=year, measurement_date=today,
                    latitude=round(lat, 6), longitude=round(lon, 6),
                    defaults={
                        'sand_ratio': r(soil['sand']), 'silt_ratio': r(soil['silt']),
                        'clay_ratio': r(soil['clay']), 'ph_level': r(soil['ph'], 1),
                        'organic_matter_percent': r(soil['om']),
                        'field_capacity_percent': r(fc), 'wilting_point_percent': r(wp),
                    })
                self.stdout.write(self.style.SUCCESS(
                    f"{region.name} ({lat:.3f}, {lon:.3f}): sand {soil['sand']:.0f}% "
                    f"clay {soil['clay']:.0f}% pH {soil['ph']:.1f}"))
                time.sleep(12)  # SoilGrids fair-use limit: 5 requests/min
