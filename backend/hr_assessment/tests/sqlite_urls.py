"""Canonical HR12 UI and API routes for isolated tests."""

from django.urls import include, path


urlpatterns = [
    path(
        "hr/assessments/",
        include(("hr_assessment.urls", "hr_assessment"), namespace="hr_assessment"),
    ),
    path(
        "",
        include(
            ("hr_assessment.api.urls", "hr_assessment_api"),
            namespace="hr_assessment_api",
        ),
    ),
]
