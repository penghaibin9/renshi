"""Explicit HR01~HR12 URL registry."""

from django.urls import include, path, re_path

from horilla.legacy_hr_api import legacy_hr_api_redirect

urlpatterns = [
    path("hr/", include("hr_control_center.urls")),
    path("hr/structure/", include("hr_structure.urls")),
    path("hr/staff/", include("hr_staff.urls")),
    path("hr/recruitment/", include("hr_recruitment.urls")),
    path("", include("hr_recruitment.public.urls")),
    path("hr/onboarding/", include("hr_onboarding.urls")),
    path("hr/changes/", include("hr_changes.urls")),
    # HR07 由独立恢复线收口后注册。
    path("hr/external-teachers/", include("hr_external.urls")),
    path("hr/qualifications/", include("hr_qualification.urls")),
    path("hr/double-teacher/", include("hr_qualification.urls_double_teacher")),
    path("", include("hr10_development.urls")),
    path("hr/time/", include("hr_time.urls")),
    path("hr/assessments/", include("hr_assessment.urls")),
    path("", include("horilla.canonical_hr_api")),
    path("", include("hr_qualification.api.urls")),
    path("", include("hr10_development.api.urls")),
    path("", include("hr_assessment.api.urls")),
    re_path(r"^api/hr/v1/(?P<tail>.*)$", legacy_hr_api_redirect, name="legacy-hr-api"),
]
