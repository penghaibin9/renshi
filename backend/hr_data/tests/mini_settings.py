"""Isolated SQLite settings for HR18 service tests; never touches user MySQL."""

from pathlib import Path

SECRET_KEY = "hr18-isolated-tests"
DEBUG = False
USE_TZ = True
TIME_ZONE = "UTC"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
ROOT_URLCONF = "hr_data.tests.mini_urls"
BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = BASE_DIR.parent / "frontend"
MIDDLEWARE = []
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "hr_structure",
    "hr_staff",
    "hr_data.apps.HrDataConfig",
]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [FRONTEND_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {},
    }
]
