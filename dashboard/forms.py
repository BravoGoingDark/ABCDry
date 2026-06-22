from datetime import date

from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _
import pandas as pd

from .models import (
    CropType, 
    IrrigationMethod, 
    ObservationYear, 
    Region,
    SoilMetrics,
    ClimateMetrics,
    DroughtIndices,
    AgriculturalMetrics,
    RemoteSensingMetrics,
    HydrologyMetrics,
    UserProfile,
)


class RiskSimulationForm(forms.Form):
    region = forms.ModelChoiceField(queryset=Region.objects.none())
    year = forms.ModelChoiceField(queryset=ObservationYear.objects.none())
    crop = forms.ModelChoiceField(queryset=CropType.objects.none())
    irrigation = forms.ModelChoiceField(queryset=IrrigationMethod.objects.none())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["region"].queryset = Region.objects.order_by("name")
        self.fields["year"].queryset = ObservationYear.objects.order_by("-label")
        self.fields["crop"].queryset = CropType.objects.order_by("name")
        self.fields["irrigation"].queryset = IrrigationMethod.objects.order_by("name")
        if not self.is_bound:
            default_region = Region.objects.filter(name="Bizerte").first()
            if default_region:
                self.fields["region"].initial = default_region.pk
            current_year = ObservationYear.objects.filter(label=str(date.today().year)).first()
            if current_year:
                self.fields["year"].initial = current_year.pk


# ============== SOIL METRICS FORM ==============
class SoilMetricsForm(forms.ModelForm):
    class Meta:
        model = SoilMetrics
        fields = [
            'region', 'year', 'moisture_content_percent', 'sand_ratio', 'clay_ratio',
            'silt_ratio', 'root_zone_depth_mm', 'organic_matter_percent',
            'infiltration_rate_mmhr', 'field_capacity_percent', 'wilting_point_percent',
            'salinity_ece_dsm', 'ph_level'
        ]
        widgets = {
            'region': forms.Select(attrs={'class': 'form-control'}),
            'year': forms.Select(attrs={'class': 'form-control'}),
            'moisture_content_percent': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Volumetric water content (%)'}),
            'sand_ratio': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Sand ratio (%)'}),
            'clay_ratio': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Clay ratio (%)'}),
            'silt_ratio': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Silt ratio (%)'}),
            'root_zone_depth_mm': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Root zone depth (mm)'}),
            'organic_matter_percent': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Organic matter (%)'}),
            'infiltration_rate_mmhr': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Infiltration rate (mm/hr)'}),
            'field_capacity_percent': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Field capacity (%)'}),
            'wilting_point_percent': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Wilting point (%)'}),
            'salinity_ece_dsm': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Salinity ECe (dS/m)'}),
            'ph_level': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'pH level'}),
        }


# ============== CLIMATE METRICS FORM ==============
class ClimateMetricsForm(forms.ModelForm):
    class Meta:
        model = ClimateMetrics
        fields = [
            'region', 'year', 'measurement_date', 'rainfall_mm', 'seasonal_rainfall_variability',
            'temperature_max_c', 'temperature_min_c', 'temperature_mean_c', 'relative_humidity_percent',
            'wind_speed_ms', 'solar_radiation_mjm2day', 'evapotranspiration_et0_mmday', 'evapotranspiration_etc_mmday'
        ]
        widgets = {
            'region': forms.Select(attrs={'class': 'form-control'}),
            'year': forms.Select(attrs={'class': 'form-control'}),
            'measurement_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'rainfall_mm': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Rainfall (mm)'}),
            'seasonal_rainfall_variability': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., High, Medium, Low'}),
            'temperature_max_c': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Max temp (°C)'}),
            'temperature_min_c': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Min temp (°C)'}),
            'temperature_mean_c': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Mean temp (°C)'}),
            'relative_humidity_percent': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Humidity (%)'}),
            'wind_speed_ms': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Wind speed (m/s)'}),
            'solar_radiation_mjm2day': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Solar radiation (MJ/m²/day)'}),
            'evapotranspiration_et0_mmday': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'ET₀ (mm/day)'}),
            'evapotranspiration_etc_mmday': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'ETc (mm/day)'}),
        }


# ============== DROUGHT INDICES FORM ==============
class DroughtIndicesForm(forms.ModelForm):
    class Meta:
        model = DroughtIndices
        fields = [
            'region', 'year', 'measurement_date', 'spi_1month', 'spi_3month', 'spi_12month',
            'spei_1month', 'spei_3month', 'spei_12month', 'pdsi_value', 'drought_severity_class'
        ]
        widgets = {
            'region': forms.Select(attrs={'class': 'form-control'}),
            'year': forms.Select(attrs={'class': 'form-control'}),
            'measurement_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'spi_1month': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'SPI 1-month'}),
            'spi_3month': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'SPI 3-month'}),
            'spi_12month': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'SPI 12-month'}),
            'spei_1month': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'SPEI 1-month'}),
            'spei_3month': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'SPEI 3-month'}),
            'spei_12month': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'SPEI 12-month'}),
            'pdsi_value': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'PDSI value'}),
            'drought_severity_class': forms.Select(attrs={'class': 'form-control'}),
        }


# ============== AGRICULTURAL METRICS FORM ==============
class AgriculturalMetricsForm(forms.ModelForm):
    class Meta:
        model = AgriculturalMetrics
        fields = [
            'region', 'year', 'crop', 'measurement_date', 'growth_stage', 'crop_coefficient_kc',
            'crop_water_requirement_mmday', 'yield_reduction_factor', 'irrigation_method',
            'irrigation_efficiency_percent', 'water_applied_mm', 'leaf_temperature_c', 'stomatal_conductance'
        ]
        widgets = {
            'region': forms.Select(attrs={'class': 'form-control'}),
            'year': forms.Select(attrs={'class': 'form-control'}),
            'crop': forms.Select(attrs={'class': 'form-control'}),
            'measurement_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'growth_stage': forms.Select(attrs={'class': 'form-control'}),
            'crop_coefficient_kc': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Crop coefficient (Kc)'}),
            'crop_water_requirement_mmday': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'CWR (mm/day)'}),
            'yield_reduction_factor': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Yield reduction factor (0-1)'}),
            'irrigation_method': forms.Select(attrs={'class': 'form-control'}),
            'irrigation_efficiency_percent': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Efficiency (%)'}),
            'water_applied_mm': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Water applied (mm)'}),
            'leaf_temperature_c': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Leaf temp (°C)'}),
            'stomatal_conductance': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Stomatal conductance'}),
        }


# ============== REMOTE SENSING METRICS FORM ==============
class RemoteSensingMetricsForm(forms.ModelForm):
    class Meta:
        model = RemoteSensingMetrics
        fields = [
            'region', 'year', 'measurement_date', 'ndvi', 'ndwi', 'land_surface_temperature_c',
            'satellite_soil_moisture_percent', 'satellite_source', 'vegetation_condition_index',
            'evapotranspiration_sebal_mmday'
        ]
        widgets = {
            'region': forms.Select(attrs={'class': 'form-control'}),
            'year': forms.Select(attrs={'class': 'form-control'}),
            'measurement_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'ndvi': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'NDVI (-1 to 1)'}),
            'ndwi': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'NDWI'}),
            'land_surface_temperature_c': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'LST (°C)'}),
            'satellite_soil_moisture_percent': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Soil moisture (%)'}),
            'satellite_source': forms.Select(attrs={'class': 'form-control'}),
            'vegetation_condition_index': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'VCI (%)'}),
            'evapotranspiration_sebal_mmday': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'ET (mm/day)'}),
        }


# ============== HYDROLOGY METRICS FORM ==============
class HydrologyMetricsForm(forms.ModelForm):
    class Meta:
        model = HydrologyMetrics
        fields = [
            'region', 'year', 'measurement_date', 'precipitation_mm', 'evapotranspiration_mm',
            'groundwater_depth_m', 'runoff_mm', 'river_flow_m3s', 'reservoir_storage_m3',
            'irrigation_supply_available_m3', 'soil_water_deficit_index_mm', 'water_balance_percent'
        ]
        widgets = {
            'region': forms.Select(attrs={'class': 'form-control'}),
            'year': forms.Select(attrs={'class': 'form-control'}),
            'measurement_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'precipitation_mm': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Precipitation (mm)'}),
            'evapotranspiration_mm': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Evapotranspiration (mm)'}),
            'groundwater_depth_m': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Groundwater depth (m)'}),
            'runoff_mm': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Runoff (mm)'}),
            'river_flow_m3s': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'River flow (m³/s)'}),
            'reservoir_storage_m3': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Reservoir storage (m³)'}),
            'irrigation_supply_available_m3': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Irrigation supply (m³)'}),
            'soil_water_deficit_index_mm': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Soil water deficit (mm)'}),
            'water_balance_percent': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Water balance (%)'}),
        }


# ============== EXCEL IMPORT FORMS ==============
class ExcelImportForm(forms.Form):
    METRIC_CHOICES = [
        ('soil', 'Soil Metrics'),
        ('climate', 'Climate Metrics'),
        ('drought', 'Drought Indices'),
        ('agricultural', 'Agricultural Metrics'),
        ('remote_sensing', 'Remote Sensing Metrics'),
        ('hydrology', 'Hydrology Metrics'),
    ]
    
    excel_file = forms.FileField(
        label='Select Excel File',
        help_text='Upload an Excel file (.xlsx, .xls) with metric data',
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': '.xlsx,.xls'})
    )
    metric_type = forms.ChoiceField(
        choices=METRIC_CHOICES,
        label='Metric Type',
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    def clean_excel_file(self):
        excel_file = self.cleaned_data['excel_file']
        if excel_file:
            if not excel_file.name.endswith(('.xlsx', '.xls')):
                raise ValidationError('Only Excel files (.xlsx, .xls) are allowed.')
            if excel_file.size > 10 * 1024 * 1024:  # 10 MB limit
                raise ValidationError('File size must not exceed 10 MB.')
        return excel_file


class BulkMetricsImportForm(forms.Form):
    """Form for importing multiple metric types at once"""
    excel_file = forms.FileField(
        label='Select Excel File with Multiple Metrics',
        help_text='Excel file should have sheets named: Soil, Climate, Drought, Agricultural, RemoteSensing, Hydrology',
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': '.xlsx,.xls'})
    )
    
    def clean_excel_file(self):
        excel_file = self.cleaned_data['excel_file']
        if excel_file:
            if not excel_file.name.endswith(('.xlsx', '.xls')):
                raise ValidationError('Only Excel files (.xlsx, .xls) are allowed.')
            if excel_file.size > 50 * 1024 * 1024:  # 50 MB limit
                raise ValidationError('File size must not exceed 50 MB.')
        return excel_file


BASE_INPUT = 'w-full pl-10 pr-4 py-3 bg-white border border-outline-variant rounded-lg focus:outline-none focus:ring-2 focus:ring-secondary/20 focus:border-secondary transition-all text-sm placeholder:text-outline-variant/50'
BASE_SELECT = 'w-full pl-10 pr-10 py-3 bg-white border border-outline-variant rounded-lg focus:outline-none focus:ring-2 focus:ring-secondary/20 focus:border-secondary transition-all text-sm appearance-none'


class UserCreateForm(forms.ModelForm):
    """Form for superadmin to create users with role & region assignment."""

    password = forms.CharField(
        label=_('Password'),
        widget=forms.PasswordInput(attrs={'class': BASE_INPUT, 'placeholder': 'Password'}),
    )
    role = forms.ChoiceField(
        choices=UserProfile.ROLE_CHOICES,
        label=_('Role'),
        widget=forms.Select(attrs={'class': BASE_SELECT}),
    )
    region = forms.ModelChoiceField(
        queryset=Region.objects.all(),
        required=False,
        label=_('Assigned Region'),
        widget=forms.Select(attrs={'class': BASE_SELECT}),
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'password']
        widgets = {
            'username': forms.TextInput(attrs={'class': BASE_INPUT, 'placeholder': 'Username'}),
            'email': forms.EmailInput(attrs={'class': BASE_INPUT, 'placeholder': 'Email'}),
        }

    def __init__(self, *args, **kwargs):
        self.request_user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
            profile, created = UserProfile.objects.get_or_create(user=user)
            profile.role = self.cleaned_data['role']
            profile.region = self.cleaned_data.get('region')
            profile.save()
        return user
