"""Isolated SQLite settings for the HR09 authority contract suite."""

from hr_assessment.tests.sqlite_settings import *  # noqa: F401,F403


ROOT_URLCONF = "hr_qualification.tests.sqlite_urls"
INSTALLED_APPS = [
    *INSTALLED_APPS,  # noqa: F405
    "hr_external",
]
MIGRATION_MODULES = {
    **MIGRATION_MODULES,  # noqa: F405
    "hr_external": None,
}

