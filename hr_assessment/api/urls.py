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
        "api/v1/hr/assessments/cases/<uuid:case_id>/provider-snapshot",
        probe.provider_snapshot,
        name="hr12-api-provider-snapshot",
    ),
    path(
        "api/v1/hr/assessments/cases/<uuid:case_id>/finalize",
        probe.finalize_case,
        name="hr12-api-finalize",
    ),
    path("api/v1/hr/assessments/policies", views_policy.policy_list, name="hr12-api-policy-list"),
    path("api/v1/hr/assessments/policies/<uuid:policy_id>", views_policy.policy_detail, name="hr12-api-policy-detail"),
    path(
        "api/v1/hr/assessments/policies/<uuid:policy_id>/versions/<uuid:version_id>/publish",
        views_policy.publish_policy_version,
        name="hr12-api-policy-publish",
    ),
    path("api/v1/hr/assessments/indicators", views_policy.indicator_list, name="hr12-api-indicator-list"),
    path("api/v1/hr/assessments/rating-scales", views_policy.rating_scale_list, name="hr12-api-rating-scale-list"),
]
