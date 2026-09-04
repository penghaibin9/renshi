"""Canonical URL surface for the isolated HR16 test suite."""

from django.urls import include, path


urlpatterns = [
    path(
        "api/v1/hr/exit/",
        include(("hr_exit.api_urls", "hr_exit_api"), namespace="hr_exit_api"),
    ),
    path(
        "hr/exit/",
        include(("hr_exit.urls", "hr_exit"), namespace="hr_exit"),
    ),
]

