"""Canonical HR11 routes needed by the isolated test suite."""

from django.urls import path

from hr_time.api.views import time_health


urlpatterns = [
    path("api/v1/hr/time/health", time_health, name="hr11-api-time-health"),
]
