"""Verify stored SPEI forecasts against observed SPEI (live scoreboard).

For every SpeiForecast whose target month has completed and whose observed
SPEI-3 exists in drought_indices, create/update a SpeiVerification row:
did the drought flag match reality, was the severity level exact?

Run monthly after generating new forecasts:
    python manage.py verify_spei_forecasts
    python manage.py verify_spei_forecasts --horizons 1 3

Only T+1 is verified by default. T+3 showed no out-of-sample skill
(classifier AUC 0.46, i.e. worse than chance), so it is excluded until it
demonstrates otherwise; scoring it would put a known-useless horizon on the
same scoreboard as a working one.
"""
import calendar
from datetime import date

from django.core.management.base import BaseCommand

from dashboard.models import DroughtIndices, SpeiForecast, SpeiVerification
from dashboard.services.assistant_brain import _normalise_level, _spei_level

DROUGHT_THRESHOLD = -0.5


def _month_end(d):
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def _observed_spei(region, target):
    """Mean observed SPEI-3 for a region over a month, or None.

    Matched on year+month rather than an exact date: measurement_date is
    declared a DateField but stored as a timestamp, so equality against a
    date object is not reliable. Multi-point regions are averaged, matching
    how the rest of the pipeline treats them.
    """
    rows = (DroughtIndices.objects
            .filter(region=region, spei_3month__isnull=False,
                    measurement_date__year=target.year,
                    measurement_date__month=target.month)
            .values_list('spei_3month', flat=True))
    values = [float(v) for v in rows if v is not None]
    if not values:
        return None
    return sum(values) / len(values), len(values)


class Command(BaseCommand):
    help = 'Verify mature SPEI forecasts against observed SPEI-3.'

    def add_arguments(self, parser):
        parser.add_argument('--horizons', default='1',
                            help='Comma-separated horizons to verify (default: 1)')

    def handle(self, *args, **options):
        horizons = tuple(int(h) for h in str(options['horizons']).split(',') if h.strip())

        # A target month is verifiable only once fully in the past, and the
        # observed SPEI-3 (target month + 2 prior months) must exist.
        today = date.today()
        cutoff = date(today.year, today.month, 1)

        created = already = pending = 0
        for fc in SpeiForecast.objects.select_related('region').all():
            targets = [(1, fc.target_month_t1)]
            if 3 in horizons:
                targets.append((3, fc.target_month_t3))

            for horizon, target in targets:
                if target is None or target >= cutoff:
                    continue
                if SpeiVerification.objects.filter(
                        region=fc.region, horizon=horizon,
                        target_month=target).exists():
                    already += 1
                    continue

                found = _observed_spei(fc.region, target)
                if found is None:
                    pending += 1
                    continue
                actual_spei, n_points = found

                # Both sides of the comparison must use ONE level vocabulary,
                # or level_exact is always False. Observed level is derived
                # from SPEI; predicted level is normalised from whatever
                # vocabulary the stored forecast used.
                actual_level = _spei_level(actual_spei)
                if horizon == 1:
                    predicted_spei = fc.spei_t1
                    predicted_prob = fc.prob_drought_t1
                    predicted_level = fc.level_t1
                else:
                    predicted_spei = fc.spei_t3
                    predicted_prob = fc.prob_drought_t3
                    predicted_level = fc.level_t3
                predicted_level = _normalise_level(predicted_level, None) or \
                    _spei_level(float(predicted_spei) if predicted_spei is not None else None)

                drought_actual = actual_spei < DROUGHT_THRESHOLD
                if predicted_prob is not None:
                    drought_predicted = predicted_prob >= 0.5
                else:
                    drought_predicted = predicted_spei is not None and \
                        float(predicted_spei) < DROUGHT_THRESHOLD

                SpeiVerification.objects.update_or_create(
                    region=fc.region,
                    horizon=horizon,
                    target_month=target,
                    defaults={
                        'forecast': fc,
                        'predicted_level': predicted_level,
                        'predicted_spei': predicted_spei,
                        'predicted_prob': predicted_prob,
                        'drought_predicted': drought_predicted,
                        'drought_actual': drought_actual,
                        'flag_correct': drought_predicted == drought_actual,
                        'level_exact': predicted_level == actual_level,
                        'actual_spei': round(actual_spei, 2),
                        'actual_level': actual_level,
                    },
                )
                self.stdout.write(
                    f'  {fc.region.name} T+{horizon} {target}: predicted '
                    f'{predicted_spei} ({predicted_level}) vs actual '
                    f'{actual_spei:.2f} ({actual_level})'
                    f'{" [averaged over %d points]" % n_points if n_points > 1 else ""}')
                created += 1

        total = SpeiVerification.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f'Verification complete: {created} new, {already} already verified, '
            f'{pending} awaiting an observed SPEI-3. {total} total.'))

        for horizon in horizons:
            rows = SpeiVerification.objects.filter(horizon=horizon)
            n = rows.count()
            if not n:
                self.stdout.write(self.style.WARNING(
                    f'T+{horizon}: nothing verifiable yet (no matured target month '
                    f'with an observed SPEI-3).'))
                continue
            hits = rows.filter(drought_actual=True)
            caught = hits.filter(flag_correct=True).count()
            missed = hits.filter(flag_correct=False).count()
            exact = rows.filter(level_exact=True).count()
            err = [abs(float(r.predicted_spei) - float(r.actual_spei))
                   for r in rows if r.predicted_spei is not None and r.actual_spei is not None]
            mae = sum(err) / len(err) if err else None
            self.stdout.write(self.style.SUCCESS(
                f'T+{horizon}: {n} verified | drought caught {caught}/{hits.count()}'
                f' (missed {missed}) | exact level {exact}/{n}'
                + (f' | SPEI MAE {mae:.3f}' if mae is not None else '')))
