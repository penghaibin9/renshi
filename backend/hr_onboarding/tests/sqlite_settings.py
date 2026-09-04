"""Isolated SQLite settings for the complete HR05 contract suite."""

from pathlib import Path

from hr_changes.tests.sqlite_settings import *  # noqa: F401,F403


ROOT_URLCONF = "hr_onboarding.tests.sqlite_urls"
BASE_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = BASE_DIR
FRONTEND_DIR = BASE_DIR.parent / "frontend"
STATIC_URL = "/static/"

INSTALLED_APPS = [
    "django.contrib.sessions",
    *INSTALLED_APPS,  # noqa: F405
]
MIGRATION_MODULES = {
    **MIGRATION_MODULES,  # noqa: F405
    "sessions": None,
}
TEMPLATES[0]["DIRS"] = [  # noqa: F405
    BACKEND_DIR / "hr_onboarding" / "tests" / "templates",
    FRONTEND_DIR / "templates",
]
TEMPLATES[0]["OPTIONS"]["context_processors"] = [  # noqa: F405
    "django.template.context_processors.request",
    "django.contrib.auth.context_processors.auth",
]
