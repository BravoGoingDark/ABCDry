from django import forms

from .models import CropType, IrrigationMethod, ObservationYear, Region


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
