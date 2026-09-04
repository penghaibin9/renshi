"""Canonical HR14 UI and API routes for isolated tests."""

from django.urls import include, path


urlpatterns = [
    path(
        "hr/appointments/",
        include(("hr_appointment.urls", "hr_appointment"), namespace="hr_appointment"),
    ),
    path(
        "api/v1/hr/appointments/",
        include(
            ("hr_appointment.api_urls", "hr_appointment_api"),
            namespace="hr_appointment_api",
        ),
    ),
]
