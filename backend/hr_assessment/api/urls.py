"""HR12 Assessment — API 路由（全量 S1-S9）。"""

from django.urls import path

from hr_assessment.api import views_assessment as probe
from hr_assessment.api import views_policy

app_name = "hr_assessment_api"

urlpatterns = [
    path("api/v1/hr/assessments/ping", probe.ping, name="hr12-api-ping"),
    path("api/v1/hr/assessments/eligibility", probe.eligibility_probe, name="hr12-api-eligibility"),
    path("api/v1/hr/assessments/annual", probe.annual_case_list, name="hr12-api-annual-list"),
    path(
        "api/v1/hr/assessments/workbench/<str:section>",
        probe.workbench_rows,
        name="hr12-api-workbench",
    ),
    path(
        "api/v1/hr/assessments/cases/<uuid:case_id>/provider-snapshot",
        probe.provider_snapshot,
        name="hr12-api-provider-snapshot",
    ),
    path(
        "api/v1/hr/assessments/cases/<uuid:case_id>/finalize",
        probe.finalize_case,
        name="hr12-api-finalize",
    ),
    path(
        "api/v1/hr/assessments/results/<uuid:result_id>/corrections",
        probe.result_corrections,
        name="hr12-api-result-corrections",
    ),
    path(
        "api/v1/hr/assessments/cases/<uuid:case_id>/reviewers",
        probe.assign_case_reviewer,
        name="hr12-api-reviewer-assign",
    ),
    path(
        "api/v1/hr/assessments/review-administration-options",
        probe.review_administration_options,
        name="hr12-api-review-administration-options",
    ),
    path(
        "api/v1/hr/assessments/reviewer-assignments/mine",
        probe.my_reviewer_assignments,
        name="hr12-api-reviewer-mine",
    ),
    path(
        "api/v1/hr/assessments/decision-options",
        probe.decision_options,
        name="hr12-api-decision-options",
    ),
    path(
        "api/v1/hr/assessments/reviewer-assignments/<uuid:assignment_id>/evaluations",
        probe.submit_reviewer_evaluation,
        name="hr12-api-reviewer-evaluation",
    ),
    path(
        "api/v1/hr/assessments/cycles/<uuid:cycle_id>/decision-sessions",
        probe.create_decision_session,
        name="hr12-api-decision-create",
    ),
    path(
        "api/v1/hr/assessments/decision-sessions/<uuid:session_id>/complete",
        probe.complete_decision_session,
        name="hr12-api-decision-complete",
    ),
    path(
        "api/v1/hr/assessments/decision-sessions/<uuid:session_id>/minutes",
        probe.upload_decision_minutes,
        name="hr12-api-decision-minutes-upload",
    ),
    path(
        "api/v1/hr/assessments/decision-sessions/<uuid:session_id>/minutes/<uuid:document_id>",
        probe.download_decision_minutes,
        name="hr12-api-decision-minutes-download",
    ),
    path(
        "api/v1/hr/assessments/results/<uuid:result_id>/notices",
        probe.issue_result_notice,
        name="hr12-api-result-notice",
    ),
    path(
        "api/v1/hr/assessments/results/lifecycle",
        probe.result_lifecycle_list,
        name="hr12-api-result-lifecycle-list",
    ),
    path(
        "api/v1/hr/assessments/notices/<uuid:notice_id>/delivery",
        probe.confirm_result_notice_delivery,
        name="hr12-api-result-notice-delivery",
    ),
    path(
        "api/v1/hr/assessments/results/<uuid:result_id>/acknowledgements",
        probe.acknowledge_result,
        name="hr12-api-result-acknowledgement",
    ),
    path(
        "api/v1/hr/assessments/results/<uuid:result_id>/objections",
        probe.submit_result_objection,
        name="hr12-api-result-objection-submit",
    ),
    path(
        "api/v1/hr/assessments/objections/<uuid:objection_id>/decision",
        probe.decide_result_objection,
        name="hr12-api-result-objection-decide",
    ),
    path(
        "api/v1/hr/assessments/results/<uuid:result_id>/archive",
        probe.archive_result,
        name="hr12-api-result-archive",
    ),
    path("api/v1/hr/assessments/policies", views_policy.policy_list, name="hr12-api-policy-list"),
    path("api/v1/hr/assessments/policies/<uuid:policy_id>", views_policy.policy_detail, name="hr12-api-policy-detail"),
    path(
        "api/v1/hr/assessments/policies/<uuid:policy_id>/versions/<uuid:version_id>/publish",
        views_policy.publish_policy_version,
        name="hr12-api-policy-publish",
    ),
    path(
        "api/v1/hr/assessments/policies/<uuid:policy_id>/versions",
        views_policy.create_policy_version,
        name="hr12-api-policy-version-create",
    ),
    path("api/v1/hr/assessments/setup-options", probe.setup_options, name="hr12-api-setup-options"),
    path("api/v1/hr/assessments/cycles", probe.create_cycle, name="hr12-api-cycle-create"),
    path("api/v1/hr/assessments/annual/cases", probe.create_annual_case, name="hr12-api-annual-create"),
    path("api/v1/hr/assessments/indicators", views_policy.indicator_list, name="hr12-api-indicator-list"),
    path("api/v1/hr/assessments/rating-scales", views_policy.rating_scale_list, name="hr12-api-rating-scale-list"),
]
