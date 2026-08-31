"""URL surface used by the isolated HR15 SQLite contract suite."""

from django.urls import include, path

urlpatterns = [
    path(
        "api/v1/hr/payroll/",
        include(("hr_payroll.api_urls", "hr_payroll_api"), namespace="hr_payroll_api"),
    ),
    path(
        "hr/payroll/",
        include(("hr_payroll.urls", "hr_payroll"), namespace="hr_payroll"),
    ),
]
