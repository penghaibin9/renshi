"""Canonical HR05 UI, management API and portal routes for isolated tests."""

from django.urls import include, path


urlpatterns = [
    path("hr/onboarding/", include("hr_onboarding.urls")),
    path("", include("hr_onboarding.api.urls")),
]
