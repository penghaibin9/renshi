"""Canonical HR06 UI and API routes for isolated tests."""

from django.urls import include, path


urlpatterns = [
    path(
        "hr/changes/",
        include(("hr_changes.urls", "hr_changes"), namespace="hr_changes"),
    ),
    path("", include("hr_changes.api.urls")),
]

