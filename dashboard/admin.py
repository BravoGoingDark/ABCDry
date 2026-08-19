from django.contrib import admin

from .models import (
    AgriculturalMetrics,
    ClimateMetrics,
    CropType,
    DataImportLog,
    DroughtIndices,
    DroughtPrediction,
    EnvironmentalSnapshot,
    HydrologyMetrics,
    IrrigationMethod,
    ObservationYear,
    Region,
    RemoteSensingMetrics,
    RiskAssessment,
    Sensor,
    SoilMetrics,
    UserProfile,
)

admin.site.register(Region)
admin.site.register(ObservationYear)
admin.site.register(CropType)
admin.site.register(IrrigationMethod)
admin.site.register(EnvironmentalSnapshot)
admin.site.register(RiskAssessment)
admin.site.register(DroughtPrediction)
admin.site.register(SoilMetrics)
admin.site.register(ClimateMetrics)
admin.site.register(DroughtIndices)
admin.site.register(AgriculturalMetrics)
admin.site.register(RemoteSensingMetrics)
admin.site.register(HydrologyMetrics)
admin.site.register(DataImportLog)
admin.site.register(UserProfile)
admin.site.register(Sensor)
