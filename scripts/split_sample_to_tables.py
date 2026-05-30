"""Split the wide synthetic CSV into per-table CSVs matching simplified DB schema.
Outputs files to `scripts/output_tables/`.
"""
from __future__ import annotations

from pathlib import Path
import pandas as pd


TABLE_MAP = {
    'regions': ['region_id', 'region_name', 'region_country', 'region_latitude', 'region_longitude', 'region_elevation_m', 'region_area_km2', 'region_description'],
    'observation_years': ['year_id', 'year_label', 'year_start_date', 'year_end_date', 'year_season'],
    'crop_types': ['crop_id', 'crop_name', 'scientific_name', 'crop_family', 'water_requirement_mm_season', 'growing_period_days', 'crop_description'],
    'irrigation_methods': ['irrigation_id', 'irrigation_name', 'irrigation_efficiency_percent_dim', 'water_application_uniformity', 'irrigation_description'],
    'environmental_snapshots': ['time', 'region_id', 'year_id', 'wind_speed_kmh', 'wind_gust_kmh', 'wind_direction', 'rainfall_mm', 'rainfall_delta_percent', 'ph_level', 'npk_index', 'temperature_c', 'humidity_percent', 'updated_at'],
    'soil_metrics': ['time', 'region_id', 'year_id', 'moisture_content_percent', 'sand_ratio', 'clay_ratio', 'silt_ratio', 'root_zone_depth_mm', 'organic_matter_percent', 'infiltration_rate_mmhr', 'field_capacity_percent', 'wilting_point_percent', 'salinity_ece_dsm', 'soil_ph_level', 'updated_at'],
    'climate_metrics': ['time', 'region_id', 'year_id', 'rainfall_mm', 'seasonal_rainfall_variability', 'temperature_max_c', 'temperature_min_c', 'temperature_mean_c', 'relative_humidity_percent', 'wind_speed_ms', 'solar_radiation_mjm2day', 'evapotranspiration_et0_mmday', 'evapotranspiration_etc_mmday', 'updated_at'],
    'drought_indices': ['time', 'region_id', 'year_id', 'spi_1month', 'spi_3month', 'spi_12month', 'spei_1month', 'spei_3month', 'spei_12month', 'pdsi_value', 'drought_severity_class', 'updated_at'],
    'agricultural_metrics': ['time', 'region_id', 'year_id', 'crop_id', 'growth_stage', 'crop_coefficient_kc', 'crop_water_requirement_mmday', 'yield_reduction_factor', 'irrigation_id', 'irrigation_efficiency_percent', 'water_applied_mm', 'leaf_temperature_c', 'stomatal_conductance', 'updated_at'],
    'remote_sensing_metrics': ['time', 'region_id', 'year_id', 'ndvi', 'ndwi', 'land_surface_temperature_c', 'satellite_soil_moisture_percent', 'satellite_source', 'vegetation_condition_index', 'evapotranspiration_sebal_mmday', 'updated_at'],
    'hydrology_metrics': ['time', 'region_id', 'year_id', 'precipitation_mm', 'evapotranspiration_mm', 'groundwater_depth_m', 'runoff_mm', 'river_flow_m3s', 'reservoir_storage_m3', 'irrigation_supply_available_m3', 'soil_water_deficit_index_mm', 'water_balance_percent', 'updated_at'],
    'risk_assessments': ['time', 'region_id', 'year_id', 'crop_id', 'irrigation_id', 'risk_level', 'risk_score', 'recommendation', 'factors', 'created_at'],
}


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--input', default='scripts/sample_drought_large.csv')
    parser.add_argument('--outdir', default='scripts/output_tables')
    args = parser.parse_args()

    p = Path(args.outdir)
    p.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(args.input, parse_dates=['time', 'created_at', 'updated_at', 'year_start_date', 'year_end_date'], low_memory=False)

    # Create dimension tables (deduplicate)
    for table, cols in TABLE_MAP.items():
        available = [c for c in cols if c in df.columns]
        if not available:
            continue
        sub = df[available].copy()
        if table in ('regions', 'observation_years', 'crop_types', 'irrigation_methods'):
            sub = sub.drop_duplicates().reset_index(drop=True)
        out = p / f'{table}.csv'
        sub.to_csv(out, index=False)
        print(f'Wrote {len(sub)} rows to {out}')


if __name__ == '__main__':
    main()
