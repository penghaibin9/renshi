"""Minimal isolated SQLite settings for HR10/HR03 service tests only."""

SECRET_KEY = "hr10-sqlite-service-test-only"
DEBUG = False
USE_TZ = True
TIME_ZONE = "Asia/Shanghai"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "horilla_auth.HorillaUser"

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "horilla_auth",
    "hr_structure",
    "hr_staff",
    "hr10_development",
    "hr_time",
]

ROOT_URLCONF = "hr10_development.tests.urls"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# These service tests need current model tables, not production migration
# execution. MySQL migration acceptance remains covered by the normal settings.
MIGRATION_MODULES = {
    "horilla_auth": None,
    "hr_structure": None,
    "hr_staff": None,
    "hr10_development": None,
    "hr_time": None,
}
