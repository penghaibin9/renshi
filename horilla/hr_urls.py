"""Explicit HR01~HR12 URL registry."""

from django.urls import include, path, re_path

from horilla.legacy_hr_api import legacy_hr_api_redirect

urlpatterns = [
    # HR01~HR06 UI routes
    path("hr/", include("hr_control_center.urls")),
    path("hr/structure/", include("hr_structure.urls")),
    path("hr/staff/", include("hr_staff.urls")),
    path("hr/recruitment/", include("hr_recruitment.urls")),
    path("", include("hr_recruitment.public.urls")),
    path("hr/onboarding/", include("hr_onboarding.urls")),
    path("hr/changes/", include("hr_changes.urls")),
    # HR07 remains deliberately unrouted until its missing Authority app,
    # migrations and tests are recovered.
    # HR08 UI
    path("hr/external-teachers/", include("hr_external.urls")),
    # HR09 UI
    path("hr/qualifications/", include("hr_qualification.urls")),
    path("hr/double-teacher/", include("hr_qualification.urls_double_teacher")),
    # HR10 UI owns its internal /hr/development/... route prefixes.
    path("", include("hr10_development.urls")),
    # HR12 UI
    path("hr/assessments/", include("hr_assessment.urls")),
    # Canonical APIs for the old-root modules HR01/02/03/04/05/06/08/11.
    path("", include("horilla.canonical_hr_api")),
    # HR09/10/12 already declare /api/v1/hr/... routes natively.
    path("", include("hr_qualification.api.urls")),
    path("", include("hr10_development.api.urls")),
    path("", include("hr_assessment.api.urls")),
    # Legacy API root is adapter-only. 308 preserves POST/PUT/PATCH bodies.
    re_path(r"^api/hr/v1/(?P<tail>.*)$", legacy_hr_api_redirect, name="legacy-hr-api"),
]
