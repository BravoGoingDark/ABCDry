"""Train the SPEI + XGBoost drought-forecasting pipeline (T+1 / T+3 months).

Builds the monthly SPEI dataset from ClimateMetrics, trains XGBoost
regressors for SPEI-3 at T+1 and T+3, backfills the monthly SPEI history
into drought_indices, and persists the current outlook as a SpeiForecast.

Usage:
    python manage.py train_spei_models --region 4
"""
import json
import logging
import pickle
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from dashboard.models import DroughtIndices, ObservationYear, Region, SpeiForecast
from dashboard.prediction_engine.spei_features import (
    DECISION_RULE_PROVENANCE,
    DROUGHT_PROB_THRESHOLD,
    MAX_FORECAST_LAG_MONTHS,
    build_spei_dataset,
    drought_probability_band,
    drought_warning,
    get_recommendations,
    spei_to_risk,
    train_spei_models,
)

logger = logging.getLogger(__name__)

SPEI_COLUMN_BY_NMONTH = {1: 'spei_1month', 3: 'spei_3month', 12: 'spei_12month'}


def _severity_class(spei_value):
    """Map a SPEI value to the DroughtIndices drought_severity_class choices."""
    if spei_value is None or pd.isna(spei_value):
        return 'None'
    if spei_value > -0.5:
        return 'None'
    if spei_value > -1.0:
        return 'Abnormally Dry'
    if spei_value > -1.5:
        return 'Moderate Drought'
    if spei_value > -2.0:
        return 'Severe Drought'
    return 'Extreme Drought'


def _year_for(date):
    year, _ = ObservationYear.objects.get_or_create(label=str(date.year))
    return year


class Command(BaseCommand):
    help = ('Build monthly SPEI dataset, train XGBoost SPEI(T+1)/SPEI(T+3) '
            'models, store SPEI history in drought_indices and persist the '
            'current outlook as a SpeiForecast.')

    def add_arguments(self, parser):
        parser.add_argument('--region', type=int, default=None,
                            help='Region id (default: all regions with data)')
        parser.add_argument('--nmonth', type=int, default=3,
                            help='SPEI accumulation window in months (default 3)')
        parser.add_argument('--mode', default='quantile_p25',
                            choices=['regression', 'weighted', 'quantile_p25', 'delta'],
                            help=('XGBoost training mode (default: risk-averse quantile P25; '
                                  'delta = learn the change from current SPEI)'))
        parser.add_argument('--skip-history', action='store_true',
                            help='Do not write SPEI history to drought_indices')
        parser.add_argument('--skip-forecast', action='store_true',
                            help='Do not write the current SpeiForecast row')

    def handle(self, *args, **options):
        nmonth = options['nmonth']
        regions = Region.objects.all()
        if options['region']:
            regions = regions.filter(id=options['region'])

        models_dir = Path(settings.BASE_DIR) / 'models'
        models_dir.mkdir(exist_ok=True)

        for region in regions:
            try:
                df = build_spei_dataset(region.id, spei_nmonth=nmonth)
            except Exception as exc:
                self.stdout.write(self.style.WARNING(
                    f'{region.name}: dataset build failed: {exc}'))
                continue
            if df.empty:
                self.stdout.write(f'{region.name}: no monthly data, skipping.')
                continue

            self.stdout.write(f'{region.name}: dataset {df.shape[0]} rows, '
                              f'{df.index.min()} -> {df.index.max()}')

            res = train_spei_models(df, mode=options['mode'])
            meta = {
                'region_id': region.id,
                'region_name': region.name,
                'mode': options['mode'],
                'nmonth': nmonth,
                'trained_at': datetime.utcnow().isoformat() + 'Z',
                'rows': int(len(df)),
                'date_range': [str(df.index.min()), str(df.index.max())],
                'targets': {},
            }

            ok_t1 = ok_t3 = False
            for key, out in res.items():
                if 'error' in out:
                    self.stdout.write(self.style.WARNING(
                        f'{region.name} {key}: {out["error"]}'))
                    continue
                ok_t1 = ok_t1 or key == 'spei_t1'
                ok_t3 = ok_t3 or key == 'spei_t3'
                with open(models_dir / f'spei_xgb_{key}_r{region.id}.pkl', 'wb') as fh:
                    pickle.dump({'model': out['model'],
                                 'feature_cols': out['feature_cols'],
                                 'nmonth': nmonth, 'region_id': region.id}, fh)
                meta['targets'][key] = {
                    k: v for k, v in out.items() if k != 'model'}
                self.stdout.write(self.style.SUCCESS(
                    f"{region.name} {key}: MAE={out['mae']:.3f} "
                    f"RMSE={out['rmse']:.3f} R2={out['r2']:.3f} "
                    f"(n_train={out['n_train']}, n_test={out['n_test']})"))

            with open(models_dir / f'spei_training_metadata_r{region.id}.json',
                      'w', encoding='utf-8') as fh:
                json.dump(meta, fh, indent=2, default=str)

            if not options['skip_history']:
                stored = self._store_history(region, df, nmonth)
                self.stdout.write(f'{region.name}: stored {stored} monthly SPEI '
                                  'rows in drought_indices.')

            if not options['skip_forecast'] and ok_t1 and ok_t3:
                fc = self._store_forecast(region, df, res, meta)
                if fc is not None:
                    self.stdout.write(self.style.SUCCESS(
                        f'{region.name}: forecast T+1={fc.level_t1} '
                        f'({fc.score_t1}, SPEI {fc.spei_t1}) | '
                        f'T+3={fc.level_t3} ({fc.score_t3}, SPEI {fc.spei_t3})'))

        self.stdout.write(self.style.SUCCESS('SPEI pipeline complete.'))

    def _store_history(self, region, df, nmonth):
        column = SPEI_COLUMN_BY_NMONTH.get(nmonth)
        if column is None:
            return 0
        stored = 0
        for idx, row in df.iterrows():
            value = row.get('spei_target')
            if value is None or pd.isna(value):
                continue
            date = idx.to_timestamp(how='end').date()
            lat = float(row['latitude']) if pd.notna(row['latitude']) else None
            lon = float(row['longitude']) if pd.notna(row['longitude']) else None
            defaults = {
                column: round(float(value), 2),
                'drought_severity_class': _severity_class(float(value)),
            }
            if row.get('subregion'):
                defaults['subregion'] = row['subregion']
            DroughtIndices.objects.update_or_create(
                region=region,
                year=_year_for(date),
                measurement_date=date,
                latitude=lat,
                longitude=lon,
                defaults=defaults,
            )
            stored += 1
        return stored

    def _store_forecast(self, region, df, res, meta, force=False):
        t1 = res.get('spei_t1') or {}
        if 'model' not in t1:
            return None

        t1_cols = t1['feature_cols']
        clf1 = res.get('clf_t1') or {}
        clf1_model = clf1.get('model')
        clf1_cols = clf1.get('feature_cols') or t1_cols

        frame = df.sort_index()
        if 'latitude' in frame.columns and \
                frame.groupby(['latitude', 'longitude']).ngroups > 1:
            rows = [g.iloc[-1]
                    for _, g in frame.groupby(['latitude', 'longitude'])]
        else:
            rows = [frame.iloc[-1]]

        def _features(cols):
            return np.array([[r.get(c, np.nan) for c in cols] for r in rows],
                            dtype=float)

        def _predict(target):
            """Raw model output on the target's native scale.

            delta-mode models learn SPEI(t+h) - SPEI(t), so the known
            current SPEI must be added back to turn their output into the
            published absolute SPEI forecast.
            """
            raw = target['model'].predict(_features(target['feature_cols']))
            if (target.get('mode') or 'regression') == 'delta':
                bases = np.array([float(r.get('spei_current', np.nan))
                                  for r in rows], dtype=float)
                if np.isnan(bases).any():
                    logger.warning(
                        '%s: spei_current missing for %d forecast row(s); '
                        'delta prediction returned as NaN-affected',
                        region.name, int(np.isnan(bases).sum()))
                raw = raw + bases
            return raw

        spei_t1 = float(np.mean(_predict(t1)))
        prob_t1 = None
        if clf1_model is not None:
            prob_t1 = round(float(np.mean(
                clf1_model.predict_proba(_features(clf1_cols))[:, 1])), 3)

        spei_t3 = prob_t3 = score_t3 = None
        level_t3 = ''
        recs_t3 = []
        if getattr(settings, 'SPEI_T3_ENABLED', False):
            t3 = res.get('spei_t3') or {}
            if 'model' in t3:
                spei_t3 = float(np.mean(_predict(t3)))
                score_t3, level_t3 = spei_to_risk(spei_t3)
                recs_t3 = get_recommendations(level_t3)
                clf3 = res.get('clf_t3') or {}
                if clf3.get('model') is not None:
                    prob_t3 = round(float(np.mean(clf3['model'].predict_proba(
                        _features(clf3.get('feature_cols')
                                  or t3['feature_cols']))[:, 1])), 3)

        score_t1, level_t1 = spei_to_risk(spei_t1)

        last_idx = frame.index[-1]
        feature_month = last_idx.to_timestamp(how='start').date()
        target1 = (last_idx + 1).to_timestamp(how='start').date()
        target3 = (last_idx + 3).to_timestamp(how='start').date()

        warned_t1, warn_source = drought_warning(prob_t1, spei_t1, month=target1.month)
        band_key, band_label = drought_probability_band(prob_t1)

        today = datetime.utcnow().date()
        lag = (today.year * 12 + today.month) - (target1.year * 12 + target1.month)
        if lag > MAX_FORECAST_LAG_MONTHS and not force:
            logger.warning(
                'Skipping %s forecast: observations end %s, so target %s is '
                '%d months behind today. Refresh data or pass force=True.',
                region.name, feature_month, target1, lag)
            return None

        top_drivers = {}
        if t1.get('top_features'):
            top_drivers = dict(t1['top_features'][:5])

        clf_metrics = clf1.get('metrics') or {}
        validation_metrics = {
            'basis': 'purged chronological holdout, single split',
            'data_as_of': str(feature_month),
            'months_behind_today': lag,
            'drought_threshold': DROUGHT_PROB_THRESHOLD,
            'prob_drought_t1': prob_t1,
            'prob_band_t1': band_key,
            'prob_band_label_t1': band_label,
            'warning_t1': warned_t1,
            'warning_source': warn_source,
            'decision_rule_provenance': DECISION_RULE_PROVENANCE,
            'spei_t1': {k: t1.get(k) for k in
                        ('mae', 'rmse', 'r2', 'n_train', 'n_test', 'n_purged')
                        if t1.get(k) is not None},
            'benchmarks': t1.get('benchmarks') or {},
            'clf_t1': {k: clf_metrics.get(k) for k in
                       ('auc', 'recall', 'precision', 'accuracy', 'n_test')
                       if clf_metrics.get(k) is not None},
        }

        obj, created = SpeiForecast.objects.update_or_create(
            region=region,
            feature_month=feature_month,
            target_month_t1=target1,
            defaults={
                'year': _year_for(feature_month),
                'target_month_t3': target3,
                'spei_t1': round(spei_t1, 2),
                'spei_t3': round(spei_t3, 2) if spei_t3 is not None else None,
                'score_t1': score_t1,
                'score_t3': score_t3,
                'level_t1': level_t1,
                'level_t3': level_t3,
                'recommendations_t1': get_recommendations(level_t1, month=target1.month, prob=prob_t1),
                'recommendations_t3': recs_t3,
                'top_drivers': top_drivers,
                'prob_drought_t1': prob_t1,
                'prob_drought_t3': prob_t3,
                'validation_metrics': validation_metrics,
                'model_version': 'spei-xgb-t1-%s'
                                 % (meta.get('mode') or 'regression'),
                'generated_at': timezone.now(),
            },
        )
        logger.info('%s %s T+1 target=%s level=%s prob_drought=%s',
                    'created' if created else 'updated', region.name,
                    target1, level_t1, prob_t1)
        return obj
