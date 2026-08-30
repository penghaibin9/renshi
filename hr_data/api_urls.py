from django.urls import path

from . import (
    api,
    asof_api,
    evaluation_api,
    legacy_api,
    metric_api,
    quality_api,
    quality_finding_api,
    submission_api,
)

app_name = "hr_data_api"

urlpatterns = [
    path("dashboard/", api.dashboard, name="dashboard"),
    path(
        "legacy/report-assets/",
        legacy_api.legacy_report_assets,
        name="legacy-report-assets",
    ),
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
    path(
        "as-of/evidence/",
        asof_api.reconstruct_evidence,
        name="asof-evidence-reconstruct",
    ),
    path(
        "as-of/evaluate/",
        evaluation_api.evaluate,
        name="asof-evaluate",
    ),
    path(
        "quality/rules/",
        quality_api.create_rule,
        name="quality-rule-create",
    ),
    path(
        "quality/runs/",
        quality_api.execute_run,
        name="quality-run-execute",
    ),
    path(
        "quality/findings/<uuid:finding_id>/acknowledge/",
        quality_finding_api.acknowledge,
        name="quality-finding-acknowledge",
    ),
    path(
        "quality/findings/<uuid:finding_id>/verify-fixed/",
        quality_finding_api.verify_fixed,
        name="quality-finding-verify-fixed",
    ),
    path("submissions/", submission_api.create_submission, name="submission-create"),
    path(
        "submissions/<uuid:submission_id>/validate/",
        submission_api.validate_submission,
        name="submission-validate",
    ),
    path(
        "submissions/<uuid:submission_id>/corrections/",
        submission_api.create_correction,
        name="submission-correction-create",
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
