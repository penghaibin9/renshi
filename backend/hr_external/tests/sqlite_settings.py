"""Isolated SQLite settings for the complete HR08 contract suite."""

from pathlib import Path

from hr_exit.tests.sqlite_settings import *  # noqa: F401,F403


ROOT_URLCONF = "hr_external.tests.sqlite_urls"
BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = BASE_DIR.parent / "frontend"
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]

INSTALLED_APPS = [
    *INSTALLED_APPS,  # noqa: F405
    "hr_external",
]
MIGRATION_MODULES = {
    **MIGRATION_MODULES,  # noqa: F405
    "hr_external": None,
}

