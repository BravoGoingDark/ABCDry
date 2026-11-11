"""Fetch per-cell climate, verify and publish the gridded SPEI drought forecast.

    python manage.py build_drought_grid                 # incremental fetch + verify + forecast
    python manage.py build_drought_grid --no-fetch      # rebuild from stored data
    python manage.py build_drought_grid --no-verify     # reuse the last skill table (fast)

Run monthly, after CHIRPS publishes the previous month (usually mid-month).
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from dashboard.models import DroughtGridForecast, GridCellClimate
from dashboard.prediction_engine import drought_grid as dg

K = 273.15


def _month_list(start: date, end: date):
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f'{y}-{m:02d}-01')
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


class Command(BaseCommand):
    help = 'Build the 29-cell Ichkeul SPEI drought forecast (CHIRPS + ERA5-Land, ridge, walk-forward verified).'

    def add_arguments(self, parser):
        parser.add_argument('--no-fetch', action='store_true', help='Use stored cell data only')
        parser.add_argument('--refetch-months', type=int, default=3,
                            help='Re-download the last N stored months (CHIRPS revisions)')
        parser.add_argument('--no-verify', action='store_true',
                            help='Reuse the skill table of the previous run')

    def handle(self, *args, **opts):
        log = lambda s: self.stdout.write(s)
        if not opts['no_fetch']:
            self._fetch(opts['refetch_months'], log)

        records = list(GridCellClimate.objects.values(
            'cell', 'month', 'precip_mm', 'tmax_c', 'tmin_c', 'tmean_c', 'tdew_c',
            'wind_ms', 'solar_mj', 'soil_moisture'))
        if not records:
            raise CommandError('No grid cell data stored; run without --no-fetch first.')

        prev = DroughtGridForecast.objects.first()
        log('Verifying (expanding window) and forecasting...' if not opts['no_verify'] else 'Forecasting...')
        # Runs published with the scenario ensemble keep the ridge table in `skill_ridge`.
        payload = dg.run(records,
                         previous_skill=(prev.payload.get('skill_ridge') or prev.payload.get('skill')) if prev else None,
                         do_verify=not opts['no_verify'], log=log,
                         previous_scenario_skill=((prev.payload.get('scenarios') or {}).get('skill')
                                                  if prev else None))
        issue = date.fromisoformat(payload['issue_month'])
        DroughtGridForecast.objects.update_or_create(
            issue_month=issue, defaults={'payload': payload, 'model_version': payload['model_version']})
        skilful = {k: max([h for h in dg.LEADS if payload['skill'][f'{k}_{h}']['skilful']], default=0)
                   for k in dg.SCALES}
        log(self.style.SUCCESS(
            f'Published forecast issued {issue:%Y-%m}. Skilful lead (months): '
            + ', '.join(f'SPEI-{k}: {v}' for k, v in skilful.items())))

    def _fetch(self, refetch, log):
        from dashboard.management.commands.backfill_climate_monthly import Command as Backfill
        import ee
        Backfill()._init_ee()

        end = dg.last_complete_chirps_month(ee)
        last = GridCellClimate.objects.order_by('-month').values_list('month', flat=True).first()
        if last:
            y, m = last.year, last.month - refetch + 1
            while m < 1:
                y, m = y - 1, m + 12
            start = date(y, m, 1)
        else:
            start = date(dg.REF_START, 1, 1)
        months = _month_list(start, end)
        if not months:
            log('Cell data already up to date.')
            return
        log(f'Fetching {len(months)} month(s) x 29 cells ({months[0][:7]} -> {months[-1][:7]}) from Earth Engine...')
        rows = dg.fetch_cell_months(ee, months, log=log)

        def c(v):
            return None if v is None else float(v) - K

        objs = []
        for r in rows:
            u, v = r.get('u_component_of_wind_10m'), r.get('v_component_of_wind_10m')
            sm1, sm2 = r.get('volumetric_soil_water_layer_1'), r.get('volumetric_soil_water_layer_2')
            ssrd = r.get('surface_solar_radiation_downwards_sum')
            objs.append(GridCellClimate(
                cell=r['cell'], month=date.fromisoformat(r['month']),
                precip_mm=r.get('chirps'),
                tmax_c=c(r.get('temperature_2m_max')),
                tmin_c=c(r.get('temperature_2m_min')),
                tmean_c=c(r.get('temperature_2m')),
                tdew_c=c(r.get('dewpoint_temperature_2m')),
                wind_ms=(u ** 2 + v ** 2) ** 0.5 if None not in (u, v) else None,
                solar_mj=ssrd * 1e-6 if ssrd is not None else None,
                soil_moisture=(sm1 + sm2) / 2 if None not in (sm1, sm2) else None,
            ))
        with transaction.atomic():
            GridCellClimate.objects.bulk_create(
                objs, batch_size=1000, update_conflicts=True, unique_fields=['cell', 'month'],
                update_fields=['precip_mm', 'tmax_c', 'tmin_c', 'tmean_c', 'tdew_c',
                               'wind_ms', 'solar_mj', 'soil_moisture'])
        log(f'Stored {len(rows)} cell-months.')
