from dashboard.models import Region, ObservationYear, CropType, IrrigationMethod, EnvironmentalSnapshot, SoilMetrics, ClimateMetrics, DroughtIndices, AgriculturalMetrics, RemoteSensingMetrics, HydrologyMetrics, RiskAssessment, DataImportLog
models = [Region, ObservationYear, CropType, IrrigationMethod, EnvironmentalSnapshot, SoilMetrics, ClimateMetrics, DroughtIndices, AgriculturalMetrics, RemoteSensingMetrics, HydrologyMetrics, RiskAssessment, DataImportLog]
for model in models:
    print(model.__name__, model._meta.db_table, model.objects.count())
