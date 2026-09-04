"""Isolated SQLite settings for the complete HR14 contract suite."""

from hr_exit.tests.sqlite_settings import *  # noqa: F401,F403


ROOT_URLCONF = "hr_appointment.tests.sqlite_urls"
INSTALLED_APPS = [
    *INSTALLED_APPS,  # noqa: F405
    "hr_assessment",
    "hr_title",
]

# Keep HR14's real migration graph enabled because the suite verifies that its
# authority-seal migration is the single deployable leaf. Related domains are
# synchronized directly for fast, isolated service tests.
MIGRATION_MODULES = {
    **MIGRATION_MODULES,  # noqa: F405
    "hr_assessment": None,
    "hr_title": None,
}
MIGRATION_MODULES.pop("hr_appointment", None)

