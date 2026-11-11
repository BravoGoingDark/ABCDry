import json

from django.core.serializers.json import DjangoJSONEncoder
from django.utils.functional import SimpleLazyObject

from .models import Region, Sensor
from .views.utils import _lakes_by_region


def _default_region(regions):
    """Same default the overview's RiskSimulationForm picks."""
    by_name = {r.name.lower(): r for r in regions}
    return by_name.get("ichkeul") or by_name.get("bizerte") or (regions[0] if regions else None)


def navbar(request):
    """Region/Lake data for the shared navbar on pages other than the overview.

    Lazy, so the query only runs on templates that actually render the navbar.
    """
    regions = SimpleLazyObject(lambda: list(Region.objects.order_by("name")))
    return {
        "navbar_regions": regions,
        "navbar_default_region": SimpleLazyObject(lambda: _default_region(regions)),
        "navbar_lakes_json": SimpleLazyObject(lambda: json.dumps(_lakes_by_region(), cls=DjangoJSONEncoder)),
        # Sidebar badge on every page: the active sensors actually registered.
        "sidebar_sensor_count": SimpleLazyObject(lambda: Sensor.objects.filter(is_active=True).count()),
    }
