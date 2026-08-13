from django.urls import path

from . import api

app_name = "hr_payroll_api"
urlpatterns = [
    path("dashboard/", api.dashboard, name="dashboard"),
    path(
        "legacy-reconciliation/",
        api.legacy_reconciliation,
        name="legacy-reconciliation",
    ),
    path(
        "results/<uuid:source_result_id>/adjustments/",
        api.adjust_result,
        name="result-adjustments",
    ),
]
