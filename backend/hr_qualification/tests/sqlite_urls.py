"""Canonical HR09 UI and API routes for isolated tests."""

from django.urls import include, path


urlpatterns = [
    path(
        "hr/qualifications/",
        include(("hr_qualification.urls", "hr_qualification"), namespace="hr_qualification"),
    ),
    path(
        "hr/double-teacher/",
        include(
            ("hr_qualification.urls_double_teacher", "hr_double_teacher"),
            namespace="hr_double_teacher",
        ),
    ),
    path("", include("hr_qualification.api.urls")),
]
