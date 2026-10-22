"""Pool all regions' monthly SPEI datasets and train ONE cross-region model.

The pooled model sees ~10x more drought events (incl. Severe/Extreme) than a
single-region model, and uses latitude/longitude (already in FEATURE_COLS) to
condition on the climate gradient. Forecasts are then generated per region.

Usage:
    python manage.py train_spei_pooled
    python manage.py train_spei_pooled --mode quantile_p25 --skip-history
"""
import json
import pickle
from datetime import datetime
from pathlib import Path

import numpy as np

import pandas as pd
from django.conf import settings
from django.core.management.base import BaseCommand

from dashboard.models import Region
from dashboard.prediction_engine.spei_features import (
    build_spei_dataset,
    train_drought_classifier,
    train_spei_models,
)
from dashboard.management.commands.train_spei_models import (
    Command as BaseSpeiCommand,
)


class Command(BaseCommand):
    help = ('Build the pooled multi-region SPEI dataset, train shared XGBoost '
            'T+1/T+3 models, backfill SPEI history and store per-region forecasts.')

    def add_arguments(self, parser):
        parser.add_argument('--nmonth', type=int, default=3)
        parser.add_argument('--mode', default='delta',
                            choices=['regression', 'weighted', 'quantile_p25', 'delta'],
                            help=('delta = learn SPEI(t+h) - SPEI(t) with the known '
                                  'current value added back (default; beats persistence '
                                  'in purged walk-forward). regression = plain mean; '
                                  'quantile_p25 = risk-averse dry-side scenario, not '
                                  'comparable to the mean R2.'))
        parser.add_argument('--skip-history', action='store_true')
        parser.add_argument('--skip-forecast', action='store_true')
        parser.add_argument('--no-p25', action='store_true',
                            help='Skip training the risk-averse P25 side model')
        parser.add_argument('--horizon-t3', default='auto',
                            choices=['auto', 'on', 'off'],
                            help=('Skip training T+3 models entirely (off), always '
                                  'train them (on), or auto: train only when SPEI_T3 '
                                  'is enabled in settings (default)'))
        parser.add_argument('--force-forecast', action='store_true',
                            help=('Publish a forecast even when the observations are '
                                  'more than 2 months stale'))

    def handle(self, *args, **options):
        nmonth = options['nmonth']
        mode = options['mode']
        helper = BaseSpeiCommand()  # reuses _store_history / _store_forecast

        models_dir = Path(settings.BASE_DIR) / 'models'
        models_dir.mkdir(exist_ok=True)

        dfs, regions = [], []
        for region in Region.objects.filter(latitude__isnull=False):
            try:
                df_r = build_spei_dataset(region.id, spei_nmonth=nmonth)
            except Exception as exc:
                self.stdout.write(f'{region.name}: build failed ({exc}), skipping')
                continue
            if df_r.empty:
                continue
            df_r['region_id'] = region.id
            dfs.append(df_r)
            regions.append(region)
            self.stdout.write(f'{region.name}: {len(df_r)} monthly rows')

        if not dfs:
            self.stdout.write(self.style.WARNING('No regional data found.'))
            return

        pool = pd.concat(dfs)
        self.stdout.write(f'Pooled dataset: {len(pool)} rows across '
                          f'{len(regions)} regions')

        train_t3 = (options['horizon_t3'] == 'on'
                    or (options['horizon_t3'] == 'auto'
                        and getattr(settings, 'SPEI_T3_ENABLED', False)))
        res = train_spei_models(pool, mode=mode, train_t3=train_t3)
        meta = {
            'mode': mode,
            'nmonth': nmonth,
            'pool': True,
            'region_ids': [r.id for r in regions],
            'region_names': [r.name for r in regions],
            'rows': int(len(pool)),
            'trained_at': datetime.utcnow().isoformat() + 'Z',
            'targets': {},
        }

        ok_t1 = ok_t3 = False
        for key, out in res.items():
            if 'error' in out:
                self.stdout.write(self.style.WARNING(f'{key}: {out["error"]}'))
                continue
            ok_t1 = ok_t1 or key == 'spei_t1'
            ok_t3 = ok_t3 or key == 'spei_t3'
            with open(models_dir / f'spei_xgb_{key}_pooled.pkl', 'wb') as fh:
                pickle.dump({'model': out['model'],
                             'feature_cols': out['feature_cols'],
                             'nmonth': nmonth, 'mode': mode,
                             'region_ids': meta['region_ids']}, fh)
            meta['targets'][key] = {k: v for k, v in out.items() if k != 'model'}
            pers = (out.get('benchmarks') or {}).get('persistence') or {}
            extra = f" persistence MAE={pers['mae']}" if pers.get('mae') is not None else ''
            self.stdout.write(self.style.SUCCESS(
                f"{key}: MAE={out['mae']:.3f} RMSE={out['rmse']:.3f} "
                f"R2={out['r2']:.3f}{extra} (train={out['n_train']}, test={out['n_test']}, "
                f"purged={out.get('n_purged', 0)})"))

        # Keep a risk-averse dry-side model alongside the unbiased mean model.
        # It errs deliberately low, which is useful as a "worst plausible case"
        # but must never be the number we publish or verify against reality.
        if not options['no_p25']:
            p25 = train_spei_models(pool, mode='quantile_p25', train_t3=train_t3)
            for key, out in p25.items():
                if 'error' in out:
                    continue
                with open(models_dir / f'spei_xgb_{key}_pooled_p25.pkl', 'wb') as fh:
                    pickle.dump({'model': out['model'],
                                 'feature_cols': out['feature_cols'],
                                 'nmonth': nmonth, 'mode': 'quantile_p25',
                                 'region_ids': meta['region_ids'],
                                 'role': 'risk-averse dry-side scenario; '
                                         'do not publish or verify against this'}, fh)
                meta.setdefault('side_models', {})[f'{key}_p25'] = {
                    k: v for k, v in out.items() if k != 'model'}
                self.stdout.write(self.style.WARNING(
                    f"{key} (P25 dry-side, not for publication): "
                    f"MAE={out['mae']:.3f} R2={out['r2']:.3f}"))

        for h in (1, 3) if train_t3 else (1,):
            clf_res = train_drought_classifier(pool, horizon=h)
            if 'error' in clf_res:
                self.stdout.write(self.style.WARNING(
                    f'clf_t{h}: {clf_res["error"]}'))
                continue
            with open(models_dir / f'spei_clf_t{h}_pooled.pkl', 'wb') as fh:
                pickle.dump({'model': clf_res['model'],
                             'feature_cols': clf_res['feature_cols'],
                             'nmonth': nmonth, 'mode': mode,
                             'region_ids': meta['region_ids']}, fh)
            res[f'clf_t{h}'] = {'model': clf_res['model'],
                                'feature_cols': clf_res['feature_cols'],
                                'metrics': clf_res['metrics']}
            meta['targets'][f'clf_t{h}'] = clf_res['metrics']
            m_ = clf_res['metrics']
            self.stdout.write(self.style.SUCCESS(
                f"clf_t{h}: recall={m_['recall']:.2f} "
                f"precision={m_['precision']:.2f} "
                f"accuracy={m_['accuracy']:.2f} "
                f"auc={m_['auc'] if m_['auc'] is None else round(m_['auc'], 3)} "
                f"(n_test={m_['n_test']}, years={m_['test_years']})"))

        with open(models_dir / 'spei_training_metadata_pooled.json', 'w',
                  encoding='utf-8') as fh:
            json.dump(meta, fh, indent=2, default=str)

        if not options['skip_history']:
            for region, df_r in zip(regions, dfs):
                stored = helper._store_history(region, df_r, nmonth)
                self.stdout.write(f'{region.name}: stored {stored} SPEI rows')

        if not options['skip_forecast'] and ok_t1:
            for region, df_r in zip(regions, dfs):
                fc = helper._store_forecast(region, df_r, res, meta,
                                            force=options['force_forecast'])
                if fc is not None:
                    line = (f'{region.name}: T+1={fc.level_t1} '
                            f'({fc.score_t1}) '
                            f'prob_drought={fc.prob_drought_t1}')
                    if fc.spei_t3 is not None:
                        line += f' | T+3={fc.level_t3} ({fc.score_t3})'
                    self.stdout.write(self.style.SUCCESS(line))

        self.stdout.write(self.style.SUCCESS('Pooled SPEI training complete.'))
