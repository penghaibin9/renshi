"""Isolated SQLite settings for HR05 service tests; never touches developer MySQL."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]

SECRET_KEY = "hr05-isolated-test-only"
DEBUG = False
USE_TZ = True
TIME_ZONE = "UTC"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
ROOT_URLCONF = "hr_onboarding.tests.mini_urls"
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
    "hr_onboarding.tests.mini_apps.HrOnboardingMiniConfig",
]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
