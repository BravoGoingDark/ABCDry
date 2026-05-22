from django.db import models


class Region(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class ObservationYear(models.Model):
    label = models.CharField(max_length=30, unique=True)

    def __str__(self):
        return self.label


class CropType(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class IrrigationMethod(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class EnvironmentalSnapshot(models.Model):
    region = models.ForeignKey(Region, on_delete=models.CASCADE)
    year = models.ForeignKey(ObservationYear, on_delete=models.CASCADE)
    wind_speed_kmh = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    wind_gust_kmh = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    wind_direction = models.CharField(max_length=10, default="NE")
    rainfall_mm = models.DecimalField(max_digits=6, decimal_places=1, default=0)
    rainfall_delta_percent = models.IntegerField(default=0)
    ph_level = models.DecimalField(max_digits=3, decimal_places=1, default=7.0)
    npk_index = models.CharField(max_length=20, default="Med-High")
    temperature_c = models.DecimalField(max_digits=4, decimal_places=1, default=25)
    humidity_percent = models.IntegerField(default=60)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("region", "year")

    def __str__(self):
        return f"{self.region} - {self.year}"


class RiskAssessment(models.Model):
    region = models.ForeignKey(Region, on_delete=models.CASCADE)
    year = models.ForeignKey(ObservationYear, on_delete=models.CASCADE)
    crop = models.ForeignKey(CropType, on_delete=models.CASCADE)
    irrigation = models.ForeignKey(IrrigationMethod, on_delete=models.CASCADE)
    risk_level = models.CharField(max_length=30)
    recommendation = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.crop} - {self.risk_level}"
