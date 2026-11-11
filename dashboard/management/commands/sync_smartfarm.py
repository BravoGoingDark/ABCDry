"""Pull the SmartFarm soil probe's readings into the database.

    python manage.py sync_smartfarm            # last 120 days
    python manage.py sync_smartfarm --days 365
    python manage.py sync_smartfarm --check    # validate credentials only

Needs SMARTFARM_EMAIL and SMARTFARM_PASSWORD (or SMARTFARM_UID +
SMARTFARM_REFRESH_TOKEN) in the environment; see .env.example.
"""
import requests
from django.core.management.base import BaseCommand, CommandError

from dashboard.services import smartfarm


class Command(BaseCommand):
    help = 'Sync soil moisture and temperature readings from the SmartFarm probe.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=120)
        parser.add_argument('--check', action='store_true', help='Only check the credentials.')

    def handle(self, *args, days, check, **opts):
        creds = smartfarm.credentials()
        missing = smartfarm.missing_settings(creds)
        if missing:
            raise CommandError(f"Not configured; set {' and '.join(missing)} in .env")
        problem = smartfarm.credential_problem(creds)
        if problem:
            raise CommandError(problem)
        if check:
            try:
                smartfarm._access_token(force=True)
                sensors = smartfarm._get('/sensor/sensors') or []
            except (smartfarm.SmartFarmError, requests.RequestException) as exc:
                raise CommandError(str(exc))
            self.stdout.write(self.style.SUCCESS('Signed in to SmartFarm. Sensors on this account:'))
            for s in sensors:
                field = (s.get('fields') or {}).get('name') or '-'
                self.stdout.write(f"  {s.get('code')}  field: {field}  status: {s.get('etat')}")
            return
        try:
            out = smartfarm.sync(max(1, min(days, 730)))
        except (smartfarm.SmartFarmError, requests.RequestException) as exc:
            raise CommandError(str(exc))
        self.stdout.write(self.style.SUCCESS(
            f"Sensor #{out['sensor_id']}: {out['fetched']} readings fetched, {out['added']} new."))
