from __future__ import annotations

from pathlib import Path
import argparse

import numpy as np
import pandas as pd


def generate_sample_drought_data(
    days: int = 180,
    seed: int = 42,
    region_id: int = 1,
    year_id: int = 1,
    crop_id: int = 1,
    irrigation_id: int = 1,
    end_date: str | None = None,
) -> pd.DataFrame:
    """Generate a realistic synthetic drought dataset covering the modeled columns."""
    rng = np.random.default_rng(seed)
    if end_date is None:
        dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=days, freq='D')
    else:
        dates = pd.date_range(end=pd.to_datetime(end_date), periods=days, freq='D')

    trend = np.linspace(0, 1, days)
    rainfall = np.clip(rng.gamma(shape=0.8, scale=2.2, size=days) - trend * 0.7, 0, None)
    irrigation = np.where(rng.random(days) < 0.12, rng.uniform(2, 10, size=days), 0)

    temp_max = 28 + trend * 5 + rng.normal(0, 1.1, days)
    temp_min = 16 + trend * 2.5 + rng.normal(0, 0.8, days)
    temp_mean = (temp_max + temp_min) / 2
    humidity = np.clip(72 - trend * 12 + rng.normal(0, 3, days), 30, 95)
    wind_speed_ms = np.clip(3.0 + rng.normal(0, 0.4, days), 0.5, 8)
    wind_speed_kmh = wind_speed_ms * 3.6
    wind_gust_kmh = np.clip(wind_speed_kmh + rng.uniform(5, 18, size=days), 0, None)
    wind_direction = np.array(['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'])[rng.integers(0, 8, size=days)]
    solar_radiation_wm2 = np.clip(240 + trend * 45 + rng.normal(0, 12, days), 140, 380)
    solar_radiation_mjm2day = solar_radiation_wm2 * 0.0864

    ndvi = np.clip(0.75 - trend * 0.18 + rng.normal(0, 0.015, days), 0.2, 0.85)
    ndwi = np.clip(0.2 + (rainfall / (rainfall.max() + 1e-8)) * 0.5 + rng.normal(0, 0.02, days), -0.2, 0.6)
    lst_c = np.clip(26 + trend * 4 + rng.normal(0, 0.7, days), 18, 42)
    satellite_sm = np.clip(30 + trend * -6 + rng.normal(0, 2.0, days), 0, 60)
    vci = ((ndvi - ndvi.min()) / (ndvi.max() - ndvi.min() + 1e-8)) * 100

    soil_moisture = np.empty(days)
    soil_water = np.empty(days)
    et0 = np.empty(days)
    etc_mm = np.empty(days)
    soil_moisture[0] = 34.0
    soil_water[0] = 180.0

    for idx in range(days):
        es = 0.6108 * np.exp(17.27 * temp_mean[idx] / (temp_mean[idx] + 237.3))
        ea = es * (humidity[idx] / 100)
        vpd = es - ea
        delta = 4098 * es / (temp_mean[idx] + 237.3) ** 2
        psychrometric = 0.000665 * 101.3
        rn = solar_radiation_wm2[idx] * 0.0864
        wind_factor = 0.26 * (1 + 0.54 * wind_speed_ms[idx])
        et0[idx] = max(0, (0.408 * delta * rn + psychrometric * wind_factor * vpd) / (delta + psychrometric))
        etc_mm[idx] = et0[idx] * 1.0

        if idx > 0:
            drought_pull = max(0, 0.65 * (1 - rainfall[idx] / 10) + 0.35 * (temp_max[idx] - 28) / 10)
            recharge = rainfall[idx] * 0.8 + irrigation[idx] * 0.9
            soil_moisture[idx] = np.clip(soil_moisture[idx - 1] + recharge - etc_mm[idx] * 0.25 - drought_pull, 5, 45)
            soil_water[idx] = np.clip(soil_water[idx - 1] + rainfall[idx] + irrigation[idx] - etc_mm[idx] - 0.1, 20, 260)

    rainfall_prev = np.concatenate(([rainfall[0]], rainfall[:-1]))
    rainfall_delta_percent = np.zeros(days)
    np.divide(
        rainfall - rainfall_prev,
        rainfall_prev,
        out=rainfall_delta_percent,
        where=np.abs(rainfall_prev) > 1e-8,
    )
    rainfall_delta_percent *= 100

    spi_1month = np.round((rainfall - rainfall.mean()) / (rainfall.std() + 1e-8), 2)
    rolling_90 = pd.Series(rainfall).rolling(90, min_periods=1).mean().to_numpy()
    spi_3month = np.round((rainfall - rolling_90) / (pd.Series(rainfall).rolling(90, min_periods=1).std().to_numpy() + 1e-8), 2)
    rolling_365 = pd.Series(rainfall).rolling(365, min_periods=1).mean().to_numpy()
    spi_12month = np.round((rainfall - rolling_365) / (pd.Series(rainfall).rolling(365, min_periods=1).std().to_numpy() + 1e-8), 2)
    spei_1month = np.round(spi_1month - 0.15 * (etc_mm - rainfall), 2)
    spei_3month = np.round(spi_3month - 0.12 * (etc_mm - rainfall), 2)
    spei_12month = np.round(spi_12month - 0.1 * (etc_mm - rainfall), 2)
    pdsi_value = np.round(np.clip(spi_3month * 1.2 - (etc_mm - rainfall) * 0.15, -6, 6), 2)

    growth_stage = np.array(['Germination'] * days, dtype=object)
    growth_stage[days // 5 : days // 3] = 'Vegetative'
    growth_stage[days // 3 : days // 2] = 'Flowering'
    growth_stage[days // 2 : int(days * 0.8)] = 'Grain Filling'
    growth_stage[int(days * 0.8) :] = 'Maturity'

    crop_coefficient_kc = np.round(np.clip(0.65 + trend * 0.5 + rng.normal(0, 0.03, days), 0.4, 1.25), 2)
    crop_water_requirement_mmday = np.round(np.clip(etc_mm * crop_coefficient_kc, 0, None), 2)
    yield_reduction_factor = np.round(np.clip(1 - soil_moisture / 60, 0, 1), 3)
    irrigation_efficiency_percent = np.round(np.clip(62 + trend * 22 + rng.normal(0, 4, days), 40, 95), 0)
    water_applied_mm = np.round(irrigation + crop_water_requirement_mmday * 0.35, 2)
    leaf_temperature_c = np.round(temp_max + 1.5 + rng.normal(0, 0.7, days), 1)
    stomatal_conductance = np.round(np.clip(0.45 - trend * 0.22 + rng.normal(0, 0.02, days), 0.05, 0.6), 3)

    groundwater_depth_m = np.round(np.clip(5 + trend * 1.2 + rng.normal(0, 0.4, days), 0.5, 20), 2)
    runoff_mm = np.round(np.clip(rainfall * 0.18 + rng.normal(0, 0.8, days), 0, None), 1)
    river_flow_m3s = np.round(np.clip(10 + rainfall * 2.5 + rng.normal(0, 3.0, days), 0, None), 2)
    reservoir_storage_m3 = np.round(np.clip(5e6 + (rainfall.cumsum() - etc_mm.cumsum()) * 10000 + rng.normal(0, 50000, days), 0, None), 0)
    irrigation_supply_available_m3 = np.round(np.clip(1e5 + irrigation.cumsum() * 5000 + rng.normal(0, 20000, days), 0, None), 0)
    soil_water_deficit_index_mm = np.round(np.clip(etc_mm - rainfall - irrigation * 0.5, -50, 80), 2)
    water_balance_percent = np.round(np.clip(((rainfall + irrigation) / (etc_mm + 1e-8)) * 100, 0, 250), 2)
    evapotranspiration_sebal_mmday = np.round(np.clip(etc_mm * (0.9 + rng.normal(0, 0.05, days)), 0, None), 2)

    ph_level = np.round(np.clip(7.2 - trend * 0.4 + rng.normal(0, 0.1, days), 5.5, 8.3), 1)
    npk_index = np.where(soil_moisture > 30, 'High', np.where(soil_moisture > 20, 'Medium', 'Low'))
    sand_ratio = np.round(np.clip(42 + rng.normal(0, 2.0, days), 30, 65), 2)
    clay_ratio = np.round(np.clip(24 + rng.normal(0, 1.5, days), 10, 45), 2)
    silt_ratio = np.round(np.clip(100 - sand_ratio - clay_ratio, 15, 55), 2)
    root_zone_depth_mm = np.round(np.clip(420 + trend * 60 + rng.normal(0, 10, days), 250, 800), 0)
    organic_matter_percent = np.round(np.clip(2.2 + rng.normal(0, 0.15, days), 1.0, 5.0), 2)
    infiltration_rate_mmhr = np.round(np.clip(12 + rng.normal(0, 1.2, days), 3, 30), 2)
    field_capacity_percent = np.round(np.clip(31 + rng.normal(0, 1.0, days), 20, 45), 2)
    wilting_point_percent = np.round(np.clip(14 + rng.normal(0, 0.8, days), 5, 25), 2)
    salinity_ece_dsm = np.round(np.clip(0.8 + trend * 0.35 + rng.normal(0, 0.05, days), 0.1, 5), 3)
    soil_ph_level = np.round(np.clip(7.0 - trend * 0.3 + rng.normal(0, 0.1, days), 5.5, 8.2), 1)
    moisture_content_percent = np.round(np.clip(soil_moisture + rng.normal(0, 1.0, days), 5, 45), 2)

    seasonal_rainfall_variability = np.where(trend < 0.33, 'Low', np.where(trend < 0.66, 'Moderate', 'High'))
    drought_severity_class = np.where(spi_1month > -0.5, 'None', np.where(spi_1month > -1, 'Abnormally Dry', np.where(spi_1month > -1.5, 'Moderate Drought', np.where(spi_1month > -2, 'Severe Drought', 'Extreme Drought'))))

    risk_score = np.round(np.clip(100 - soil_moisture * 1.8 + (temp_max - 28) * 2 - rainfall * 1.5 + (45 - humidity) * 0.5, 0, 100), 1)
    risk_level = np.where(risk_score < 25, 'Low', np.where(risk_score < 50, 'Moderate', np.where(risk_score < 75, 'High', 'Extreme')))
    recommendation = np.where(
        risk_score < 25,
        'Maintain current irrigation schedule and monitor weekly.',
        np.where(
            risk_score < 50,
            'Increase irrigation monitoring and conserve soil moisture.',
            np.where(risk_score < 75, 'Prioritize irrigation and reduce plant stress.', 'Immediate water conservation and emergency irrigation required.'),
        ),
    )
    factors = [
        '{"rainfall_deficit": %.1f, "soil_moisture": %.1f, "temperature": %.1f}' % (max(0, 20 - rainfall[i]), soil_moisture[i], temp_max[i])
        for i in range(days)
    ]

    created_at = dates + pd.to_timedelta(1, unit='h')
    updated_at = dates + pd.to_timedelta(2, unit='h')

    region_name = 'Test Region Alpha'
    crop_name = 'Wheat'
    irrigation_name = 'Drip Irrigation'
    year_label = str(dates[0].year)
    year_start_date = pd.Timestamp(f'{dates[0].year}-01-01')
    year_end_date = pd.Timestamp(f'{dates[0].year}-12-31')
    year_season = 'Winter'

    df = pd.DataFrame(
        {
            'time': dates,
            'region_id': [region_id] * days,
            'year_id': [year_id] * days,
            'crop_id': [crop_id] * days,
            'irrigation_id': [irrigation_id] * days,
            'region_name': [region_name] * days,
            'region_country': ['Morocco'] * days,
            'region_latitude': np.round(np.full(days, 31.79), 6),
            'region_longitude': np.round(np.full(days, -7.08), 6),
            'region_elevation_m': np.full(days, 450),
            'region_area_km2': np.full(days, 1250.0),
            'region_description': ['Synthetic test region for drought forecasting'] * days,
            'year_label': [year_label] * days,
            'year_start_date': [year_start_date] * days,
            'year_end_date': [year_end_date] * days,
            'year_season': [year_season] * days,
            'crop_name': [crop_name] * days,
            'scientific_name': ['Triticum aestivum'] * days,
            'crop_family': ['Poaceae'] * days,
            'water_requirement_mm_season': np.full(days, 450.0),
            'growing_period_days': np.full(days, 150),
            'crop_description': ['Synthetic wheat sample for model testing'] * days,
            'irrigation_name': [irrigation_name] * days,
            'irrigation_efficiency_percent_dim': np.full(days, 90.0),
            'water_application_uniformity': np.full(days, 95.0),
            'irrigation_description': ['High-efficiency drip irrigation'] * days,

            'wind_speed_kmh': np.round(wind_speed_kmh, 1),
            'wind_gust_kmh': np.round(wind_gust_kmh, 1),
            'wind_direction': wind_direction,
            'rainfall_mm': np.round(rainfall, 1),
            'rainfall_delta_percent': np.round(rainfall_delta_percent, 0),
            'ph_level': ph_level,
            'npk_index': np.where(soil_moisture > 30, 'Med-High', np.where(soil_moisture > 20, 'Medium', 'Low')),
            'temperature_c': np.round(temp_mean, 1),
            'humidity_percent': np.round(humidity, 0),

            'moisture_content_percent': moisture_content_percent,
            'sand_ratio': sand_ratio,
            'clay_ratio': clay_ratio,
            'silt_ratio': silt_ratio,
            'root_zone_depth_mm': root_zone_depth_mm,
            'organic_matter_percent': organic_matter_percent,
            'infiltration_rate_mmhr': infiltration_rate_mmhr,
            'field_capacity_percent': field_capacity_percent,
            'wilting_point_percent': wilting_point_percent,
            'salinity_ece_dsm': salinity_ece_dsm,
            'soil_ph_level': soil_ph_level,

            'seasonal_rainfall_variability': seasonal_rainfall_variability,
            'temperature_max_c': np.round(temp_max, 1),
            'temperature_min_c': np.round(temp_min, 1),
            'temperature_mean_c': np.round(temp_mean, 1),
            'relative_humidity_percent': np.round(humidity, 0),
            'wind_speed_ms': np.round(wind_speed_ms, 2),
            'solar_radiation_mjm2day': np.round(solar_radiation_mjm2day, 2),
            'evapotranspiration_et0_mmday': np.round(et0, 2),
            'evapotranspiration_etc_mmday': np.round(etc_mm, 2),

            'spi_1month': spi_1month,
            'spi_3month': spi_3month,
            'spi_12month': spi_12month,
            'spei_1month': spei_1month,
            'spei_3month': spei_3month,
            'spei_12month': spei_12month,
            'pdsi_value': pdsi_value,
            'drought_severity_class': drought_severity_class,

            'growth_stage': growth_stage,
            'crop_coefficient_kc': crop_coefficient_kc,
            'crop_water_requirement_mmday': crop_water_requirement_mmday,
            'yield_reduction_factor': yield_reduction_factor,
            'irrigation_method_name': ['Drip Irrigation'] * days,
            'irrigation_efficiency_percent': irrigation_efficiency_percent,
            'water_applied_mm': water_applied_mm,
            'leaf_temperature_c': leaf_temperature_c,
            'stomatal_conductance': stomatal_conductance,

            'ndvi': np.round(ndvi, 3),
            'ndwi': np.round(ndwi, 3),
            'land_surface_temperature_c': np.round(lst_c, 2),
            'lst_c': np.round(lst_c, 2),
            'satellite_soil_moisture_percent': np.round(satellite_sm, 2),
            'satellite_source': ['MODIS'] * days,
            'vegetation_condition_index': np.round(vci, 2),
            'evapotranspiration_sebal_mmday': evapotranspiration_sebal_mmday,

            'precipitation_mm': np.round(rainfall, 1),
            'evapotranspiration_mm': np.round(etc_mm, 1),
            'groundwater_depth_m': groundwater_depth_m,
            'runoff_mm': runoff_mm,
            'river_flow_m3s': river_flow_m3s,
            'reservoir_storage_m3': reservoir_storage_m3,
            'irrigation_supply_available_m3': irrigation_supply_available_m3,
            'soil_water_deficit_index_mm': soil_water_deficit_index_mm,
            'water_balance_percent': water_balance_percent,

            'risk_level': risk_level,
            'risk_score': risk_score,
            'recommendation': recommendation,
            'factors': factors,

            # Pipeline-friendly aliases and helpers
            'soil_moisture_pct': np.round(soil_moisture, 2),
            'irrigation_mm': np.round(irrigation, 2),
            'temp_max_c': np.round(temp_max, 2),
            'temp_min_c': np.round(temp_min, 2),
            'humidity_pct': np.round(humidity, 2),
            'wind_speed_ms_daily': np.round(wind_speed_ms, 2),
            'solar_radiation_wm2': np.round(solar_radiation_wm2, 2),
            'etc_mm': np.round(etc_mm, 2),
            'soil_water_mm': np.round(soil_water, 2),
            'spi': spi_1month,
            'crop_type': ['wheat'] * days,
            'days_since_planting': np.arange(1, days + 1),
            'created_at': created_at,
            'updated_at': updated_at,
        }
    )

    return df


def main() -> None:
    parser = argparse.ArgumentParser(description='Generate synthetic drought data')
    parser.add_argument('--n-regions', type=int, default=1, help='Number of regions to synthesize')
    parser.add_argument('--years-per-region', type=int, default=1, help='Years per region')
    parser.add_argument('--days-per-year', type=int, default=180, help='Days per year/series')
    parser.add_argument('--start-year', type=int, default=pd.Timestamp.today().year - 1, help='Start year')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--output', type=str, default=str(Path(__file__).with_name('sample_drought_test_data.csv')))
    args = parser.parse_args()

    out_path = Path(args.output)
    frames = []
    year_ids = list(range(args.start_year, args.start_year + args.years_per_region))
    for r in range(1, args.n_regions + 1):
        for yi, year in enumerate(year_ids):
            seed = args.seed + r * 100 + yi
            end_date = f'{year}-12-31'
            df = generate_sample_drought_data(days=args.days_per_year, seed=seed, region_id=r, year_id=year, crop_id=1, irrigation_id=1, end_date=end_date)
            frames.append(df)

    big = pd.concat(frames, ignore_index=True)
    big.to_csv(out_path, index=False)
    print(f'Wrote {len(big)} rows to {out_path} (n_regions={args.n_regions}, years_per_region={args.years_per_region}, days_per_year={args.days_per_year})')


if __name__ == '__main__':
    main()