import json
from decimal import Decimal
from datetime import date
from io import BytesIO
import logging

from django.core.serializers.json import DjangoJSONEncoder
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from fpdf import FPDF

from ..models import (
    CropType,
    EnvironmentalSnapshot,
    ObservationYear,
    Region,
    RiskAssessment,
    DroughtPrediction,
    SoilMetrics,
    ClimateMetrics,
    DroughtIndices,
    AgriculturalMetrics,
    RemoteSensingMetrics,
    HydrologyMetrics,
)
from ..prediction_engine.spei_features import (
    MAX_FORECAST_LAG_MONTHS,
    drought_probability_band,
    drought_warning,
)
from .utils import (
    _check_data_permission,
    _get_region_stations,
    _haversine_distance,
    _prediction_warning_block,
    METRICS_REGISTRY,
    MODEL_MAP,
)

logger = logging.getLogger('django')


def parameter_review(request):
    """Display parameter review and manual entry interface with expandable categories"""
    context = {
        'regions': Region.objects.all(),
        'years': ObservationYear.objects.all(),
    }
    return render(request, 'dashboard/parameter_review.html', context)


def analysis_results(request):
    """Display analysis results and drought risk assessment"""
    def safe_float(val):
        if val is None:
            return None
        try:
            return float(val)
        except Exception:
            return None

    # Honour an explicit region_id from the query string (set by JS region
    # selector), otherwise fall back to the region that actually has data.
    region_id_param = request.GET.get('region_id')
    default_region = None
    if region_id_param:
        try:
            default_region = Region.objects.get(pk=int(region_id_param))
        except (Region.DoesNotExist, ValueError):
            pass
    if default_region is None:
        default_region = (
            Region.objects.filter(name__iexact='Ichkeul').first()
            or Region.objects.filter(climate_metrics__isnull=False).first()
            or Region.objects.filter(drought_indices__isnull=False).first()
            or Region.objects.filter(remote_sensing__isnull=False).first()
            or Region.objects.order_by('name').first()
        )

    latest_soil = SoilMetrics.objects.filter(region=default_region).order_by('-measurement_date').first()
    latest_climate = ClimateMetrics.objects.filter(region=default_region).order_by('-measurement_date').first()
    latest_remote = RemoteSensingMetrics.objects.filter(region=default_region).order_by('-measurement_date').first()
    latest_hydro = HydrologyMetrics.objects.filter(region=default_region).order_by('-measurement_date').first()
    latest_agri = AgriculturalMetrics.objects.filter(region=default_region).order_by('-measurement_date').first()

    latest_prediction = DroughtPrediction.objects.filter(region=default_region).order_by('-generated_at').select_related('region', 'year').first()

    from django.db.models import Sum

    rf_30d_agg = ClimateMetrics.objects.filter(
        region=default_region,
        measurement_date__gte=latest_climate.measurement_date - timezone.timedelta(days=30)
    ).aggregate(total=Sum('rainfall_mm'))['total'] if latest_climate and latest_climate.measurement_date else None

    rf_display = safe_float(rf_30d_agg) if rf_30d_agg is not None else safe_float(getattr(latest_climate, 'rainfall_mm', None))
    etc_display = safe_float(getattr(latest_climate, 'evapotranspiration_etc_mmday', None)) or safe_float(getattr(latest_climate, 'evapotranspiration_et0_mmday', None))
    soil_display = safe_float(getattr(latest_soil, 'moisture_content_percent', None)) or safe_float(getattr(latest_prediction, 'soil_moisture_today_pct', None))

    stress_val = safe_float(getattr(latest_agri, 'yield_reduction_factor', None))
    if stress_val is None and latest_prediction and latest_prediction.drivers:
        veg_stress = latest_prediction.drivers.get('vegetation_stress')
        if veg_stress is not None:
            stress_val = float(veg_stress) / 100.0

    initial_data = {
        'soil_moisture_pct': soil_display,
        'rainfall_mm': rf_display,
        'ndvi': safe_float(getattr(latest_remote, 'ndvi', None)),
        'etc_mm': etc_display,
        'groundwater_m': safe_float(getattr(latest_hydro, 'groundwater_depth_m', None)),
        'stress_pct': stress_val,
        'temperature_c': safe_float(getattr(latest_climate, 'temperature_mean_c', None)),
        'wind_speed': safe_float(getattr(latest_climate, 'wind_speed_ms', None)),
        'humidity': safe_float(getattr(latest_climate, 'relative_humidity_percent', None)),
        'solar_radiation': safe_float(getattr(latest_climate, 'solar_radiation_mjm2day', None)),
    }

    region_map = {r.name.lower(): r.id for r in Region.objects.all()}
    year_map = {y.label.split()[0]: y.id for y in ObservationYear.objects.all() if y.label.split()[0].isdigit()}
    default_region_id = region_map.get(default_region.name.lower()) if default_region else 1
    default_year_id = year_map.get(str(timezone.now().year), 1)

    soil_qs = list(SoilMetrics.objects.filter(region=default_region).order_by('-measurement_date')[:6])
    soil_qs.reverse()
    if soil_qs:
        soil_water_vals = [safe_float(s.moisture_content_percent) or 0 for s in soil_qs]
        fc_soil = SoilMetrics.objects.filter(region=default_region, field_capacity_percent__isnull=False).order_by('-measurement_date').first()
        fc_val = float(fc_soil.field_capacity_percent) if fc_soil and fc_soil.field_capacity_percent else 30.0
        soil_water_bars = [min(1.0, v / fc_val) if v > 0 else 0 for v in soil_water_vals]
        soil_labels = [s.measurement_date.strftime('%b %d') if getattr(s, 'measurement_date', None) else '—' for s in soil_qs]
    else:
        clim_qs = list(ClimateMetrics.objects.filter(region=default_region).order_by('-measurement_date')[:6])
        clim_qs.reverse()
        soil_labels = [c.measurement_date.strftime('%b %d') if getattr(c, 'measurement_date', None) else '—' for c in clim_qs]
        rain_vals = [safe_float(c.rainfall_mm) or 0 for c in clim_qs]
        max_rain = max(rain_vals) if rain_vals and max(rain_vals) > 0 else 50.0
        soil_water_bars = [round(min(1.0, v / max_rain), 2) for v in rain_vals]
    while len(soil_water_bars) < 6:
        soil_water_bars.append(0)
    while len(soil_labels) < 6:
        soil_labels.append('—')

    risk_today_raw = safe_float(getattr(latest_prediction, 'current_risk_score', None))
    risk_7_raw = safe_float(getattr(latest_prediction, 'risk_7day', None))
    risk_30_raw = safe_float(getattr(latest_prediction, 'risk_30day', None))
    risk_today = risk_today_raw if risk_today_raw is not None else 50
    risk_7 = risk_7_raw if risk_7_raw is not None else 60
    risk_30 = risk_30_raw if risk_30_raw is not None else 70
    risk_pts = [
        max(0, risk_today - 20), max(0, risk_today - 12), max(0, risk_today - 6),
        risk_today, min(100, risk_7), min(100, (risk_7 + risk_30) / 2), min(100, risk_30),
    ]

    def _risk_svg(pts, svg_w=400, svg_h=200, pad_l=29, pad_r=29, pad_t=0, pad_b=0):
        cw = svg_w - pad_l - pad_r
        ch = svg_h - pad_t - pad_b
        n = len(pts)
        if n == 0:
            return ""
        coords = []
        for i, v in enumerate(pts):
            x = pad_l + (i / (n - 1)) * cw
            y = pad_t + ch - (v / 100) * ch
            coords.append((x, y))
        d = f"M{coords[0][0]},{coords[0][1]}"
        for i in range(1, n):
            px, py = coords[i - 1]
            cx, cy = (px + coords[i][0]) / 2, py
            d += f" Q{cx},{cy} {coords[i][0]},{coords[i][1]}"
        fill = d + f" L{coords[-1][0]},{pad_b + ch} L{coords[0][0]},{pad_b + ch} Z"
        return d, fill

    trend_line, trend_fill = _risk_svg(risk_pts)

    def _time_ago(date_val):
        if date_val is None:
            return "Unknown"
        if hasattr(date_val, 'date'):
            date_val = date_val.date()
        delta = (timezone.now().date() - date_val).days
        if delta == 0:
            return "Today"
        if delta == 1:
            return "Yesterday"
        return f"{delta}d ago"

    alerts = []
    sm = safe_float(getattr(latest_soil, 'moisture_content_percent', None))
    if sm is not None and sm < 12:
        sm_date = getattr(latest_soil, 'measurement_date', None)
        alerts.append({
            'priority': 'High Priority', 'priority_cls': 'border-error bg-error-container/20 text-error',
            'time': _time_ago(sm_date), 'title': 'Soil Moisture Critical Drop',
            'desc': f'Sensor station S-04 reported &lt; {sm:.0f}% moisture. Immediate verification required.',
            'btn_text': 'Action Required', 'btn_cls': 'text-error',
        })
    rf_30d = safe_float(getattr(latest_climate, 'rainfall_mm', None))
    if rf_30d is not None and rf_30d < 20:
        rf_date = getattr(latest_climate, 'measurement_date', None)
        alerts.append({
            'priority': 'Medium Priority', 'priority_cls': 'border-secondary bg-surface-container-low text-secondary',
            'time': _time_ago(rf_date), 'title': 'Precipitation Gap Warning',
            'desc': f'Low rainfall ({rf_30d:.1f}mm recorded). Trend analysis updated.',
            'btn_text': 'View Trends', 'btn_cls': 'text-secondary',
        })
    ndvi_val = safe_float(getattr(latest_remote, 'ndvi', None))
    if ndvi_val is not None and ndvi_val < 0.3:
        ndvi_date = getattr(latest_remote, 'measurement_date', None)
        alerts.append({
            'priority': 'Medium Priority', 'priority_cls': 'border-yellow-500 bg-yellow-50 text-yellow-700',
            'time': _time_ago(ndvi_date), 'title': 'Vegetation Stress Detected',
            'desc': f'NDVI at {ndvi_val:.2f} indicates significant vegetation water stress in the basin.',
            'btn_text': 'Analyze', 'btn_cls': 'text-yellow-600',
        })
    if not alerts:
        alerts.append({
            'priority': 'Info', 'priority_cls': 'border-primary bg-primary-container/10 text-primary',
            'time': 'Just now', 'title': 'All Clear',
            'desc': 'No critical thresholds exceeded. Standard monitoring continues.',
            'btn_text': 'Dashboard', 'btn_cls': 'text-primary',
        })

    soil_labels = []
    for s in soil_qs:
        d = getattr(s, 'measurement_date', None)
        if d:
            soil_labels.append(d.strftime('%b %d'))
        else:
            soil_labels.append('—')
    while len(soil_labels) < 6:
        soil_labels.append('—')

    trend_labels = ['T-21', 'T-14', 'T-7', 'Today', '+7 Days', '+14 Days', '+30 Days']

    base_area = 1200
    extreme_pct = max(0.05, (risk_today / 100) * 0.35)
    severe_pct = max(0.05, (risk_7 / 100) * 0.30)
    moderate_pct = max(0.05, 0.25 - (risk_today / 100) * 0.10)
    safe_pct = max(0.05, 1.0 - extreme_pct - severe_pct - moderate_pct)
    total_pct = extreme_pct + severe_pct + moderate_pct + safe_pct
    extreme_pct /= total_pct; severe_pct /= total_pct; moderate_pct /= total_pct; safe_pct /= total_pct

    heatmap_zones = {
        'extreme_km2': f"{extreme_pct * base_area:.1f}",
        'severe_km2': f"{severe_pct * base_area:.1f}",
        'moderate_km2': f"{moderate_pct * base_area:.1f}",
        'total_km2': f"{base_area:,}",
    }

    year_choices = [(y.label.split()[0], y.label) for y in ObservationYear.objects.all() if y.label.split()[0].isdigit()]

    stations_data = _get_region_stations(default_region, default_year_id)

    context = {
        'regions': Region.objects.all(),
        'years': year_choices,
        'now_year': str(timezone.now().year),
        'initial_data_json': json.dumps(initial_data, cls=DjangoJSONEncoder),
        'region_map_json': json.dumps(region_map),
        'year_map_json': json.dumps(year_map),
        'default_region_id': default_region_id,
        'default_region_name': default_region.name if default_region else 'Bizerte',
        'default_year_id': default_year_id,
        'soil_water_bars': json.dumps(soil_water_bars),
        'risk_pts_json': json.dumps(risk_pts),
        'trend_line': trend_line,
        'trend_fill': trend_fill,
        'trend_labels': trend_labels,
        'alerts': alerts,
        'heatmap_zones': heatmap_zones,
        'soil_water_labels': soil_labels,
        'stations': stations_data,
        'stations_json': json.dumps(stations_data, cls=DjangoJSONEncoder),
    }
    return render(request, 'dashboard/analysis.html', context)


def analysis_export_csv(request):
    """Export a comprehensive analysis report for a region/year as PDF."""
    region_id = request.GET.get('region_id')
    year_id = request.GET.get('year_id')

    if not region_id or not year_id:
        return HttpResponse('Missing region_id or year_id', status=400)

    try:
        region = Region.objects.get(pk=region_id)
        year = ObservationYear.objects.get(pk=year_id)
    except (Region.DoesNotExist, ObservationYear.DoesNotExist):
        return HttpResponse('Invalid region or year', status=404)

    try:
        from ..prediction_engine.pipeline import DroughtPredictionPipeline
        pipeline = DroughtPredictionPipeline()
        result = pipeline.predict_for_region(region, year, use_llm=False)
        pred = pipeline.save_prediction(region, year, result)
    except Exception:
        pred = DroughtPrediction.objects.filter(region=region, year=year).order_by('-generated_at').first()

    latest_soil = SoilMetrics.objects.filter(region=region, year=year).order_by('-measurement_date').first()
    latest_climate = ClimateMetrics.objects.filter(region=region, year=year).order_by('-measurement_date').first()
    latest_rs = RemoteSensingMetrics.objects.filter(region=region, year=year).order_by('-measurement_date').first()
    latest_hydro = HydrologyMetrics.objects.filter(region=region, year=year).order_by('-measurement_date').first()
    latest_agri = AgriculturalMetrics.objects.filter(region=region, year=year).order_by('-measurement_date').first()
    latest_di = DroughtIndices.objects.filter(region=region, year=year).order_by('-measurement_date').first()

    today_str = date.today().isoformat()
    risk_today = float(str(pred.current_risk_score)) if pred and pred.current_risk_score is not None else None
    risk_7 = float(str(pred.risk_7day)) if pred and pred.risk_7day is not None else None
    risk_30 = float(str(pred.risk_30day)) if pred and pred.risk_30day is not None else None

    def _risk_label(s):
        if s is None:
            return 'N/A'
        if s < 25:
            return 'Safe'
        if s < 50:
            return 'Watch'
        if s < 75:
            return 'Severe'
        return 'Extreme'

    drivers = pred.drivers if pred and pred.drivers else {}
    explanation = pred.explanation if pred and pred.explanation else ''

    def _fmt(val):
        if val is None:
            return '-'
        if isinstance(val, (Decimal, float, int)):
            return str(round(float(val), 2))
        return str(val)

    def _pdf_str(s):
        if not s:
            return ''
        try:
            s.encode('latin-1')
            return s
        except UnicodeEncodeError:
            import unicodedata
            return unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    w = pdf.w - pdf.l_margin - pdf.r_margin

    pdf.set_font('Helvetica', 'B', 18)
    pdf.cell(w, 12, 'Drought Analysis Report', border=0, align='C')
    pdf.ln(14)

    pdf.set_font('Helvetica', 'B', 13)
    pdf.set_fill_color(230, 240, 255)
    pdf.cell(w, 8, '1. Report Summary', border=0, fill=True)
    pdf.ln(10)

    pdf.set_font('Helvetica', '', 10)
    summary_rows = [
        ('Region', region.name),
        ('Year', year.label),
        ('Export Date', today_str),
        ('Overall Risk', f'{_risk_label(risk_today)} ({_fmt(risk_today)}/100)'),
        ('7-Day Forecast', f'{_risk_label(risk_7)} ({_fmt(risk_7)}/100)'),
        ('30-Day Forecast', f'{_risk_label(risk_30)} ({_fmt(risk_30)}/100)'),
    ]
    for label, value in summary_rows:
        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(50, 7, label, border=0)
        pdf.set_font('Helvetica', '', 10)
        pdf.cell(w - 50, 7, _pdf_str(value), border=0)
        pdf.ln(7)

    pdf.ln(4)

    pdf.set_font('Helvetica', 'B', 13)
    pdf.set_fill_color(230, 240, 255)
    pdf.cell(w, 8, '2. Key Drought Drivers', border=0, fill=True)
    pdf.ln(10)

    pdf.set_font('Helvetica', 'B', 9)
    pdf.set_fill_color(200, 215, 240)
    col_w = [w * 0.45, w * 0.25, w * 0.30]
    headers = ['Driver', 'Contribution (%)', 'Score (0-100)']
    for i, h in enumerate(headers):
        pdf.cell(col_w[i], 7, h, border=1, fill=True, align='C')
    pdf.ln()

    driver_keys = [
        ('rainfall_deficit', 'Rainfall Deficit'),
        ('high_temperature', 'High Temperature'),
        ('soil_moisture_decline', 'Soil Moisture Decline'),
        ('vegetation_stress', 'Vegetation Stress'),
        ('high_evapotranspiration', 'High Evapotranspiration'),
    ]
    abs_drivers = drivers.get('absolute', {}) if isinstance(drivers, dict) else {}
    pdf.set_font('Helvetica', '', 9)
    for i, (key, label) in enumerate(driver_keys):
        contrib = drivers.get(key, '') if isinstance(drivers, dict) else ''
        abs_val = abs_drivers.get(key, '') if isinstance(abs_drivers, dict) else ''
        fill = (i % 2 == 0)
        if fill:
            pdf.set_fill_color(245, 248, 252)
        pdf.cell(col_w[0], 6, f'  {label}', border=1, fill=fill)
        pdf.cell(col_w[1], 6, _fmt(contrib), border=1, fill=fill, align='C')
        pdf.cell(col_w[2], 6, _fmt(abs_val), border=1, fill=fill, align='C')
        pdf.ln()

    pdf.ln(6)

    pdf.set_font('Helvetica', 'B', 13)
    pdf.set_fill_color(230, 240, 255)
    pdf.cell(w, 8, '3. Drought Insight', border=0, fill=True)
    pdf.ln(10)

    pdf.set_font('Helvetica', '', 10)
    pdf.set_fill_color(252, 252, 252)
    pdf.multi_cell(w, 6, _pdf_str(explanation) if explanation else 'No insight available.', border=0, fill=True)
    pdf.ln(6)

    pdf.set_font('Helvetica', 'B', 13)
    pdf.set_fill_color(230, 240, 255)
    pdf.cell(w, 8, '4. Current Metrics Snapshot', border=0, fill=True)
    pdf.ln(10)

    snapshots = [
        ('Soil', 'Moisture (%)', latest_soil.moisture_content_percent if latest_soil else None),
        ('Soil', 'Field Capacity (%)', latest_soil.field_capacity_percent if latest_soil else None),
        ('Soil', 'Wilting Point (%)', latest_soil.wilting_point_percent if latest_soil else None),
        ('Soil', 'Sand Ratio', latest_soil.sand_ratio if latest_soil else None),
        ('Soil', 'Clay Ratio', latest_soil.clay_ratio if latest_soil else None),
        ('Soil', 'Organic Matter (%)', latest_soil.organic_matter_percent if latest_soil else None),
        ('Climate', 'Rainfall (mm)', latest_climate.rainfall_mm if latest_climate else None),
        ('Climate', 'Max Temperature (C)', latest_climate.temperature_max_c if latest_climate else None),
        ('Climate', 'Min Temperature (C)', latest_climate.temperature_min_c if latest_climate else None),
        ('Climate', 'Mean Temperature (C)', latest_climate.temperature_mean_c if latest_climate else None),
        ('Climate', 'Humidity (%)', latest_climate.relative_humidity_percent if latest_climate else None),
        ('Climate', 'Wind Speed (m/s)', latest_climate.wind_speed_ms if latest_climate else None),
        ('Climate', 'ET0 (mm/day)', latest_climate.evapotranspiration_et0_mmday if latest_climate else None),
        ('Climate', 'ETc (mm/day)', latest_climate.evapotranspiration_etc_mmday if latest_climate else None),
        ('Drought Indices', 'SPI (1-month)', latest_di.spi_1month if latest_di else None),
        ('Drought Indices', 'SPEI (1-month)', latest_di.spei_1month if latest_di else None),
        ('Drought Indices', 'PDSI', latest_di.pdsi_value if latest_di else None),
        ('Remote Sensing', 'NDVI', latest_rs.ndvi if latest_rs else None),
        ('Remote Sensing', 'LST (C)', latest_rs.land_surface_temperature_c if latest_rs else None),
        ('Remote Sensing', 'Satellite SM (%)', latest_rs.satellite_soil_moisture_percent if latest_rs else None),
        ('Hydrology', 'Precipitation (mm)', latest_hydro.precipitation_mm if latest_hydro else None),
        ('Hydrology', 'Groundwater Depth (m)', latest_hydro.groundwater_depth_m if latest_hydro else None),
        ('Hydrology', 'Runoff (mm)', latest_hydro.runoff_mm if latest_hydro else None),
        ('Hydrology', 'River Flow (m3/s)', latest_hydro.river_flow_m3s if latest_hydro else None),
        ('Agriculture', 'Growth Stage', latest_agri.growth_stage.name if latest_agri and hasattr(latest_agri.growth_stage, 'name') else (latest_agri.growth_stage if latest_agri else None)),
        ('Agriculture', 'Crop Coefficient (Kc)', latest_agri.crop_coefficient_kc if latest_agri else None),
        ('Agriculture', 'Water Requirement (mm/day)', latest_agri.crop_water_requirement_mmday if latest_agri else None),
        ('Agriculture', 'Yield Reduction Factor', latest_agri.yield_reduction_factor if latest_agri else None),
    ]

    pdf.set_font('Helvetica', 'B', 9)
    pdf.set_fill_color(200, 215, 240)
    sc_w = [w * 0.22, w * 0.52, w * 0.26]
    for i, h in enumerate(['Category', 'Metric', 'Value']):
        pdf.cell(sc_w[i], 7, h, border=1, fill=True, align='C')
    pdf.ln()

    pdf.set_font('Helvetica', '', 8)
    for i, (cat, metric, val) in enumerate(snapshots):
        fill = (i % 2 == 0)
        if fill:
            pdf.set_fill_color(245, 248, 252)
        pdf.cell(sc_w[0], 5, f'  {cat}', border=1, fill=fill)
        pdf.cell(sc_w[1], 5, f'  {metric}', border=1, fill=fill)
        pdf.cell(sc_w[2], 5, _fmt(val), border=1, fill=fill, align='C')
        pdf.ln()

    pdf.ln(6)

    pdf.set_font('Helvetica', 'B', 13)
    pdf.set_fill_color(230, 240, 255)
    pdf.cell(w, 8, '5. Daily Time Series Data', border=0, fill=True)
    pdf.ln(10)

    pdf.set_font('Helvetica', '', 10)
    pdf.multi_cell(w, 6, 'The full daily time series with all metric columns and risk scores is included in the attached CSV file (same filename with .csv extension).', border=0)
    pdf.ln(4)

    pdf.set_font('Helvetica', 'I', 8)
    pdf.cell(w, 5, f'Generated by ABC Basin Drought Early Warning System on {today_str}', align='C')

    buffer = BytesIO()
    pdf.output(buffer)
    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    fname = f'analysis_{region.name.lower()}_{year.label.split()[0]}'
    response['Content-Disposition'] = f'attachment; filename="{fname}.pdf"'
    return response


def calculations_view(request):
    """Display calculated metrics, formulas, and custom chart builder."""
    rid = request.GET.get('region_id')
    region = get_object_or_404(Region, pk=rid) if rid else Region.objects.filter(name='Bizerte').first() or Region.objects.first()
    snap_date = request.GET.get('snap_date')

    def _latest_with_date(model_cls, region, snap_date):
        filters = {'region': region}
        if snap_date:
            filters['measurement_date__lte'] = snap_date
        return model_cls.objects.filter(**filters).order_by('-measurement_date').first()

    latest_soil = _latest_with_date(SoilMetrics, region, snap_date)
    latest_climate = _latest_with_date(ClimateMetrics, region, snap_date)
    latest_di = _latest_with_date(DroughtIndices, region, snap_date)
    latest_rs = _latest_with_date(RemoteSensingMetrics, region, snap_date)
    latest_hydro = _latest_with_date(HydrologyMetrics, region, snap_date)
    latest_agri = _latest_with_date(AgriculturalMetrics, region, snap_date)

    def _f(v):
        if v is None:
            return '—'
        if isinstance(v, Decimal):
            return round(float(v), 2)
        return v

    mean_temp = None
    if latest_climate and latest_climate.temperature_max_c is not None and latest_climate.temperature_min_c is not None:
        try:
            mean_temp = round((float(latest_climate.temperature_max_c) + float(latest_climate.temperature_min_c)) / 2.0, 2)
        except Exception:
            mean_temp = None

    awc = None
    awc_formula_parts = []
    if latest_soil:
        fc = latest_soil.field_capacity_percent
        wp = latest_soil.wilting_point_percent
        rz = latest_soil.root_zone_depth_mm
        if fc is not None and wp is not None and rz:
            try:
                fc_f = float(fc)
                wp_f = float(wp)
                awc = round(((fc_f - wp_f) / 100.0) * float(rz), 2)
                awc_formula_parts = [f'FC={fc_f}%', f'WP={wp_f}%', f'RZ={rz}mm', f'({fc_f}-{wp_f})/100×{rz}={awc}mm']
            except Exception:
                pass

    soil_water_deficit = None
    if latest_soil and latest_climate:
        sm = latest_soil.moisture_content_percent
        fc_v = latest_soil.field_capacity_percent
        if sm is not None and fc_v is not None and float(fc_v) > 0:
            soil_water_deficit = round(max(0, 100 - (float(sm) / float(fc_v) * 100)), 2)

    et_def_calc = None
    if latest_climate and latest_agri:
        et0 = latest_climate.evapotranspiration_et0_mmday
        kc = latest_agri.crop_coefficient_kc
        if et0 is not None and kc is not None:
            et_def_calc = f'{_f(et0)} × {_f(kc)} = {round(float(et0)*float(kc), 2)} mm/day'

    calc_sections = [
        {
            'category': 'Soil',
            'items': [
                {'name': 'Field Capacity (%)',  'formula': 'Saxton & Rawls PTF: 0.28 + 0.57×clay − 0.24×sand', 'value': _f(latest_soil.field_capacity_percent if latest_soil else None)},
                {'name': 'Wilting Point (%)',   'formula': 'Saxton & Rawls PTF: 0.06 + 0.42×clay − 0.07×sand', 'value': _f(latest_soil.wilting_point_percent if latest_soil else None)},
                {'name': 'AWC (mm)',             'formula': awc_formula_parts[3] if awc_formula_parts else '(FC − WP)/100 × Root Zone Depth', 'value': _f(awc)},
                {'name': 'Soil Water Deficit (%)','formula': 'max(0, 100 − (SM/FC × 100))', 'value': _f(soil_water_deficit)},
                {'name': 'Organic Matter (%)',   'formula': 'Loss on ignition (LOI) method', 'value': _f(latest_soil.organic_matter_percent if latest_soil else None)},
                {'name': 'Infiltration (mm/hr)', 'formula': 'Double-ring infiltrometer or PTF from texture', 'value': _f(latest_soil.infiltration_rate_mmhr if latest_soil else None)},
            ]
        },
        {
            'category': 'Climate',
            'items': [
                {'name': 'Mean Temp (°C)',       'formula': f'({_f(latest_climate.temperature_max_c if latest_climate else None)} + {_f(latest_climate.temperature_min_c if latest_climate else None)}) ÷ 2', 'value': _f(mean_temp)},
                {'name': 'ET₀ (mm/day)',          'formula': 'Penman-Monteith FAO-56: (0.408ΔRn + γ·(900/(T+273))·U₂·(es−ea)) / (Δ+γ(1+0.34U₂))', 'value': _f(latest_climate.evapotranspiration_et0_mmday if latest_climate else None)},
                {'name': 'ETc (mm/day)',          'formula': f'ET₀ × Kc: {et_def_calc or "ET₀ × Kc (FAO-56 lookup)"}', 'value': _f(latest_climate.evapotranspiration_etc_mmday if latest_climate else None)},
                {'name': 'Rainfall (mm)',         'formula': 'Station / satellite measurement (CHIRPS, gauge)', 'value': _f(latest_climate.rainfall_mm if latest_climate else None)},
                {'name': 'Humidity (%)',          'formula': 'Station measurement (DHT22 / hygrometer)', 'value': _f(latest_climate.relative_humidity_percent if latest_climate else None)},
                {'name': 'Wind Speed (m/s)',      'formula': 'Station measurement (anemometer)', 'value': _f(latest_climate.wind_speed_ms if latest_climate else None)},
            ]
        },
        {
            'category': 'Drought Indices',
            'items': [
                {'name': 'SPI (1-month)',         'formula': 'Gamma(α,β) fitted to 30d rainfall → inverse normal CDF', 'value': _f(latest_di.spi_1month if latest_di else None)},
                {'name': 'SPI (3-month)',         'formula': 'Gamma(α,β) fitted to 90d rainfall → inverse normal CDF', 'value': _f(latest_di.spi_3month if latest_di else None)},
                {'name': 'SPI (12-month)',        'formula': 'Gamma(α,β) fitted to 365d rainfall → inverse normal CDF', 'value': _f(latest_di.spi_12month if latest_di else None)},
                {'name': 'SPEI (1-month)',        'formula': 'Water balance (P − ET₀) anomaly ÷ historical σ', 'value': _f(latest_di.spei_1month if latest_di else None)},
                {'name': 'PDSI',                  'formula': 'Palmer model: soil water balance with climatic coefficient', 'value': _f(latest_di.pdsi_value if latest_di else None)},
            ]
        },
        {
            'category': 'Remote Sensing',
            'items': [
                {'name': 'NDVI',                  'formula': '(NIR − Red) / (NIR + Red)', 'value': _f(latest_rs.ndvi if latest_rs else None)},
                {'name': 'LST (°C)',              'formula': 'Split-window algorithm from TIR bands', 'value': _f(latest_rs.land_surface_temperature_c if latest_rs else None)},
                {'name': 'Satellite SM (%)',      'formula': 'SMAP L-band radiometer (0-5 cm depth)', 'value': _f(latest_rs.satellite_soil_moisture_percent if latest_rs else None)},
                {'name': 'VCI (%)',               'formula': '(NDVI − NDVI_min) / (NDVI_max − NDVI_min) × 100', 'value': _f(latest_rs.vegetation_condition_index if latest_rs else None)},
            ]
        },
        {
            'category': 'Hydrology',
            'items': [
                {'name': 'Precipitation (mm)',    'formula': 'Station / CHIRPS measurement', 'value': _f(latest_hydro.precipitation_mm if latest_hydro else None)},
                {'name': 'Groundwater Depth (m)', 'formula': 'Well measurement / piezometer', 'value': _f(latest_hydro.groundwater_depth_m if latest_hydro else None)},
                {'name': 'Runoff (mm)',            'formula': 'SCS-CN: Q = (P−0.2S)²/(P+0.8S) with S=(25400/CN)−254', 'value': _f(latest_hydro.runoff_mm if latest_hydro else None)},
                {'name': 'River Flow (m³/s)',     'formula': 'Stage-discharge rating curve (Q = a·h^b)', 'value': _f(latest_hydro.river_flow_m3s if latest_hydro else None)},
                {'name': 'Water Balance (%)',     'formula': '(Supply − Demand) / Demand × 100', 'value': _f(latest_hydro.water_balance_percent if latest_hydro else None)},
            ]
        },
        {
            'category': 'Agriculture',
            'items': [
                {'name': 'Crop Coeff. (Kc)',      'formula': 'FAO-56 growth-stage lookup table', 'value': _f(latest_agri.crop_coefficient_kc if latest_agri else None)},
                {'name': 'CWR (mm/day)',           'formula': 'ETc = ET₀ × Kc', 'value': _f(latest_agri.crop_water_requirement_mmday if latest_agri else None)},
                {'name': 'Yield Reduction (0-1)',  'formula': '1 − (actual / potential) yield', 'value': _f(latest_agri.yield_reduction_factor if latest_agri else None)},
                {'name': 'Irrigation Efficiency (%)','formula': 'Applied water beneficially used ÷ total applied', 'value': _f(latest_agri.irrigation_efficiency_percent if latest_agri else None)},
            ]
        },
    ]

    context = {
        'regions': Region.objects.all(),
        'years': ObservationYear.objects.all(),
        'calc_sections': calc_sections,
        'metrics_json': json.dumps([{'key': k, 'label': f'{cat} – {lbl}', 'model': m, 'field': f, 'unit': u, 'category': cat} for k, m, f, lbl, u, cat in METRICS_REGISTRY if m is not None]),
        'selected_region': region,
        'snap_date': snap_date or '',
    }
    return render(request, 'dashboard/calculations.html', context)


def calculations_chart_api(request):
    """Return time-series data for a chosen metric + region + date range."""
    region_id = request.GET.get('region_id')
    metric = request.GET.get('metric')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    if not all([region_id, metric]):
        return JsonResponse({'error': 'region_id and metric required'}, status=400)

    region = get_object_or_404(Region, pk=region_id)

    reg_entry = None
    for entry in METRICS_REGISTRY:
        if entry[0] == metric:
            reg_entry = entry
            break
    if not reg_entry:
        return JsonResponse({'error': f'Unknown metric: {metric}'}, status=400)

    _key, model_name, field_name, label, unit, cat = reg_entry

    if model_name is None:
        return JsonResponse({'error': 'Derived metrics not available as time-series'}, status=400)

    model_cls = MODEL_MAP[model_name]

    filters = {'region': region}
    if date_from:
        filters['measurement_date__gte'] = date_from
    if date_to:
        filters['measurement_date__lte'] = date_to

    qs = model_cls.objects.filter(**filters).order_by('measurement_date').values('measurement_date', field_name)

    dates = []
    values = []
    for row in qs:
        v = row[field_name]
        if v is not None:
            if isinstance(v, Decimal):
                v = float(v)
            dates.append(row['measurement_date'].isoformat() if hasattr(row['measurement_date'], 'isoformat') else str(row['measurement_date']))
            values.append(v)

    return JsonResponse({
        'metric': metric,
        'label': label,
        'unit': unit,
        'category': cat,
        'dates': dates,
        'values': values,
    })


def calculations_data(request):
    """Return sample time-series data for calculations charts (JSON)."""
    from datetime import datetime, timedelta

    today = datetime.utcnow().date()
    dates = [(today - timedelta(days=i)).isoformat() for i in reversed(range(7))]

    soil_awc = [100, 98, 96, 95, 94, 93, 92]
    climate_temp = [22.1, 22.5, 23.0, 24.2, 25.0, 24.7, 24.5]
    climate_et0 = [3.5, 3.8, 4.0, 4.1, 4.3, 4.0, 4.2]
    drought_spi1 = [-0.2, -0.3, -0.4, -0.6, -0.8, -0.9, -1.0]

    payload = {
        'dates': dates,
        'soil': {
            'labels': dates,
            'awc_mm': soil_awc,
        },
        'climate': {
            'labels': dates,
            'temperature_c': climate_temp,
            'et0_mm_day': climate_et0,
        },
        'drought': {
            'labels': dates,
            'spi1': drought_spi1,
        }
    }
    return JsonResponse(payload)


def drought_prediction_api(request):
    """Return the latest drought prediction or generate a fresh one on demand."""
    region_id = request.GET.get('region_id')
    year_id = request.GET.get('year_id')
    refresh = request.GET.get('refresh', '0').lower() in {'1', 'true', 'yes', 'on'}
    use_llm = request.GET.get('use_llm', '0').lower() in {'1', 'true', 'yes', 'on'}

    region = None
    year = None
    if region_id:
        region = get_object_or_404(Region, pk=region_id)
    else:
        region = Region.objects.filter(name="Bizerte").first() or Region.objects.order_by('name').first()
    if year_id:
        year = get_object_or_404(ObservationYear, pk=year_id)
    else:
        year = ObservationYear.objects.order_by('-label').first()

    if region is None or year is None:
        return JsonResponse({'success': False, 'error': 'Region and year are required.'}, status=400)

    latest_prediction = DroughtPrediction.objects.filter(region=region, year=year).order_by('-generated_at').first()
    if latest_prediction is None:
        latest_prediction = DroughtPrediction.objects.filter(region=region).order_by('-generated_at').first()
    _fc_soil = SoilMetrics.objects.filter(region=region, field_capacity_percent__isnull=False).order_by('-measurement_date').first()
    _fc = float(_fc_soil.field_capacity_percent) if _fc_soil and _fc_soil.field_capacity_percent else 30.0
    stations_data = _get_region_stations(region, year)
    if latest_prediction and not refresh:
        sm_today = float(latest_prediction.soil_moisture_today_pct or 0)
        sm_7 = float(latest_prediction.soil_moisture_7day_pct or 0)
        sm_30 = float(latest_prediction.soil_moisture_30day_pct or 0)
        return JsonResponse({
            'success': True,
            'source': 'database',
            'prediction': {
                'region': region.name,
                'year': year.label,
                'generated_at': latest_prediction.generated_at,
                'stations': stations_data,
                'risk_scores': {
                    'today': float(latest_prediction.current_risk_score),
                    'day_7': float(latest_prediction.risk_7day),
                    'day_30': float(latest_prediction.risk_30day),
                },
                'current': {
                    'soil_moisture_pct': sm_today,
                    'soil_water_percent_of_capacity': round(min(100, (sm_today / _fc) * 100), 1) if sm_today and _fc > 0 else 0,
                },
                'forecasts': {
                    'soil_moisture_7day_pct': sm_7,
                    'soil_moisture_30day_pct': sm_30,
                },
                'drivers': latest_prediction.drivers,
                'llm_explanation': latest_prediction.explanation,
                'warning': _prediction_warning_block(latest_prediction.validation_metrics),
                'rainfall_forecast': {
                    'source': latest_prediction.rainfall_forecast.get('source'),
                    'n_forecast_days': latest_prediction.rainfall_forecast.get('n_forecast_days'),
                    'rain_7d_mm': float(latest_prediction.forecast_rain_7d_mm) if latest_prediction.forecast_rain_7d_mm is not None else None,
                    'rain_30d_mm': float(latest_prediction.forecast_rain_30d_mm) if latest_prediction.forecast_rain_30d_mm is not None else None,
                },
            },
        })

    try:
        from ..prediction_engine.pipeline import DroughtPredictionPipeline

        pipeline = DroughtPredictionPipeline()
        result = pipeline.predict_for_region(region, year, use_llm=use_llm)
        saved_prediction = pipeline.save_prediction(
            region, year, result,
            validation_metrics=pipeline.validation_metrics,
        )

        return JsonResponse({
            'success': True,
            'source': 'generated',
            'prediction_id': saved_prediction.id,
            'prediction': {
                'region': region.name,
                'year': year.label,
                'generated_at': saved_prediction.generated_at,
                'stations': stations_data,
                'risk_scores': result['risk_scores'],
                'current': result['current'],
                'forecasts': result['forecasts'],
                'drivers': result['drivers'],
                'llm_explanation': result['llm_explanation'],
                'warning': result.get('warning') or _prediction_warning_block(saved_prediction.validation_metrics),
                'rainfall_forecast': result.get('rainfall_forecast', {}),
            },
        })
    except Exception as exc:
        logger.warning('Prediction generation failed: %s', exc)
        if latest_prediction is not None:
            sm_today = float(latest_prediction.soil_moisture_today_pct or 0)
            return JsonResponse({
                'success': True,
                'source': 'database',
                'warning': 'Fresh prediction unavailable, showing cached results.',
                'prediction': {
                    'region': region.name,
                    'year': year.label,
                    'generated_at': latest_prediction.generated_at,
                    'risk_scores': {
                        'today': float(latest_prediction.current_risk_score),
                        'day_7': float(latest_prediction.risk_7day),
                        'day_30': float(latest_prediction.risk_30day),
                    },
                    'current': {
                        'soil_moisture_pct': sm_today,
                        'soil_water_percent_of_capacity': round(min(100, (sm_today / _fc) * 100), 1) if sm_today and _fc > 0 else 0,
                    },
                    'forecasts': {
                        'soil_moisture_7day_pct': float(latest_prediction.soil_moisture_7day_pct or 0),
                        'soil_moisture_30day_pct': float(latest_prediction.soil_moisture_30day_pct or 0),
                    },
                    'drivers': latest_prediction.drivers,
                    'llm_explanation': latest_prediction.explanation,
                    'warning': _prediction_warning_block(latest_prediction.validation_metrics),
                    'rainfall_forecast': {
                        'source': latest_prediction.rainfall_forecast.get('source'),
                        'n_forecast_days': latest_prediction.rainfall_forecast.get('n_forecast_days'),
                        'rain_7d_mm': float(latest_prediction.forecast_rain_7d_mm) if latest_prediction.forecast_rain_7d_mm is not None else None,
                        'rain_30d_mm': float(latest_prediction.forecast_rain_30d_mm) if latest_prediction.forecast_rain_30d_mm is not None else None,
                    },
                },
            })
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


# ============== SPEI FORECAST API ==============
@require_http_methods(['GET'])
def spei_forecast_api(request):
    """Return the latest monthly SPEI drought outlook for a region.

    GET /api/spei-forecast/?region=<id>
    (without ?region= returns the most recent forecast for any region)
    """
    from ..models import SpeiForecast

    region_id = request.GET.get('region')
    qs = SpeiForecast.objects.select_related('region')
    if region_id:
        qs = qs.filter(region_id=region_id)
    forecast = qs.first()
    if forecast is None:
        return JsonResponse(
            {'error': 'No SPEI forecast available. Run: python manage.py train_spei_models'},
            status=404,
        )
    vm = forecast.validation_metrics or {}
    warning = vm.get('warning_t1')
    if warning is None:
        warning, _ = drought_warning(forecast.prob_drought_t1,
                                     forecast.spei_t1)
    band_key, band_label = drought_probability_band(forecast.prob_drought_t1)

    return JsonResponse({
        'region': forecast.region.name,
        'region_id': forecast.region_id,
        'generated_at': forecast.generated_at,
        'feature_month': forecast.feature_month,
        'forecast': {
            't1': {
                'target_month': forecast.target_month_t1,
                'spei': float(forecast.spei_t1) if forecast.spei_t1 is not None else None,
                'prob_drought': forecast.prob_drought_t1,
                'risk_score': forecast.score_t1,
                'risk_level': forecast.level_t1,
                'recommendations': forecast.recommendations_t1,
                'warning': bool(warning),
                'warning_source': vm.get('warning_source'),
                'probability_band': band_key,
                'probability_label': band_label,
                'months_behind_today': vm.get('months_behind_today'),
            },
            't3': {
                'target_month': forecast.target_month_t3,
                'spei': float(forecast.spei_t3) if forecast.spei_t3 is not None else None,
                'prob_drought': forecast.prob_drought_t3,
                'risk_score': forecast.score_t3,
                'risk_level': forecast.level_t3,
                'recommendations': forecast.recommendations_t3,
            },
        },
        'top_drivers': forecast.top_drivers,
        'validation_metrics': forecast.validation_metrics,
        'model_version': forecast.model_version,
    })


# ============== SPEI OUTLOOK PAGE ==============
def spei_outlook_view(request):
    """SPEI drought outlook page: latest per-region forecast + live
    verification scoreboard (predicted vs what actually happened)."""
    from ..models import Region, SpeiForecast, SpeiVerification

    forecasts = []
    for region in Region.objects.filter(latitude__isnull=False).order_by('name'):
        fc = SpeiForecast.objects.filter(region=region).first()
        if not fc:
            continue
        vm = fc.validation_metrics or {}
        warned = vm.get('warning_t1')
        if warned is None:
            warned, warn_source = drought_warning(fc.prob_drought_t1, fc.spei_t1)
        else:
            warn_source = vm.get('warning_source')
        band_key, band_label = drought_probability_band(fc.prob_drought_t1)
        fc.warning_t1 = bool(warned)
        fc.warning_source = warn_source
        fc.band_t1 = band_key
        fc.band_label_t1 = band_label
        fc.months_behind = vm.get('months_behind_today')
        fc.stale = (fc.months_behind or 0) > MAX_FORECAST_LAG_MONTHS
        forecasts.append(fc)

    verifications = list(SpeiVerification.objects.select_related('region')
                         .order_by('-target_month')[:30])
    total = SpeiVerification.objects.count()
    events = list(SpeiVerification.objects.filter(drought_actual=True))
    caught = sum(1 for v in events if v.flag_correct)
    exact = SpeiVerification.objects.filter(level_exact=True).count()
    stats = {
        'total': total,
        'events': len(events),
        'caught': caught,
        'recall_pct': round(100 * caught / len(events)) if events else None,
        'exact_pct': round(100 * exact / total) if total else None,
    }
    stale_months = max((f.months_behind or 0) for f in forecasts) if forecasts else 0
    if stale_months <= MAX_FORECAST_LAG_MONTHS:
        stale_months = 0
    return render(request, 'dashboard/spei_outlook.html',
                  {'forecasts': forecasts, 'verifications': verifications,
                   'stats': stats, 'stale_months': stale_months})


# ============== FARMER ASSISTANT PAGE ==============
def assistant_page_view(request):
    """Farmer assistant chat page (advice grounded in live SPEI data)."""
    from ..models import Region

    regions = Region.objects.filter(latitude__isnull=False).order_by('name')
    return render(request, 'dashboard/assistant.html', {'regions': regions})


# ============== FARMER ASSISTANT API ==============
@require_http_methods(['GET', 'POST'])
def assistant_chat_api(request):
    """Farmer assistant chat endpoint.

    POST JSON: {"question": str, "region_id": int?, "crop": str?, "lang": "en|fr|ar",
                "history": [{role, content}]?, "conversation": {crop, region_name, intent}?}
    Returns:   {answer, intent, crop, region, from_cache, facts, sources, understood}
    """
    import json as _json
    from ..services.farmer_assistant import get_assistant_answer, suggestions

    if request.method == 'GET':
        lang = request.GET.get('lang', 'en')
        return JsonResponse({'suggestions': suggestions(lang)})

    try:
        payload = _json.loads(request.body or b'{}')
    except Exception:
        payload = {}
    question = (payload.get('question') or '').strip()
    if not question:
        return JsonResponse({'error': 'question is required'}, status=400)
    lang = payload.get('lang') or request.LANGUAGE_CODE or 'en'
    region_id = payload.get('region_id')
    crop = payload.get('crop')
    history = payload.get('history') or []
    conversation = payload.get('conversation') or None

    result = get_assistant_answer(question, region_id=region_id, crop=crop,
                                  lang=lang, use_llm=True, history=history,
                                  conversation=conversation)
    if not result.get('suggestions'):
        result['suggestions'] = suggestions(lang)
    return JsonResponse(result)
