"""Isolated SQLite settings for the complete HR03 contract suite."""

from pathlib import Path

from hr_staff.tests.mini_settings import *  # noqa: F401,F403


ROOT_URLCONF = "hr_staff.tests.sqlite_urls"
BASE_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = BASE_DIR
REPO_ROOT = BASE_DIR.parent
FRONTEND_DIR = REPO_ROOT / "frontend"
DATABASES["default"]["NAME"] = ":memory:"  # noqa: F405
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
INSTALLED_APPS = ["django.contrib.sessions", *INSTALLED_APPS]  # noqa: F405
MIGRATION_MODULES = {
    "sessions": None,
    "hr_structure": None,
    "hr_staff": None,
}
MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
]
TEMPLATES[0]["DIRS"] = [  # noqa: F405
    BACKEND_DIR / "hr_staff" / "tests" / "templates",
    FRONTEND_DIR / "templates",
]
TEMPLATES[0]["OPTIONS"] = {
    "context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
    ]
}

