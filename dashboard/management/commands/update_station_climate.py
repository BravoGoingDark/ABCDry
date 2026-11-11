"""Continue the two Ichkeul stations' daily climate from open data (ERA5-Land + CHIRPS via Earth Engine).

    python manage.py update_station_climate --calibrate     # once: fit corrections on 2016-2025
    python manage.py update_station_climate                 # new / provisional days up to today
    python manage.py update_station_climate --start 2026-01-01 --end 2026-03-31
    python manage.py update_station_climate --dry-run

Fills rainfall, mean/min/max temperature, humidity, wind at 2 m, solar
radiation and FAO-56 ET0 for both stations (see services/station_climate).
Needs GEE_CREDENTIALS_FILE.
"""
import datetime as dt

from django.core.management.base import BaseCommand, CommandError

from dashboard.services import station_climate as sc


class Command(BaseCommand):
    help = 'Download and store daily climate for the two Ichkeul stations (ERA5-Land + CHIRPS).'

    def add_arguments(self, parser):
        parser.add_argument('--calibrate', action='store_true',
                            help='Fit the per-station corrections on the dataset overlap before updating.')
        parser.add_argument('--start', type=dt.date.fromisoformat)
        parser.add_argument('--end', type=dt.date.fromisoformat)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, calibrate, start, end, dry_run, **opts):
        try:
            if calibrate:
                self.stdout.write('Fitting corrections on the 2016-2025 overlap (a few minutes)...')
                cal = sc.calibrate()
                for key, st in cal['stations'].items():
                    errs = ', '.join(f"{k} {v['raw']}->{v['corrected']}" for k, v in st['test_mae'].items())
                    self.stdout.write(f"  {st['lat']}, {st['lon']}: test error 2024-2025 (raw->corrected) {errs}")
            summary = sc.update(start=start, end=end, dry_run=dry_run, log=self.stdout.write)
        except sc.StationClimateError as exc:
            raise CommandError(str(exc))
        for st in sc.STATIONS:
            s = summary[st['key']]
            self.stdout.write(self.style.SUCCESS(f"{st['lat']}, {st['lon']}: {s}"))
