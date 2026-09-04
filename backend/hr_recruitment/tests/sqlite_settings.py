"""Isolated SQLite settings for the complete HR04 contract suite."""

from pathlib import Path

from hr_onboarding.tests.sqlite_settings import *  # noqa: F401,F403


ROOT_URLCONF = "hr_recruitment.tests.sqlite_urls"
BASE_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = BASE_DIR
FRONTEND_DIR = BASE_DIR.parent / "frontend"
STATIC_URL = "/static/"

