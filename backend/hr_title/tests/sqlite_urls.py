"""Canonical HR13 UI and API routes for isolated tests."""

from django.urls import include, path


urlpatterns = [
    path(
        "hr/titles/",
        include(("hr_title.urls", "hr_title"), namespace="hr_title"),
    ),
    path(
        "api/v1/hr/titles/",
        include(("hr_title.api_urls", "hr_title_api"), namespace="hr_title_api"),
    ),
]
