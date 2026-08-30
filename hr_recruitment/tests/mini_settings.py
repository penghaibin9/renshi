"""Isolated SQLite settings for HR04 authority unit tests only.

Production and acceptance remain MySQL-only.  This module deliberately loads
just the three authority apps needed to exercise the service without touching
a developer's database.
"""

SECRET_KEY = "hr04-isolated-test-only"
DEBUG = False
USE_TZ = True
TIME_ZONE = "UTC"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
ROOT_URLCONF = "hr_recruitment.tests.mini_urls"
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
    "hr_recruitment",
]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
