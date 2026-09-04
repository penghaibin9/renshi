"""Isolated SQLite settings for the complete HR06 contract suite."""

from pathlib import Path

from hr_external.tests.sqlite_settings import *  # noqa: F401,F403


ROOT_URLCONF = "hr_changes.tests.sqlite_urls"
BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = BASE_DIR.parent / "frontend"

INSTALLED_APPS = [
    *INSTALLED_APPS,  # noqa: F405
    "hr_recruitment",
    "hr_onboarding",
    "hr_changes",
]
MIGRATION_MODULES = {
    **MIGRATION_MODULES,  # noqa: F405
    "hr_recruitment": None,
    "hr_onboarding": None,
    "hr_changes": None,
}

