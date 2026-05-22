from django.urls import path

from .views import dashboard_view, live_metrics_api

app_name = "dashboard"

urlpatterns = [
    path("", dashboard_view, name="home"),
    path("api/live-metrics/", live_metrics_api, name="live_metrics"),
]
