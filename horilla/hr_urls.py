"""Explicit canonical HR routing registry."""

from importlib.util import find_spec

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
    path("hr/external-teachers/", include("hr_external.urls")),
    path("hr/qualifications/", include("hr_qualification.urls")),
    path("hr/double-teacher/", include("hr_qualification.urls_double_teacher")),
    path("", include("hr10_development.urls")),
    path("hr/assessments/", include("hr_assessment.urls")),
    path("", include("horilla.canonical_hr_api")),
    path("", include("hr_qualification.api.urls")),
    path("", include("hr10_development.api.urls")),
    path("", include("hr_assessment.api.urls")),
]

PARALLEL_HR_ROUTES = [
    ("hr_title", "hr/titles/", "api/v1/hr/titles/"),
    ("hr_appointment", "hr/appointments/", "api/v1/hr/appointments/"),
    ("hr_payroll", "hr/payroll/", "api/v1/hr/payroll/"),
    ("hr_exit", "hr/exit/", "api/v1/hr/exit/"),
    ("hr_self", "hr/self/", "api/v1/hr/self/"),
    ("hr_data", "hr/data/", "api/v1/hr/data/"),
]

for _app, _ui_prefix, _api_prefix in PARALLEL_HR_ROUTES:
    if find_spec(_app) is None:
        continue
    urlpatterns.extend([
        path(_ui_prefix, include(f"{_app}.urls")),
        path(_api_prefix, include(f"{_app}.api_urls")),
    ])

urlpatterns.append(
    re_path(r"^api/hr/v1/(?P<tail>.*)$", legacy_hr_api_redirect, name="legacy-hr-api")
)
