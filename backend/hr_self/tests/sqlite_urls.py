"""Canonical URL surface for the isolated HR17 test suite."""

from django.urls import include, path


urlpatterns = [
    path(
        "api/v1/hr/self/",
        include(("hr_self.api_urls", "hr_self_api"), namespace="hr_self_api"),
    ),
    path(
        "hr/self/",
        include(("hr_self.urls", "hr_self"), namespace="hr_self"),
    ),
]
