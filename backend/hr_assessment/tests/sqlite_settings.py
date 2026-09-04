"""Isolated SQLite settings for the HR12 authority contract suite."""

from hr_appointment.tests.sqlite_settings import *  # noqa: F401,F403


ROOT_URLCONF = "hr_assessment.tests.sqlite_urls"
INSTALLED_APPS = [
    "auditlog",
    "hr_control_center",
    "hr_qualification",
    "hr10_development",
    *INSTALLED_APPS,  # noqa: F405
]
MIGRATION_MODULES = {
    **MIGRATION_MODULES,  # noqa: F405
    "auditlog": None,
    "hr_control_center": None,
    "hr_qualification": None,
    "hr10_development": None,
}
