from django.contrib import admin

from .models import (
    CropType,
    EnvironmentalSnapshot,
    IrrigationMethod,
    ObservationYear,
    Region,
    RiskAssessment,
)

admin.site.register(Region)
admin.site.register(ObservationYear)
admin.site.register(CropType)
admin.site.register(IrrigationMethod)
admin.site.register(EnvironmentalSnapshot)
admin.site.register(RiskAssessment)
