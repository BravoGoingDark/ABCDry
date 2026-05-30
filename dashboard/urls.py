from django.urls import path

from .views import (
    dashboard_view, 
    live_metrics_api,
    data_ingestion,
    api_submit_metrics,
    parameter_review,
    analysis_results,
    calculations_view,
    calculations_data,
    historical_view,
    login_view,
    drought_prediction_api,
    soil_metrics_view,
    climate_metrics_view,
    drought_indices_view,
    agricultural_metrics_view,
    remote_sensing_view,
    hydrology_metrics_view,
    metrics_browser,
    edit_metric_entry,
    delete_metric_entry,
    add_soil_metrics,
    add_climate_metrics,
    add_drought_indices,
    add_agricultural_metrics,
    add_remote_sensing_metrics,
    add_hydrology_metrics,
    import_excel_metrics,
    export_metrics_excel,
    import_logs_view,
    ajax_upload_file,
)

app_name = "dashboard"

urlpatterns = [
    # Original Dashboard
    path("", dashboard_view, name="home"),
    path("api/live-metrics/", live_metrics_api, name="live_metrics"),
    
    # Data Ingestion
    path("data-ingestion/", data_ingestion, name="data_ingestion"),
    path("api/submit-metrics/", api_submit_metrics, name="api_submit_metrics"),
    path("parameters/", parameter_review, name="parameter_review"),
    path("analysis/", analysis_results, name="analysis"),
    path("analysis/calculations/", calculations_view, name="calculations"),
    path("analysis/calculations/data/", calculations_data, name="calculations_data"),
    path("historical/", historical_view, name="historical"),
    path("login/", login_view, name="login"),
    path("api/drought-prediction/", drought_prediction_api, name="drought_prediction_api"),
    
    # View Metrics
    path("metrics/soil/", soil_metrics_view, name="soil_metrics"),
    path("metrics/climate/", climate_metrics_view, name="climate_metrics"),
    path("metrics/drought/", drought_indices_view, name="drought_indices"),
    path("metrics/agricultural/", agricultural_metrics_view, name="agricultural_metrics"),
    path("metrics/remote-sensing/", remote_sensing_view, name="remote_sensing"),
    path("metrics/hydrology/", hydrology_metrics_view, name="hydrology_metrics"),
    path("metrics/browser/", metrics_browser, name="metrics_browser"),
    path("metrics/<str:metric_type>/<int:pk>/edit/", edit_metric_entry, name="edit_metric_entry"),
    path("metrics/<str:metric_type>/<int:pk>/delete/", delete_metric_entry, name="delete_metric_entry"),
    
    # Add Metrics
    path("metrics/soil/add/", add_soil_metrics, name="add_soil_metrics"),
    path("metrics/climate/add/", add_climate_metrics, name="add_climate_metrics"),
    path("metrics/drought/add/", add_drought_indices, name="add_drought_indices"),
    path("metrics/agricultural/add/", add_agricultural_metrics, name="add_agricultural_metrics"),
    path("metrics/remote-sensing/add/", add_remote_sensing_metrics, name="add_remote_sensing_metrics"),
    path("metrics/hydrology/add/", add_hydrology_metrics, name="add_hydrology_metrics"),
    
    # Data Import/Export
    path("metrics/import/excel/", import_excel_metrics, name="import_excel"),
    path("metrics/export/<str:metric_type>/", export_metrics_excel, name="export_metrics"),
    path("metrics/import-logs/", import_logs_view, name="import_logs"),
    
    # AJAX File Upload
    path("api/upload-file/", ajax_upload_file, name="ajax_upload_file"),
]
