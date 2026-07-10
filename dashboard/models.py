from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


class Region(models.Model):
    id = models.BigAutoField(primary_key=True, db_column='region_id')
    name = models.CharField(max_length=100, unique=True)
    country = models.CharField(max_length=100, blank=True, null=True)
    latitude = models.DecimalField(max_digits=10, decimal_places=6, blank=True, null=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=6, blank=True, null=True)
    elevation_m = models.IntegerField(blank=True, null=True)
    area_km2 = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    radius_km = models.DecimalField(max_digits=8, decimal_places=2, default=100.0)

    class Meta:
        db_table = 'regions'

    def __str__(self):
        return self.name


class ObservationYear(models.Model):
    id = models.BigAutoField(primary_key=True, db_column='year_id')
    label = models.CharField(max_length=30, unique=True)

    class Meta:
        db_table = 'observation_years'

    def __str__(self):
        return self.label


class CropType(models.Model):
    id = models.BigAutoField(primary_key=True, db_column='crop_id')
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        db_table = 'crop_types'

    def __str__(self):
        return self.name


class IrrigationMethod(models.Model):
    id = models.BigAutoField(primary_key=True, db_column='irrigation_id')
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        db_table = 'irrigation_methods'

    def __str__(self):
        return self.name


class EnvironmentalSnapshot(models.Model):
    id = models.BigAutoField(primary_key=True, db_column='snapshot_id')
    region = models.ForeignKey(Region, on_delete=models.CASCADE)
    year = models.ForeignKey(ObservationYear, on_delete=models.CASCADE)
    time = models.DateTimeField(db_column='time', auto_now_add=True)
    wind_speed_kmh = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    wind_gust_kmh = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    wind_direction = models.CharField(max_length=10, default="NE")
    rainfall_mm = models.DecimalField(max_digits=6, decimal_places=1, default=0)
    rainfall_delta_percent = models.IntegerField(default=0)
    ph_level = models.DecimalField(max_digits=3, decimal_places=1, default=7.0)
    npk_index = models.CharField(max_length=20, default="Med-High")
    temperature_c = models.DecimalField(max_digits=4, decimal_places=1, default=25)
    humidity_percent = models.IntegerField(default=60)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='environmental_snapshots')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'environmental_snapshots'
        unique_together = ("region", "year")

    def __str__(self):
        return f"{self.region} - {self.year}"


class RiskAssessment(models.Model):
    id = models.BigAutoField(primary_key=True, db_column='assessment_id')
    region = models.ForeignKey(Region, on_delete=models.CASCADE)
    year = models.ForeignKey(ObservationYear, on_delete=models.CASCADE)
    crop = models.ForeignKey(CropType, on_delete=models.CASCADE)
    irrigation = models.ForeignKey(IrrigationMethod, on_delete=models.CASCADE)
    risk_level = models.CharField(max_length=30)
    recommendation = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='risk_assessments')

    class Meta:
        db_table = 'risk_assessments'

    def __str__(self):
        return f"{self.crop} - {self.risk_level}"


# ============== SOIL METRICS ==============
class SoilMetrics(models.Model):
    id = models.BigAutoField(primary_key=True, db_column='metric_id')
    region = models.ForeignKey(Region, on_delete=models.CASCADE, related_name='soil_metrics')
    year = models.ForeignKey(ObservationYear, on_delete=models.CASCADE)
    measurement_date = models.DateField(db_column='time')
    latitude = models.DecimalField(max_digits=10, decimal_places=6, blank=True, null=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=6, blank=True, null=True)
    
    # Moisture Content
    moisture_content_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="Volumetric water content (%)")
    
    # Texture & Structure
    sand_ratio = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="Sand ratio (%)")
    clay_ratio = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="Clay ratio (%)")
    silt_ratio = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="Silt ratio (%)")
    
    # Depth & Root Zone
    root_zone_depth_mm = models.IntegerField(null=True, blank=True, help_text="Available water holding capacity (mm)")
    
    # Organic Matter
    organic_matter_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="Organic matter content (%)")
    
    # Infiltration
    infiltration_rate_mmhr = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, help_text="Infiltration rate (mm/hr)")
    
    # Soil Water Thresholds
    field_capacity_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="Field capacity threshold (%)")
    wilting_point_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="Wilting point threshold (%)")
    
    # Salinity & pH
    salinity_ece_dsm = models.DecimalField(max_digits=5, decimal_places=3, null=True, blank=True, help_text="Electrical conductivity (dS/m)")
    ph_level = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True, help_text="Soil pH level")
    
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='soil_metric_entries')
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'soil_metrics'
        unique_together = ("region", "year", "measurement_date")
        ordering = ['-measurement_date']
    
    def __str__(self):
        return f"Soil - {self.region} - {self.measurement_date}"


# ============== CLIMATE & WEATHER METRICS ==============
class ClimateMetrics(models.Model):
    id = models.BigAutoField(primary_key=True, db_column='metric_id')
    region = models.ForeignKey(Region, on_delete=models.CASCADE, related_name='climate_metrics')
    year = models.ForeignKey(ObservationYear, on_delete=models.CASCADE)
    measurement_date = models.DateField(db_column='time')
    latitude = models.DecimalField(max_digits=10, decimal_places=6, blank=True, null=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=6, blank=True, null=True)
    
    # Rainfall
    rainfall_mm = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True, help_text="Rainfall amount (mm)")
    seasonal_rainfall_variability = models.CharField(max_length=50, blank=True, help_text="Seasonal variability classification")
    
    # Temperature
    temperature_max_c = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True, help_text="Daily max temperature (°C)")
    temperature_min_c = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True, help_text="Daily min temperature (°C)")
    temperature_mean_c = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True, help_text="Daily mean temperature (°C)")
    
    # Humidity
    relative_humidity_percent = models.IntegerField(null=True, blank=True, help_text="Relative humidity (%)")
    
    # Wind
    wind_speed_ms = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True, help_text="Wind speed (m/s at 2m height)")
    
    # Solar Radiation
    solar_radiation_mjm2day = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, help_text="Solar radiation (MJ/m²/day)")
    
    # Evapotranspiration
    evapotranspiration_et0_mmday = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="Reference ET₀ (mm/day)")
    evapotranspiration_etc_mmday = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="Crop ET (mm/day)")
    
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='climate_metric_entries')
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'climate_metrics'
        unique_together = ("region", "year", "measurement_date")
        ordering = ['-measurement_date']
        indexes = [
            models.Index(fields=['region', 'measurement_date']),
        ]
    
    def __str__(self):
        return f"Climate - {self.region} - {self.measurement_date}"


# ============== DROUGHT INDICES ==============
class DroughtIndices(models.Model):
    id = models.BigAutoField(primary_key=True, db_column='metric_id')
    region = models.ForeignKey(Region, on_delete=models.CASCADE, related_name='drought_indices')
    year = models.ForeignKey(ObservationYear, on_delete=models.CASCADE)
    measurement_date = models.DateField(db_column='time')
    latitude = models.DecimalField(max_digits=10, decimal_places=6, blank=True, null=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=6, blank=True, null=True)
    
    # SPI - Standardized Precipitation Index
    spi_1month = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="SPI 1-month")
    spi_3month = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="SPI 3-month")
    spi_12month = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="SPI 12-month")
    
    # SPEI - Standardized Precipitation-Evapotranspiration Index
    spei_1month = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="SPEI 1-month")
    spei_3month = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="SPEI 3-month")
    spei_12month = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="SPEI 12-month")
    
    # PDSI - Palmer Drought Severity Index
    pdsi_value = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="PDSI value")
    
    drought_severity_class = models.CharField(
        max_length=20,
        choices=[
            ('None', 'No Drought'),
            ('Abnormally Dry', 'Abnormally Dry'),
            ('Moderate Drought', 'Moderate Drought'),
            ('Severe Drought', 'Severe Drought'),
            ('Extreme Drought', 'Extreme Drought'),
        ],
        default='None'
    )
    
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='drought_metric_entries')
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'drought_indices'
        unique_together = ("region", "year", "measurement_date")
        ordering = ['-measurement_date']
    
    def __str__(self):
        return f"Drought - {self.region} - {self.drought_severity_class}"


# ============== AGRICULTURAL & CROP METRICS ==============
class AgriculturalMetrics(models.Model):
    id = models.BigAutoField(primary_key=True, db_column='metric_id')
    region = models.ForeignKey(Region, on_delete=models.CASCADE, related_name='agricultural_metrics')
    year = models.ForeignKey(ObservationYear, on_delete=models.CASCADE)
    crop = models.ForeignKey(CropType, on_delete=models.CASCADE)
    measurement_date = models.DateField(db_column='time')
    latitude = models.DecimalField(max_digits=10, decimal_places=6, blank=True, null=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=6, blank=True, null=True)
    
    # Crop Stage
    GROWTH_STAGES = [
        ('Germination', 'Germination'),
        ('Vegetative', 'Vegetative'),
        ('Flowering', 'Flowering'),
        ('Grain Filling', 'Grain Filling'),
        ('Maturity', 'Maturity'),
    ]
    growth_stage = models.CharField(max_length=20, choices=GROWTH_STAGES)
    
    # Crop Coefficient
    crop_coefficient_kc = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True, help_text="Crop coefficient (Kc)")
    
    # Crop Water Requirement
    crop_water_requirement_mmday = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="CWR (mm/day)")
    
    # Yield Reduction Factors
    yield_reduction_factor = models.DecimalField(max_digits=5, decimal_places=3, null=True, blank=True, help_text="Sensitivity to water stress (0-1)")
    
    # Irrigation
    irrigation_method = models.ForeignKey(IrrigationMethod, on_delete=models.SET_NULL, null=True, blank=True, db_column='irrigation_id')
    irrigation_efficiency_percent = models.IntegerField(null=True, blank=True, help_text="Irrigation efficiency (%)")
    water_applied_mm = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, help_text="Water applied (mm)")
    
    # Plant Stress
    leaf_temperature_c = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True, help_text="Leaf temperature (°C)")
    stomatal_conductance = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True, help_text="Stomatal conductance (mol/m²/s)")
    
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='agricultural_metric_entries')
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'agricultural_metrics'
        ordering = ['-measurement_date']
        indexes = [
            models.Index(fields=['region', 'crop', 'measurement_date']),
        ]
    
    def __str__(self):
        return f"{self.crop} - {self.region} - {self.measurement_date}"


# ============== REMOTE SENSING METRICS ==============
class RemoteSensingMetrics(models.Model):
    id = models.BigAutoField(primary_key=True, db_column='metric_id')
    region = models.ForeignKey(Region, on_delete=models.CASCADE, related_name='remote_sensing')
    year = models.ForeignKey(ObservationYear, on_delete=models.CASCADE)
    measurement_date = models.DateField(db_column='time')
    latitude = models.DecimalField(max_digits=10, decimal_places=6, blank=True, null=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=6, blank=True, null=True)
    
    # NDVI - Vegetation Index
    ndvi = models.DecimalField(max_digits=4, decimal_places=3, null=True, blank=True, help_text="NDVI (-1 to 1, vegetation health)")
    
    # NDWI - Water Index
    ndwi = models.DecimalField(max_digits=4, decimal_places=3, null=True, blank=True, help_text="NDWI (water content in vegetation)")
    
    # LST - Land Surface Temperature
    land_surface_temperature_c = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="LST (°C)")
    
    # Satellite Soil Moisture
    satellite_soil_moisture_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="Soil moisture from satellite (%)")
    satellite_source = models.CharField(
        max_length=50,
        blank=True,
        choices=[
            ('SMAP', 'SMAP'),
            ('Sentinel-1', 'Sentinel-1'),
            ('MODIS', 'MODIS'),
            ('Landsat', 'Landsat'),
        ]
    )
    
    # VCI - Vegetation Condition Index
    vegetation_condition_index = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="VCI (% of normal)")
    
    # ET from SEBAL/METRIC
    evapotranspiration_sebal_mmday = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="ET from SEBAL/METRIC (mm/day)")
    
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='remote_sensing_metric_entries')
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'remote_sensing_metrics'
        unique_together = ("region", "year", "measurement_date")
        ordering = ['-measurement_date']
    
    def __str__(self):
        return f"Remote Sensing - {self.region} - {self.measurement_date}"


# ============== HYDROLOGY & WATER BALANCE ==============
class HydrologyMetrics(models.Model):
    id = models.BigAutoField(primary_key=True, db_column='metric_id')
    region = models.ForeignKey(Region, on_delete=models.CASCADE, related_name='hydrology_metrics')
    year = models.ForeignKey(ObservationYear, on_delete=models.CASCADE)
    measurement_date = models.DateField(db_column='time')
    latitude = models.DecimalField(max_digits=10, decimal_places=6, blank=True, null=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=6, blank=True, null=True)
    
    # Precipitation vs Evapotranspiration
    precipitation_mm = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True, help_text="Precipitation (mm)")
    evapotranspiration_mm = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True, help_text="Evapotranspiration (mm)")
    
    # Groundwater
    groundwater_depth_m = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, help_text="Groundwater depth (m)")
    
    # Runoff & River Flow
    runoff_mm = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True, help_text="Runoff (mm)")
    river_flow_m3s = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="River flow (m³/s)")
    
    # Reservoir & Irrigation Supply
    reservoir_storage_m3 = models.DecimalField(max_digits=15, decimal_places=0, null=True, blank=True, help_text="Reservoir storage (m³)")
    irrigation_supply_available_m3 = models.DecimalField(max_digits=15, decimal_places=0, null=True, blank=True, help_text="Available irrigation supply (m³)")
    
    # Soil Water Deficit
    soil_water_deficit_index_mm = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, help_text="Soil water deficit (ETc - available water)")

    water_balance_percent = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, help_text="Water balance (supply - demand %)")
    
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='hydrology_metric_entries')
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'hydrology_metrics'
        unique_together = ("region", "year", "measurement_date")
        ordering = ['-measurement_date']
    
    def __str__(self):
        return f"Hydrology - {self.region} - {self.measurement_date}"


# ============== BULK DATA IMPORT ==============
class DataImportLog(models.Model):
    id = models.BigAutoField(primary_key=True, db_column='log_id')
    IMPORT_SOURCES = [
        ('Excel', 'Excel File'),
        ('API', 'API Integration'),
        ('Manual', 'Manual Entry'),
    ]
    
    source = models.CharField(max_length=20, choices=IMPORT_SOURCES)
    filename = models.CharField(max_length=255, blank=True)
    metric_type = models.CharField(max_length=50, help_text="Type of metric imported (Soil, Climate, etc.)")
    records_imported = models.IntegerField(default=0)
    import_date = models.DateTimeField(auto_now_add=True)
    imported_by = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=[('Success', 'Success'), ('Failed', 'Failed'), ('Partial', 'Partial')],
        default='Success'
    )
    error_details = models.TextField(blank=True, null=True, help_text="JSON details of import errors")
    
    class Meta:
        db_table = 'data_import_logs'
        ordering = ['-import_date']
    
    def __str__(self):
        return f"{self.metric_type} - {self.source} - {self.import_date}"


# ============== PREDICTION ENGINE OUTPUTS ==============
class DroughtPrediction(models.Model):
    id = models.BigAutoField(primary_key=True, db_column='prediction_id')
    region = models.ForeignKey(Region, on_delete=models.CASCADE, related_name='drought_predictions')
    year = models.ForeignKey(ObservationYear, on_delete=models.CASCADE)
    prediction_date = models.DateField(auto_now_add=True)
    generated_at = models.DateTimeField(auto_now_add=True)
    model_version = models.CharField(max_length=50, default='v1')

    current_risk_score = models.DecimalField(max_digits=5, decimal_places=1)
    risk_7day = models.DecimalField(max_digits=5, decimal_places=1)
    risk_30day = models.DecimalField(max_digits=5, decimal_places=1)

    soil_moisture_today_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    soil_moisture_7day_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    soil_moisture_30day_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    drivers = models.JSONField(default=dict, blank=True)
    explanation = models.TextField(blank=True)
    source_window_days = models.IntegerField(default=30)

    class Meta:
        db_table = 'drought_predictions'
        ordering = ['-generated_at']
        indexes = [
            models.Index(fields=['region', 'year', '-generated_at']),
        ]

    def __str__(self):
        return f"Prediction - {self.region} - {self.prediction_date}"


# ============== USER PROFILE & RBAC ==============

class UserProfile(models.Model):
    ROLE_CHOICES = [
        ('superadmin', 'Superadmin'),
        ('subadmin', 'Subadmin'),
        ('viewer', 'Viewer'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='viewer')
    region = models.ForeignKey(
        Region, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='assigned_users'
    )

    class Meta:
        pass

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"

    def is_superadmin(self):
        return self.role == 'superadmin'

    def is_subadmin(self):
        return self.role == 'subadmin'

    def is_viewer(self):
        return self.role == 'viewer'


@receiver(post_save, sender=User)
def ensure_user_profile(sender, instance, **kwargs):
    UserProfile.objects.get_or_create(user=instance)


class Sensor(models.Model):
    SENSOR_TYPES = [
        ('aws', 'Weather Station'),
        ('soil', 'Soil Moisture'),
        ('water', 'Water Level'),
        ('custom', 'Custom'),
    ]

    id = models.BigAutoField(primary_key=True, db_column='sensor_id')
    name = models.CharField(max_length=200)
    sensor_type = models.CharField(max_length=20, choices=SENSOR_TYPES, default='custom')
    latitude = models.DecimalField(max_digits=10, decimal_places=6)
    longitude = models.DecimalField(max_digits=10, decimal_places=6)
    coverage_radius_km = models.DecimalField(max_digits=8, decimal_places=2, default=10.0)
    region = models.ForeignKey(Region, on_delete=models.SET_NULL, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    description = models.TextField(blank=True, null=True)
    installed_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        db_table = 'sensors'

    def __str__(self):
        return f"{self.name} ({self.get_sensor_type_display()})"
