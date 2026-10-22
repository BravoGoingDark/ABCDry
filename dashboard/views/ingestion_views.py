import json
from io import BytesIO
from collections import defaultdict
from datetime import datetime

import pandas as pd
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.utils.translation import gettext as _

from ..forms import ExcelImportForm
from ..models import (
    CropType,
    EnvironmentalSnapshot,
    IrrigationMethod,
    ObservationYear,
    Region,
    SoilMetrics,
    ClimateMetrics,
    DroughtIndices,
    AgriculturalMetrics,
    RemoteSensingMetrics,
    HydrologyMetrics,
    DataImportLog,
)
from ..data_ingestion_utils import DataImporter, DataIngestionError, create_reference_data
from .utils import (
    _is_viewer_user,
    _is_subadmin_user,
    _validate_coordinates_for_region,
    TEMPLATE_COLUMNS,
)


# Alias map: common user column names -> canonical DB/import field names
COLUMN_ALIASES = {
    # Date / identity
    'date': 'measurement_date',
    'datetime': 'measurement_date',
    'record_date': 'measurement_date',
    # Climate
    'precipitation_mm': 'rainfall_mm',
    'precip_mm': 'rainfall_mm',
    'precipitation': 'rainfall_mm',
    'rain': 'rainfall_mm',
    'rainfall': 'rainfall_mm',
    'rainfall_mm_day': 'rainfall_mm',
    'tmean': 'temperature_mean_c',
    'tmean_c': 'temperature_mean_c',
    'tmp_mean': 'temperature_mean_c',
    'temperature_c': 'temperature_mean_c',
    'tmax': 'temperature_max_c',
    'tmax_c': 'temperature_max_c',
    'tmp_max': 'temperature_max_c',
    'tmin': 'temperature_min_c',
    'tmin_c': 'temperature_min_c',
    'tmp_min': 'temperature_min_c',
    'relative_humidity': 'relative_humidity_percent',
    'rh': 'relative_humidity_percent',
    'humidity': 'relative_humidity_percent',
    'humidity_percent': 'relative_humidity_percent',
    'solar_radiation_mj_m2_day': 'solar_radiation_mjm2day',
    'solar_radiation': 'solar_radiation_mjm2day',
    'radiation': 'solar_radiation_mjm2day',
    'wind_speed_10m': 'wind_speed_ms',
    'wind_speed': 'wind_speed_ms',
    'wind': 'wind_speed_ms',
    # Remote sensing
    'lst_c': 'land_surface_temperature_c',
    'lst': 'land_surface_temperature_c',
    'land_surface_temperature': 'land_surface_temperature_c',
    'soil_moisture': 'satellite_soil_moisture_percent',
    'sm': 'satellite_soil_moisture_percent',
    # Station exports (FAO-56 style climate + crop files)
    'tmean_°c': 'temperature_mean_c',
    'tmin_°c': 'temperature_min_c',
    'tmax_°c': 'temperature_max_c',
    'relative_humidity% 2m': 'relative_humidity_percent',
    'wind_speed_2m m/s': 'wind_speed_ms',
    'solar_radiation_mj_m2_day': 'solar_radiation_mjm2day',
    'et0 (mm/jour)': 'evapotranspiration_et0_mmday',
    # Agricultural (French) station columns
    'culture': 'crop',
    'ênnée': 'year',
    'stade': 'growth_stage',
    'kc': 'crop_coefficient_kc',
    'etc (mm/jour)': 'crop_water_requirement_mmday',
    'jour du cycle': 'cycle_day',
    # Hydrology
    'precip': 'precipitation_mm',
    'et': 'evapotranspiration_mm',
    'et0': 'evapotranspiration_et0_mmday',
}


def _read_excel_best_sheet(uploaded_file, metric_type):
    """Read an Excel file picking the sheet whose columns best match the metric type."""
    xl = pd.ExcelFile(uploaded_file)
    if len(xl.sheet_names) == 1:
        return xl.parse(xl.sheet_names[0])
    metric_cols = set(TEMPLATE_COLUMNS.get(metric_type, []))
    best_name, best_score = xl.sheet_names[0], -1
    for name in xl.sheet_names:
        try:
            df = xl.parse(name, nrows=100)
        except Exception:
            continue
        cols = set()
        for c in df.columns:
            key = str(c).strip().lower()
            cols.add(COLUMN_ALIASES.get(key, key))
            cols.add(str(c).strip())
        score = len(cols - set()) if not metric_cols else len(cols.intersection(metric_cols))
        if score - best_score == abs(score - best_score) and score - best_score != 0:
            best_name, best_score = name, score
    return xl.parse(best_name)


def _get_region(name):
    """Tolerant region lookup: exact, then case-insensitive/trimmed."""
    name = str(name or '').strip()
    if not name:
        raise ValueError('Missing region name')
    region = Region.objects.filter(name=name).first()
    if region is None:
        region = Region.objects.filter(name__iexact=name).first()
    if region is None:
        raise ValueError("Region '%s' not found" % name)
    return region


def _get_or_create_year(label):
    """Tolerant year lookup: get or create the observation year."""
    label = str(label or '').strip()
    if label.endswith('.0'):
        label = label[:-2]
    if not label:
        raise ValueError('Missing year')
    year, _ = ObservationYear.objects.get_or_create(label=label)
    return year


def _row_coords(row):
    """Extract (latitude, longitude) floats from an import row; None if absent."""
    lat_f = lon_f = None
    try:
        raw = row.get('latitude')
        if raw is not None and pd.notna(raw):
            lat_f = float(raw)
    except (TypeError, ValueError):
        lat_f = None
    try:
        raw = row.get('longitude')
        if raw is not None and pd.notna(raw):
            lon_f = float(raw)
    except (TypeError, ValueError):
        lon_f = None
    return lat_f, lon_f


def _get_or_create_crop(name):
    """Tolerant crop lookup: exact, then case-insensitive/trimmed, then create."""
    name = str(name or '').strip()
    if not name:
        raise ValueError('Missing crop name')
    crop = CropType.objects.filter(name=name).first()
    if crop is None:
        crop = CropType.objects.filter(name__iexact=name).first()
    if crop is None:
        crop, _ = CropType.objects.get_or_create(name=name)
    return crop


def _normalize_import_df(df, metric_type, region_name=None):
    """Normalize an uploaded DataFrame for import.

    - Renames common user column names to canonical field names.
    - Ensures a 'region' column is present (uses region_name if provided).
    - Derives a 'year' column from measurement_date if missing.
    - Returns (df, errors).
    """
    errors = []
    if df is None or df.empty:
        return df, ['Uploaded file is empty']

    rename_map = {}
    for col in df.columns:
        col_str = str(col).strip()
        key = col_str.lower().strip()
        if key in COLUMN_ALIASES and COLUMN_ALIASES[key] != col_str:
            rename_map[col_str] = COLUMN_ALIASES[key]
    if rename_map:
        df = df.rename(columns=rename_map)

    # measurement_date fallback
    if 'measurement_date' not in df.columns:
        # try common variants
        for cand in ['Date', 'date', 'DATE']:
            if cand in df.columns:
                df = df.rename(columns={cand: 'measurement_date'})
                break
        else:
            errors.append("Column 'measurement_date' (or a date column) not found in file")

    # Parse measurement_date to datetime (handles Excel serial numbers too)
    if 'measurement_date' in df.columns:
        ser = df['measurement_date']
        numeric = pd.to_numeric(ser, errors='coerce')
        mostly_numeric = (float(numeric.notna().mean()) if len(numeric) else 0.0) - 0.9
        is_mostly_numeric = mostly_numeric == abs(mostly_numeric) and mostly_numeric != 0.0
        if pd.api.types.is_numeric_dtype(ser) and ser.notna().any():
            # Raw Excel serial day numbers, e.g. 35065 = 1996-01-01
            df['measurement_date'] = pd.to_datetime(numeric, unit='D', origin='1899-12-30', errors='coerce')
        elif not pd.api.types.is_datetime64_any_dtype(ser) and is_mostly_numeric:
            # Numeric-looking strings that are Excel serial day numbers
            df['measurement_date'] = pd.to_datetime(numeric, unit='D', origin='1899-12-30', errors='coerce')
        else:
            try:
                df['measurement_date'] = pd.to_datetime(ser, errors='coerce')
            except Exception as e:
                errors.append(f'Could not parse measurement_date column: {e}')

    # Fallback: reconstruct measurement_date from day/month/year columns if
    # measurement_date is missing or could not be parsed.
    month_col = ('month' if 'month' in df.columns else 'month_' if 'month_' in df.columns else None)

    try:
        md_missing = 'measurement_date' not in df.columns
        md_allna = md_missing or bool(df['measurement_date'].isna().all())
    except Exception:
        md_allna = True

    if md_allna and month_col and 'day' in df.columns and 'year' in df.columns:
        try:
            df['measurement_date'] = pd.to_datetime(
                df['year'].astype(str) + '-' + df[month_col].astype(str) + '-' + df['day'].astype(str),
                errors='coerce',
            )
            errors = [e for e in errors if 'measurement_date' not in e]
        except Exception:
            pass

    if 'measurement_date' not in df.columns and not (month_col and 'day' in df.columns and 'year' in df.columns):
        errors.append("No usable date information found (need 'measurement_date' or day/month/year columns)")

    # Region column: the region selected in the UI always wins over the file's column
    if region_name:
        df['region'] = region_name
    elif 'region' not in df.columns:
        errors.append("No 'region' column and no region selected")

    # Year column (use file's year column if already present)
    if 'year' not in df.columns:
        if 'measurement_date' in df.columns and df['measurement_date'].notna().any():
            df['year'] = df['measurement_date'].dt.year.astype(str)
        else:
            errors.append("Column 'year' not found and could not be derived from dates")

    # Strip whitespace from object columns
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].astype(str).str.strip().replace({'nan': '', 'None': ''})

    return df, errors


def data_ingestion(request):
    """Display data ingestion interface with drag-drop and manual entry options"""
    create_reference_data()
    
    context = {
        'regions': Region.objects.all(),
        'years': ObservationYear.objects.all(),
        'crops': CropType.objects.all(),
        'irrigation_methods': IrrigationMethod.objects.all(),
        'recent_imports': DataImportLog.objects.order_by('-import_date', '-id')[:10],
    }
    return render(request, 'dashboard/data_ingestion.html', context)


@require_http_methods(["POST"])
def api_submit_metrics(request):
    """API endpoint for manual data submission"""
    try:
        data = json.loads(request.body)
        metric_type = data.get('metric_type')
        
        username = request.user.username if request.user.is_authenticated else 'Anonymous'
        
        if data.get('region') and not data.get('region_id'):
            try:
                r = Region.objects.filter(name__iexact=data.get('region')).first()
                if r:
                    data['region_id'] = r.id
            except Exception:
                pass
        if data.get('region_id') and isinstance(data.get('region_id'), str) and data.get('region_id').isdigit():
            data['region_id'] = int(data['region_id'])

        if _is_viewer_user(request.user):
            return JsonResponse({
                'success': False,
                'error': _('Viewers cannot submit data.'),
            }, status=403)

        if _is_subadmin_user(request.user):
            allowed = request.user.profile.region_id
            submitted = data.get('region_id')
            if allowed and str(submitted) != str(allowed):
                return JsonResponse({
                    'success': False,
                    'error': _('You can only submit data for your assigned region.'),
                }, status=403)

        region = Region.objects.filter(id=data.get('region_id')).first()
        if region:
            lat = data.get('latitude')
            lng = data.get('longitude')
            if lat is not None and lng is not None:
                is_valid, error_msg = _validate_coordinates_for_region(region, lat, lng)
                if not is_valid:
                    return JsonResponse({'success': False, 'error': error_msg}, status=400)

        if data.get('year') and not data.get('year_id'):
            y = ObservationYear.objects.filter(label__iexact=data.get('year')).first()
            if y:
                data['year_id'] = y.id
        if data.get('year_id') and isinstance(data.get('year_id'), str) and data.get('year_id').isdigit():
            data['year_id'] = int(data['year_id'])

        if data.get('crop') and not data.get('crop_id'):
            c = CropType.objects.filter(name__iexact=data.get('crop')).first()
            if c:
                data['crop_id'] = c.id

        if data.get('irrigation') and not data.get('irrigation_id'):
            irr = IrrigationMethod.objects.filter(name__iexact=data.get('irrigation')).first()
            if irr:
                data['irrigation_id'] = irr.id

        if data.get('timestamp') and not data.get('measurement_date'):
            data['measurement_date'] = data.get('timestamp')

        importer = DataImporter(source='Manual', username=username)
        result = importer.submit_form_data(metric_type, data)
        import_log = importer.log_import(metric_type, notes='Manual entry via web form')
        action = getattr(importer, 'last_action', None)
        return JsonResponse({
            'success': True,
            'message': _('Data submitted successfully'),
            'records_imported': importer.imported_records,
            'log_id': import_log.id,
            'action': action,
        })
    
    except DataIngestionError as e:
        return JsonResponse({
            'success': False,
            'error': str(e),
        }, status=400)
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON format',
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Unexpected error: {str(e)}',
        }, status=500)


def import_excel_metrics(request):
    """Import metrics from Excel file"""
    if request.method == 'POST':
        if _is_viewer_user(request.user):
            messages.error(request, _('Viewers cannot import data.'))
            return redirect('dashboard:data_ingestion')
        form = ExcelImportForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                excel_file = request.FILES['excel_file']
                metric_type = form.cleaned_data['metric_type']
                selected_region = form.cleaned_data.get('region')

                df = _read_excel_best_sheet(excel_file, metric_type)
                df, norm_errors = _normalize_import_df(
                    df, metric_type,
                    region_name=selected_region.name if selected_region else None,
                )
                errors = list(norm_errors)
                records_imported = 0

                if errors and df is not None and df.empty:
                    raise ValueError('; '.join(errors[:5]))

                result = None
                if metric_type == 'soil':
                    result = _import_soil_metrics(df, errors)
                elif metric_type == 'climate':
                    result = _import_climate_metrics(df, errors)
                elif metric_type == 'drought':
                    result = _import_drought_indices(df, errors)
                elif metric_type == 'agricultural':
                    result = _import_agricultural_metrics(df, errors)
                elif metric_type == 'remote_sensing':
                    result = _import_remote_sensing_metrics(df, errors)
                elif metric_type == 'hydrology':
                    result = _import_hydrology_metrics(df, errors)

                if isinstance(result, dict):
                    records_imported = result.get('count', 0)
                    created = result.get('created', 0)
                    updated = result.get('updated', 0)
                else:
                    records_imported = int(result or 0)
                    created = 0
                    updated = 0
                
                status = 'Partial' if errors else 'Success'
                DataImportLog.objects.create(
                    source='Excel',
                    filename=excel_file.name,
                    metric_type=metric_type,
                    records_imported=records_imported,
                    status=status,
                    notes=(f"{len(errors)} errors" if errors else f"Created {created}, Updated {updated}")
                )

                messages.success(request, _('Excel import completed! {} records imported.'.format(records_imported)))
                if created or updated:
                    messages.info(request, _(f"Created: {created}, Updated: {updated}"))
                if errors:
                    messages.warning(request, _('Some records had errors: {}'.format(len(errors))))
                
                return redirect('dashboard:data_ingestion')
            except Exception as e:
                messages.error(request, _('Error importing Excel file: {}'.format(str(e))))
    else:
        form = ExcelImportForm()
    
    return render(request, 'dashboard/excel_import.html', {'form': form})


def _import_soil_metrics(df, errors):
    """Import soil metrics from DataFrame"""
    count = 0
    created = 0
    updated = 0
    for idx, row in df.iterrows():
        try:
            region = _get_region(row.get('region', ''))
            year = _get_or_create_year(row.get('year', ''))
            measurement_date = pd.to_datetime(row.get('measurement_date')).date() if pd.notna(row.get('measurement_date')) else None

            defaults = {
                'moisture_content_percent': float(row.get('moisture_content_percent')) if pd.notna(row.get('moisture_content_percent')) else None,
                'sand_ratio': float(row.get('sand_ratio')) if pd.notna(row.get('sand_ratio')) else None,
                'clay_ratio': float(row.get('clay_ratio')) if pd.notna(row.get('clay_ratio')) else None,
                'silt_ratio': float(row.get('silt_ratio')) if pd.notna(row.get('silt_ratio')) else None,
                'root_zone_depth_mm': int(row.get('root_zone_depth_mm')) if pd.notna(row.get('root_zone_depth_mm')) else None,
                'organic_matter_percent': float(row.get('organic_matter_percent')) if pd.notna(row.get('organic_matter_percent')) else None,
                'infiltration_rate_mmhr': float(row.get('infiltration_rate_mmhr')) if pd.notna(row.get('infiltration_rate_mmhr')) else None,
                'field_capacity_percent': float(row.get('field_capacity_percent')) if pd.notna(row.get('field_capacity_percent')) else None,
                'wilting_point_percent': float(row.get('wilting_point_percent')) if pd.notna(row.get('wilting_point_percent')) else None,
                'salinity_ece_dsm': float(row.get('salinity_ece_dsm')) if pd.notna(row.get('salinity_ece_dsm')) else None,
                'ph_level': float(row.get('ph_level')) if pd.notna(row.get('ph_level')) else None,
            }

            lat_f, lon_f = _row_coords(row)
            obj, created_flag = SoilMetrics.objects.update_or_create(
                region=region,
                year=year,
                measurement_date=measurement_date,
                latitude=lat_f,
                longitude=lon_f,
                defaults=defaults,
            )
            count += 1
            if created_flag:
                created += 1
            else:
                updated += 1
        except Exception as e:
            errors.append(f"Row {idx}: {str(e)}")

    return {'count': count, 'created': created, 'updated': updated}


def _import_climate_metrics(df, errors):
    """Import climate metrics from DataFrame using batch upsert (without ON CONFLICT)."""
    region_map = {r.name: r for r in Region.objects.all()}
    year_map = {y.label: y for y in ObservationYear.objects.all()}

    def _get_year(label):
        year = year_map.get(label)
        if year is None:
            year, _ = ObservationYear.objects.get_or_create(label=label)
            year_map[label] = year
        return year

    region_ids = set()
    rows_data = []

    for idx, row in df.iterrows():
        try:
            region_name = row.get('region', '')
            year_label = str(row.get('year', ''))

            region = region_map.get(region_name)
            if not region:
                errors.append(f"Row {idx}: Region '{region_name}' not found")
                continue

            year = _get_year(year_label)
            if not year:
                errors.append(f"Row {idx}: Year '{year_label}' not found")
                continue

            measurement_date = pd.to_datetime(row.get('measurement_date')).date() if pd.notna(row.get('measurement_date')) else None
            if not measurement_date:
                errors.append(f"Row {idx}: Invalid measurement_date")
                continue

            region_ids.add(region.id)
            rows_data.append((region, year, measurement_date, row))

        except Exception as e:
            errors.append(f"Row {idx}: {str(e)}")

    if not rows_data:
        return {'count': 0, 'created': 0, 'updated': 0}

    now = datetime.now()

    def _safe_val(v, caster=float):
        if pd.isna(v):
            return None
        try:
            val = caster(v)
            if isinstance(val, (int, float)) and val < -900:
                return None
            return val
        except (ValueError, TypeError):
            return None

    def _build_record(region, year, measurement_date, row):
        lat_f, lon_f = _row_coords(row)
        return ClimateMetrics(
            region=region,
            year=year,
            measurement_date=measurement_date,
            latitude=lat_f,
            longitude=lon_f,
            rainfall_mm=_safe_val(row.get('rainfall_mm')),
            seasonal_rainfall_variability=row.get('seasonal_rainfall_variability', ''),
            temperature_max_c=_safe_val(row.get('temperature_max_c')),
            temperature_min_c=_safe_val(row.get('temperature_min_c')),
            temperature_mean_c=_safe_val(row.get('temperature_mean_c')),
            relative_humidity_percent=_safe_val(row.get('relative_humidity_percent'), int),
            wind_speed_ms=_safe_val(row.get('wind_speed_ms')),
            solar_radiation_mjm2day=_safe_val(row.get('solar_radiation_mjm2day')),
            evapotranspiration_et0_mmday=_safe_val(row.get('evapotranspiration_et0_mmday')),
            evapotranspiration_etc_mmday=_safe_val(row.get('evapotranspiration_etc_mmday')),
            updated_at=now,
        )

    update_fields = [
        'rainfall_mm', 'seasonal_rainfall_variability',
        'temperature_max_c', 'temperature_min_c', 'temperature_mean_c',
        'relative_humidity_percent', 'wind_speed_ms',
        'solar_radiation_mjm2day', 'evapotranspiration_et0_mmday',
        'evapotranspiration_etc_mmday', 'latitude', 'longitude',
        'updated_at',
    ]

    existing = ClimateMetrics.objects.filter(
        region_id__in=region_ids,
    ).values_list('id', 'region_id', 'year_id', 'measurement_date', 'latitude', 'longitude')

    existing_keys = {}
    for pk, rid, yid, mdate, lat_v, lon_v in existing:
        lat_v = float(lat_v) if lat_v is not None else None
        lon_v = float(lon_v) if lon_v is not None else None
        existing_keys[(rid, yid, mdate, lat_v, lon_v)] = pk

    to_create = []
    to_update = []
    rainfall_by_region = defaultdict(list)

    for region, year, measurement_date, row in rows_data:
        rec = _build_record(region, year, measurement_date, row)
        key = (region.id, year.id, measurement_date, rec.latitude, rec.longitude)
        pk = existing_keys.get(key)
        if pk is not None:
            rec.id = pk
            to_update.append(rec)
        else:
            to_create.append(rec)

        rainfall_mm = float(row.get('rainfall_mm')) if pd.notna(row.get('rainfall_mm')) else None
        if rainfall_mm is not None:
            rainfall_by_region[region.id].append((measurement_date, rainfall_mm))

    if to_create:
        ClimateMetrics.objects.bulk_create(to_create)

    if to_update:
        ClimateMetrics.objects.bulk_update(to_update, update_fields)

    _batch_calculate_spi(dict(rainfall_by_region))

    return {
        'count': len(to_create) + len(to_update),
        'created': len(to_create),
        'updated': len(to_update),
    }


def _batch_calculate_spi(rainfall_by_region):
    """Calculate SPI for all rainfall points, grouped by region, in bulk, using per-month gamma."""
    from ..prediction_engine.physical_helpers import calculate_spi as calc_spi_monthy

    if not rainfall_by_region:
        return

    for region_id, points in rainfall_by_region.items():
        region = Region.objects.get(id=region_id)

        all_climate = list(ClimateMetrics.objects.filter(
            region=region, rainfall_mm__isnull=False,
        ).order_by('measurement_date').values_list('measurement_date', 'rainfall_mm'))

        if len(all_climate) < 30:
            continue

        dates = [c[0] for c in all_climate]
        vals = [float(c[1]) for c in all_climate]
        series = pd.Series(vals, index=pd.DatetimeIndex(dates))

        spi1_series = calc_spi_monthy(series, nmonth=1)
        spi3_series = calc_spi_monthy(series, nmonth=3) if len(series) >= 60 else None
        spi12_series = calc_spi_monthy(series, nmonth=12) if len(series) >= 180 else None

        drought_records = []
        year_cache = {}

        for date, rainfall_mm in points:
            if date not in spi1_series.index:
                continue

            spi_1 = float(spi1_series.loc[date]) if pd.notna(spi1_series.loc[date]) else None
            spi_3 = float(spi3_series.loc[date]) if spi3_series is not None and pd.notna(spi3_series.loc[date]) else spi_1
            spi_12 = float(spi12_series.loc[date]) if spi12_series is not None and pd.notna(spi12_series.loc[date]) else spi_1

            year_label = str(date.year)
            if year_label not in year_cache:
                year_obj, _ = ObservationYear.objects.get_or_create(label=year_label)
                year_cache[year_label] = year_obj
            year = year_cache[year_label]

            drought_records.append(DroughtIndices(
                region=region,
                year=year,
                measurement_date=date,
                spi_1month=spi_1,
                spi_3month=spi_3,
                spi_12month=spi_12,
            ))

        if drought_records:
            existing_di = DroughtIndices.objects.filter(
                region=region,
                measurement_date__in=[d.measurement_date for d in drought_records],
            ).values_list('id', 'year_id', 'measurement_date')
            di_existing = {(yid, md): pk for pk, yid, md in existing_di}

            to_create_di = []
            to_update_di = []
            for drec in drought_records:
                pk = di_existing.get((drec.year_id, drec.measurement_date))
                if pk is not None:
                    drec.id = pk
                    to_update_di.append(drec)
                else:
                    to_create_di.append(drec)

            if to_create_di:
                DroughtIndices.objects.bulk_create(to_create_di)
            if to_update_di:
                DroughtIndices.objects.bulk_update(
                    to_update_di, ['spi_1month', 'spi_3month', 'spi_12month']
                )


def _import_drought_indices(df, errors):
    """Import drought indices from DataFrame"""
    count = 0
    created = 0
    updated = 0
    for idx, row in df.iterrows():
        try:
            region = _get_region(row.get('region', ''))
            year = _get_or_create_year(row.get('year', ''))
            measurement_date = pd.to_datetime(row.get('measurement_date')).date() if pd.notna(row.get('measurement_date')) else None

            defaults = {
                'spi_1month': float(row.get('spi_1month')) if pd.notna(row.get('spi_1month')) else None,
                'spi_3month': float(row.get('spi_3month')) if pd.notna(row.get('spi_3month')) else None,
                'spi_12month': float(row.get('spi_12month')) if pd.notna(row.get('spi_12month')) else None,
                'spei_1month': float(row.get('spei_1month')) if pd.notna(row.get('spei_1month')) else None,
                'spei_3month': float(row.get('spei_3month')) if pd.notna(row.get('spei_3month')) else None,
                'spei_12month': float(row.get('spei_12month')) if pd.notna(row.get('spei_12month')) else None,
                'pdsi_value': float(row.get('pdsi_value')) if pd.notna(row.get('pdsi_value')) else None,
                'drought_severity_class': row.get('drought_severity_class', 'None'),
            }

            lat_f, lon_f = _row_coords(row)
            obj, created_flag = DroughtIndices.objects.update_or_create(
                region=region,
                year=year,
                measurement_date=measurement_date,
                latitude=lat_f,
                longitude=lon_f,
                defaults=defaults,
            )
            count += 1
            if created_flag:
                created += 1
            else:
                updated += 1
        except Exception as e:
            errors.append(f"Row {idx}: {str(e)}")

    return {'count': count, 'created': created, 'updated': updated}


def _import_agricultural_metrics(df, errors):
    """Import agricultural metrics from DataFrame"""
    count = 0
    created = 0
    updated = 0
    for idx, row in df.iterrows():
        try:
            region = _get_region(row.get('region', ''))
            year = _get_or_create_year(row.get('year', ''))
            crop = _get_or_create_crop(row.get('crop', ''))
            irrigation = None
            if pd.notna(row.get('irrigation_method')):
                try:
                    irrigation = IrrigationMethod.objects.get(name=row.get('irrigation_method'))
                except Exception:
                    irrigation = None

            measurement_date = pd.to_datetime(row.get('measurement_date')).date() if pd.notna(row.get('measurement_date')) else None

            defaults = {
                'growth_stage': row.get('growth_stage', 'Vegetative'),
                'crop_coefficient_kc': float(row.get('crop_coefficient_kc')) if pd.notna(row.get('crop_coefficient_kc')) else None,
                'crop_water_requirement_mmday': float(row.get('crop_water_requirement_mmday')) if pd.notna(row.get('crop_water_requirement_mmday')) else None,
                'yield_reduction_factor': float(row.get('yield_reduction_factor')) if pd.notna(row.get('yield_reduction_factor')) else None,
                'irrigation_method': irrigation,
                'irrigation_efficiency_percent': int(row.get('irrigation_efficiency_percent')) if pd.notna(row.get('irrigation_efficiency_percent')) else None,
                'water_applied_mm': float(row.get('water_applied_mm')) if pd.notna(row.get('water_applied_mm')) else None,
                'leaf_temperature_c': float(row.get('leaf_temperature_c')) if pd.notna(row.get('leaf_temperature_c')) else None,
                'stomatal_conductance': float(row.get('stomatal_conductance')) if pd.notna(row.get('stomatal_conductance')) else None,
            }

            lat_f, lon_f = _row_coords(row)
            defaults['latitude'] = lat_f
            defaults['longitude'] = lon_f
            obj, created_flag = AgriculturalMetrics.objects.update_or_create(
                region=region,
                year=year,
                crop=crop,
                measurement_date=measurement_date,
                latitude=lat_f,
                longitude=lon_f,
                defaults=defaults,
            )
            count += 1
            if created_flag:
                created += 1
            else:
                updated += 1
        except Exception as e:
            errors.append(f"Row {idx}: {str(e)}")

    return {'count': count, 'created': created, 'updated': updated}


def _import_remote_sensing_metrics(df, errors):
    """Import remote sensing metrics from DataFrame"""
    count = 0
    created = 0
    updated = 0
    for idx, row in df.iterrows():
        try:
            region = _get_region(row.get('region', ''))
            year = _get_or_create_year(row.get('year', ''))
            measurement_date = pd.to_datetime(row.get('measurement_date')).date() if pd.notna(row.get('measurement_date')) else None

            defaults = {
                'ndvi': float(row.get('ndvi')) if pd.notna(row.get('ndvi')) else None,
                'ndwi': float(row.get('ndwi')) if pd.notna(row.get('ndwi')) else None,
                'land_surface_temperature_c': float(row.get('land_surface_temperature_c')) if pd.notna(row.get('land_surface_temperature_c')) else None,
                'satellite_soil_moisture_percent': float(row.get('satellite_soil_moisture_percent')) if pd.notna(row.get('satellite_soil_moisture_percent')) else None,
                'satellite_source': row.get('satellite_source', ''),
                'vegetation_condition_index': float(row.get('vegetation_condition_index')) if pd.notna(row.get('vegetation_condition_index')) else None,
                'evapotranspiration_sebal_mmday': float(row.get('evapotranspiration_sebal_mmday')) if pd.notna(row.get('evapotranspiration_sebal_mmday')) else None,
            }

            lat_f, lon_f = _row_coords(row)
            obj, created_flag = RemoteSensingMetrics.objects.update_or_create(
                region=region,
                year=year,
                measurement_date=measurement_date,
                latitude=lat_f,
                longitude=lon_f,
                defaults=defaults,
            )
            count += 1
            if created_flag:
                created += 1
            else:
                updated += 1
        except Exception as e:
            errors.append(f"Row {idx}: {str(e)}")

    return {'count': count, 'created': created, 'updated': updated}


def _import_hydrology_metrics(df, errors):
    """Import hydrology metrics from DataFrame"""
    count = 0
    created = 0
    updated = 0
    for idx, row in df.iterrows():
        try:
            region = _get_region(row.get('region', ''))
            year = _get_or_create_year(row.get('year', ''))
            measurement_date = pd.to_datetime(row.get('measurement_date')).date() if pd.notna(row.get('measurement_date')) else None

            defaults = {
                'precipitation_mm': float(row.get('precipitation_mm')) if pd.notna(row.get('precipitation_mm')) else None,
                'evapotranspiration_mm': float(row.get('evapotranspiration_mm')) if pd.notna(row.get('evapotranspiration_mm')) else None,
                'groundwater_depth_m': float(row.get('groundwater_depth_m')) if pd.notna(row.get('groundwater_depth_m')) else None,
                'runoff_mm': float(row.get('runoff_mm')) if pd.notna(row.get('runoff_mm')) else None,
                'river_flow_m3s': float(row.get('river_flow_m3s')) if pd.notna(row.get('river_flow_m3s')) else None,
                'reservoir_storage_m3': int(row.get('reservoir_storage_m3')) if pd.notna(row.get('reservoir_storage_m3')) else None,
                'irrigation_supply_available_m3': int(row.get('irrigation_supply_available_m3')) if pd.notna(row.get('irrigation_supply_available_m3')) else None,
                'soil_water_deficit_index_mm': float(row.get('soil_water_deficit_index_mm')) if pd.notna(row.get('soil_water_deficit_index_mm')) else None,
                'water_balance_percent': float(row.get('water_balance_percent')) if pd.notna(row.get('water_balance_percent')) else None,
            }

            lat_f, lon_f = _row_coords(row)
            obj, created_flag = HydrologyMetrics.objects.update_or_create(
                region=region,
                year=year,
                measurement_date=measurement_date,
                latitude=lat_f,
                longitude=lon_f,
                defaults=defaults,
            )
            count += 1
            if created_flag:
                created += 1
            else:
                updated += 1
        except Exception as e:
            errors.append(f"Row {idx}: {str(e)}")

    return {'count': count, 'created': created, 'updated': updated}


def _sanitize_excel_dataframe(df):
    """Convert timezone-aware datetimes to naive datetimes for Excel compatibility."""
    if df.empty:
        return df

    for column in list(df.columns):
        series = df[column]

        if pd.api.types.is_datetime64_any_dtype(series):
            try:
                tz = getattr(series.dt, 'tz', None)
                if tz is not None:
                    df[column] = series.dt.tz_convert(timezone.utc).dt.tz_localize(None)
                else:
                    df[column] = pd.to_datetime(series, utc=False)
            except Exception:
                df[column] = pd.to_datetime(series, errors='coerce')
            continue

        if pd.api.types.is_object_dtype(series):
            cleaned = []
            for value in series:
                if value is None:
                    cleaned.append(value)
                elif isinstance(value, datetime) and value.tzinfo is not None:
                    cleaned.append(value.astimezone(timezone.utc).replace(tzinfo=None))
                else:
                    cleaned.append(value)
            df[column] = cleaned

    return df


def export_metrics_excel(request, metric_type):
    """Export metrics to Excel file"""
    if metric_type == 'soil':
        queryset = SoilMetrics.objects.all().values()
    elif metric_type == 'climate':
        queryset = ClimateMetrics.objects.all().values()
    elif metric_type == 'drought':
        queryset = DroughtIndices.objects.all().values()
    elif metric_type == 'agricultural':
        queryset = AgriculturalMetrics.objects.all().values()
    elif metric_type == 'remote_sensing':
        queryset = RemoteSensingMetrics.objects.all().values()
    elif metric_type == 'hydrology':
        queryset = HydrologyMetrics.objects.all().values()
    else:
        return HttpResponse('Invalid metric type', status=400)

    df = pd.DataFrame(list(queryset))
    df = _sanitize_excel_dataframe(df)

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name=metric_type, index=False)

    output.seek(0)
    response = HttpResponse(
        output.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="metrics_{metric_type}_{pd.Timestamp.now().strftime("%Y%m%d")}.xlsx"'

    return response


TEMPLATE_CHOICE_OPTIONS = {
    'subregion': ['v8_st_humide_inf', 'v8_st_sub_humide'],
    'growth_stage': ['Germination', 'Vegetative', 'Flowering', 'Grain Filling', 'Maturity'],
    'drought_severity_class': ['None', 'Abnormally Dry', 'Moderate Drought', 'Severe Drought', 'Extreme Drought'],
    'satellite_source': ['SMAP', 'Sentinel-1', 'Sentinel-2', 'Sentinel-3', 'MODIS', 'Landsat'],
    'rainfall_source': ['CHIRPS', 'IMERG'],
}

TEMPLATE_REQUIRED_COLUMNS = {
    'soil': ['region', 'year', 'measurement_date'],
    'climate': ['region', 'year', 'measurement_date'],
    'drought': ['region', 'year', 'measurement_date'],
    'agricultural': ['region', 'year', 'measurement_date', 'crop', 'growth_stage'],
    'remote_sensing': ['region', 'year', 'measurement_date'],
    'hydrology': ['region', 'year', 'measurement_date'],
}


def _get_template_region_names():
    """Best-effort list of existing region names for the instructions sheet."""
    try:
        return list(Region.objects.order_by('name').values_list('name', flat=True))
    except Exception:
        return []


def download_metric_template(request, metric_type):
    """Download a guided Excel template for the given metric type.

    Sheet 1 (Data): styled headers, required columns highlighted, dropdown
    validation on choice columns.
    Sheet 2 (Instructions): plain-language filling guide.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    if metric_type not in TEMPLATE_COLUMNS:
        return HttpResponse('Invalid metric type', status=400)

    cols = TEMPLATE_COLUMNS[metric_type]
    required = set(TEMPLATE_REQUIRED_COLUMNS.get(metric_type, ['region', 'year', 'measurement_date']))
    required &= set(cols)

    wb = Workbook()

    # ---------------- Sheet 1: Data ----------------
    ws = wb.active
    ws.title = 'Data'

    header_font = Font(bold=True, color='FFFFFF')
    required_fill = PatternFill(fill_type='solid', fgColor='C0504D')   # red = must fill
    optional_fill = PatternFill(fill_type='solid', fgColor='4472C4')   # blue = optional
    header_alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

    for i, col in enumerate(cols, start=1):
        cell = ws.cell(row=1, column=i, value=col)
        cell.font = header_font
        cell.fill = required_fill if col in required else optional_fill
        cell.alignment = header_alignment
        ws.column_dimensions[get_column_letter(i)].width = max(16, len(col) + 4)
    ws.row_dimensions[1].height = 24
    ws.freeze_panes = 'A2'

    # Dropdown validation for constrained columns
    for col, options in TEMPLATE_CHOICE_OPTIONS.items():
        if col not in cols:
            continue
        letter = get_column_letter(cols.index(col) + 1)
        dv = DataValidation(
            type='list',
            formula1='"' + ','.join(options) + '"',
            allow_blank=True,
            showDropDown=False,
        )
        dv.error = 'Please choose one of the allowed values'
        dv.errorTitle = 'Invalid value'
        dv.prompt = 'Allowed: ' + ', '.join(options)
        dv.promptTitle = col
        ws.add_data_validation(dv)
        dv.add(f'{letter}2:{letter}5000')

    # ---------------- Sheet 2: Instructions ----------------
    ins = wb.create_sheet('Instructions')
    ins.column_dimensions['A'].width = 30
    ins.column_dimensions['B'].width = 95
    title_font = Font(bold=True, size=14)
    section_font = Font(bold=True, size=11, color='C0504D')

    ins['A1'] = f'{metric_type.title()} Data Import Template'
    ins['A1'].font = title_font

    rows = [
        ('', ''),
        ('HOW TO FILL THIS FILE', ''),
        ('1', 'Enter your data in the Data sheet, one row per record, starting at row 2.'),
        ('2', 'RED columns are REQUIRED - rows without them will be skipped and reported as errors.'),
        ('3', 'BLUE columns are optional - leave blank if you have no value.'),
        ('4', 'Do NOT rename, reorder or delete the header row.'),
        ('5', 'Save the file as .xlsx and upload it with the matching metric type selected.'),
        ('', ''),
        ('REQUIRED COLUMNS', ''),
    ]
    for col in sorted(required):
        rows.append((col, 'REQUIRED - every row must have a value'))

    rows += [
        ('', ''),
        ('FORMAT RULES', ''),
        ('region', 'Region name exactly as it exists in the system (see list below). Case-sensitive.'),
        ('year', 'Year as a 4-digit number, e.g. 2024. Must match the measurement_date year.'),
        ('measurement_date', 'Date in YYYY-MM-DD format (e.g. 2024-03-15). Avoid Excel serial numbers.'),
        ('', ''),
    ]

    if metric_type == 'agricultural':
        rows.append(('crop', 'Crop name exactly as it exists in the system (e.g. wheat, barley).'))
    choices = [(c, v) for c, v in TEMPLATE_CHOICE_OPTIONS.items() if c in cols]
    if choices:
        rows.append(('', ''))
        rows.append(('DROPDOWN COLUMNS', ''))
        for c, v in choices:
            rows.append((c, 'Allowed values: ' + ', '.join(v)))

    region_names = _get_template_region_names()
    if region_names:
        rows += [('', ''), ('AVAILABLE REGIONS', ''), (', '.join(region_names), '')]

    r = 2
    for a, b in rows:
        cell_a = ins.cell(row=r, column=1, value=a)
        cell_b = ins.cell(row=r, column=2, value=b)
        if b == '' and a != '' and (a.isupper() or a == ', '.join(region_names)):
            cell_a.font = section_font
        r += 1

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    response = HttpResponse(
        output.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="template_{metric_type}.xlsx"'
    return response


def import_logs_view(request):
    """View import history logs"""
    logs = DataImportLog.objects.order_by('-import_date')
    
    context = {
        'logs': logs,
        'total_records': sum(log.records_imported for log in logs),
        'success_count': logs.filter(status='Success').count(),
        'failed_count': logs.filter(status='Failed').count(),
    }
    
    return render(request, 'dashboard/import_logs.html', context)


@require_http_methods(["POST"])
def ajax_upload_file(request):
    """AJAX endpoint for drag-and-drop file upload — saves to PostgreSQL"""
    try:
        if _is_viewer_user(request.user):
            return JsonResponse({
                'success': False,
                'error': _('Viewers cannot import data.'),
            }, status=403)

        uploaded_file = request.FILES.get('file')
        metric_type = request.POST.get('metric_type', '')
        region_id = request.POST.get('region_id', '')

        if not uploaded_file:
            return JsonResponse({'success': False, 'error': 'No file provided'}, status=400)

        if not metric_type:
            return JsonResponse({'success': False, 'error': 'Please select a metric type'}, status=400)

        filename = uploaded_file.name.lower()

        if filename.endswith('.csv'):
            df = pd.read_csv(uploaded_file)
        elif filename.endswith(('.xlsx', '.xls')):
            df = _read_excel_best_sheet(uploaded_file, metric_type)
        else:
            return JsonResponse({
                'success': False,
                'error': 'Unsupported file format. Use .csv, .xlsx, or .xls'
            }, status=400)

        if df.empty:
            return JsonResponse({'success': False, 'error': 'The uploaded file contains no data'}, status=400)

        region_name = None
        if region_id:
            try:
                region_name = Region.objects.get(id=int(region_id)).name
            except (ValueError, Region.DoesNotExist):
                region_name = None

        df, norm_errors = _normalize_import_df(df, metric_type, region_name=region_name)
        if norm_errors:
            return JsonResponse({
                'success': False,
                'error': 'File format issue: ' + '; '.join(norm_errors[:4]),
            }, status=400)

        records_imported = 0
        errors = []
        created = 0
        updated = 0

        result = None
        if metric_type == 'soil':
            result = _import_soil_metrics(df, errors)
        elif metric_type == 'climate':
            result = _import_climate_metrics(df, errors)
        elif metric_type == 'drought':
            result = _import_drought_indices(df, errors)
        elif metric_type == 'agricultural':
            result = _import_agricultural_metrics(df, errors)
        elif metric_type == 'remote_sensing':
            result = _import_remote_sensing_metrics(df, errors)
        elif metric_type == 'hydrology':
            result = _import_hydrology_metrics(df, errors)
        else:
            return JsonResponse({'success': False, 'error': f'Unknown metric type: {metric_type}'}, status=400)

        if isinstance(result, dict):
            records_imported = result.get('count', 0)
            created = result.get('created', 0)
            updated = result.get('updated', 0)
        else:
            records_imported = int(result or 0)

        status = 'Failed' if records_imported == 0 and errors else ('Partial' if errors else 'Success')
        username = request.user.username if request.user.is_authenticated else 'Anonymous'

        DataImportLog.objects.create(
            source='Excel',
            filename=uploaded_file.name,
            metric_type=metric_type,
            records_imported=records_imported,
            imported_by=username,
            status=status,
            notes=f"{len(errors)} errors" if errors else "No errors",
            error_details=json.dumps(errors[:20]) if errors else None,
        )

        return JsonResponse({
            'success': True,
            'message': f'Import complete: {records_imported} records saved',
            'records_imported': records_imported,
            'total_rows': len(df),
            'error_count': len(errors),
            'errors': errors[:5],
            'created': created,
            'updated': updated,
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Upload failed: {str(e)}'
        }, status=500)
