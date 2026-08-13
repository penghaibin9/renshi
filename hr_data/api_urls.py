from django.urls import path

from . import api, metric_api

app_name = "hr_data_api"

urlpatterns = [
    path("dashboard/", api.dashboard, name="dashboard"),
    path(
        "definitions/populations/",
        api.create_population_definition,
        name="population-definition-create",
    ),
    path(
        "definitions/dimensions/",
        api.create_dimension_definition,
        name="dimension-definition-create",
    ),
    path(
        "definitions/metrics/",
        metric_api.create_metric_definition,
        name="metric-definition-create",
    ),
]
