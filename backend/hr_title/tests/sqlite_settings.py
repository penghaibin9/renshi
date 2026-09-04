"""Isolated SQLite settings for the complete HR13 contract suite."""

from pathlib import Path

from hr_appointment.tests.sqlite_settings import *  # noqa: F401,F403


ROOT_URLCONF = "hr_title.tests.sqlite_urls"
BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = BASE_DIR.parent / "frontend"
