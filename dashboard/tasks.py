import logging

from celery import shared_task
from django.core.management import call_command

logger = logging.getLogger(__name__)


@shared_task
def refresh_materialized_views():
    """Refresh TimescaleDB materialized views (Postgres only)."""
    from django.db import connection

    if connection.vendor != 'postgresql':
        return 'No materialized views to refresh (non-Postgres backend).'

    materialized_views = []
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT matviewname FROM pg_matviews")
            materialized_views = [row[0] for row in cursor.fetchall()]
    except Exception as exc:  # pragma: no cover
        logger.warning('Could not list materialized views: %s', exc)
        return 'Could not list materialized views.'

    refreshed = []
    for view in materialized_views:
        try:
            with connection.cursor() as cursor:
                cursor.execute(f'REFRESH MATERIALIZED VIEW CONCURRENTLY "{view}"')
            refreshed.append(view)
        except Exception as exc:  # pragma: no cover
            logger.warning('Refresh failed for %s: %s', view, exc)
    return f'Refreshed: {refreshed}'


@shared_task
def generate_daily_risk_assessments():
    """Generate + store today's risk prediction for every region (no LLM)."""
    from dashboard.models import ObservationYear, Region
    from dashboard.prediction_engine.pipeline import DroughtPredictionPipeline

    from django.utils import timezone
    year = (ObservationYear.objects.filter(label=str(timezone.localdate().year)).first()
            or ObservationYear.objects.order_by('-label').first())
    if year is None:
        return 'No observation years found.'

    pipeline = DroughtPredictionPipeline()
    saved_ids = []
    for region in Region.objects.all():
        try:
            result = pipeline.predict_for_region(region, year, use_llm=False)
            saved = pipeline.save_prediction(region, year, result, source_window_days=120)
            saved_ids.append(saved.id)
        except Exception as exc:  # pragma: no cover
            logger.warning('Daily prediction failed for %s: %s', region, exc)
    return f'Generated predictions: {saved_ids}'


@shared_task
def pull_satellite_and_retrain():
    """Daily pipeline: ingest recent satellite data, recompute SPI, retrain, predict."""
    call_command('pull_satellite', '--every', '5')
    call_command('retrain_models')
    return 'Pull + retrain complete.'


@shared_task
def validate_spi_forecast():
    """Re-run SPI-3 forecast backtests so warning confidence stays fresh."""
    call_command('validate_spi_forecast', '--horizon', '7')
    call_command('validate_spi_forecast', '--horizon', '30')
    return 'SPI forecast backtests complete.'


@shared_task
def monthly_spei_forecast():
    """Monthly: refresh climate + satellite data for all regions, retrain
    pooled SPEI models, refresh per-region forecasts, then verify mature
    predictions against observed SPEI (live scoreboard)."""
    from django.core.management import call_command

    # 1) Data refresh: monthly CHIRPS + ERA5-Land climate rows and monthly
    #    MODIS/SMAP remote-sensing rows for every region (complete months
    #    only; ECMWF/CHIRPS embargo handled inside the commands).
    call_command('backfill_climate_monthly')
    call_command('backfill_rs_monthly')
    # 2) Model refresh + forecasts + verification
    call_command('train_spei_pooled')
    call_command('verify_spei_forecasts')
    # 2b) Gridded 29-cell Ichkeul forecast (incremental fetch, re-verify, publish)
    try:
        call_command('build_drought_grid')
    except Exception:
        logger.warning('Gridded drought forecast build failed', exc_info=True)
    # 3) Pre-warm assistant answers (all regions x intents x languages)
    try:
        from dashboard.services.farmer_assistant import prewarm_answers
        n = prewarm_answers()
        logger.info('Assistant pre-warm: %s answers cached', n)
    except Exception:
        logger.warning('Assistant pre-warm failed', exc_info=True)
    return 'Monthly SPEI forecast + verification complete.'


@shared_task
def sync_smartfarm_probe():
    """Pull new readings from the SmartFarm soil probe (reports ~once a day)."""
    from dashboard.services import smartfarm

    if not smartfarm.configured():
        return 'SmartFarm not configured.'
    out = smartfarm.sync(days=14)
    return f"SmartFarm: {out['added']} new readings."


@shared_task
def update_station_climate():
    """Continue the two Ichkeul stations' daily climate (ERA5-Land + CHIRPS via Earth Engine).

    Daily: ERA5-Land arrives ~1 week late and CHIRPS ~5-6 weeks late; each run
    adds the new days and swaps provisional IMERG rain for CHIRPS once published.
    """
    from dashboard.services import station_climate

    summary = station_climate.update()
    return f'Station climate: {summary}'
