"""Explicit HR01~HR12 URL registry.

Do not mutate ``horilla.urls.urlpatterns`` from AppConfig.ready(). Keeping the
routing graph in one file makes startup deterministic and makes the module map
obvious to a beginner.
"""

from django.urls import include, path

urlpatterns = [
    # HR01
    path("hr/", include("hr_control_center.urls")),
    path("", include("hr_control_center.api.urls")),
    # HR02
    path("hr/structure/", include("hr_structure.urls")),
    path("", include("hr_structure.api.urls")),
    # HR03
    path("hr/staff/", include("hr_staff.urls")),
    path("", include("hr_staff.api.urls")),
    # HR04
    path("hr/recruitment/", include("hr_recruitment.urls")),
    path("", include("hr_recruitment.public.urls")),
    path("", include("hr_recruitment.api.urls")),
    # HR05
    path("hr/onboarding/", include("hr_onboarding.urls")),
    path("", include("hr_onboarding.api.urls")),
    # HR06
    path("hr/changes/", include("hr_changes.urls")),
    path("", include("hr_changes.api.urls")),
    # HR07 is intentionally NOT routed until its missing Authority app/models/
    # migrations/tests are recovered and pass MySQL acceptance.
    # HR08
    path("hr/external-teachers/", include("hr_external.urls")),
    path("", include("hr_external.api.urls")),
    # HR09
    path("hr/qualifications/", include("hr_qualification.urls")),
    path("hr/double-teacher/", include("hr_qualification.urls_double_teacher")),
    path("", include("hr_qualification.api.urls")),
    # HR10 (its URL modules own their canonical sub-prefixes)
    path("", include("hr10_development.urls")),
    path("", include("hr10_development.api.urls")),
    # HR11
    path("", include("hr_time.api.urls")),
    # HR12
    path("hr/assessments/", include("hr_assessment.urls")),
    path("", include("hr_assessment.api.urls")),
]
