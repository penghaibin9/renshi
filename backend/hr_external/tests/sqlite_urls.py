"""Canonical HR08 UI and API routes for isolated tests."""

from django.urls import include, path


urlpatterns = [
    path(
        "hr/external-teachers/",
        include(("hr_external.urls", "hr_external"), namespace="hr_external"),
    ),
    path("", include("hr_external.api.urls")),
]

