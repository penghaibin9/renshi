from django.urls import path

from . import api, metric_api, submission_api

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
    path("submissions/", submission_api.create_submission, name="submission-create"),
    path(
        "submissions/<uuid:submission_id>/validate/",
        submission_api.validate_submission,
        name="submission-validate",
    ),
    path(
        "submissions/<uuid:submission_id>/approve/",
        submission_api.approve_submission,
        name="submission-approve",
    ),
    path(
        "submissions/<uuid:submission_id>/submit/",
        submission_api.submit_submission,
        name="submission-submit",
    ),
    path(
        "submissions/<uuid:submission_id>/receipt/",
        submission_api.record_receipt,
        name="submission-receipt",
    ),
]
