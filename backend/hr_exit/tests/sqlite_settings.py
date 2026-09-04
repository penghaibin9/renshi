"""Minimal SQLite settings for the isolated HR16 production contract suite."""

from django.apps import AppConfig


class HrPayrollTestConfig(AppConfig):
    """Register HR15 models without importing the retired payroll runtime."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "hr_payroll"

    def ready(self):
        from hr_payroll import (  # noqa: F401
            authority_models,
            authority_registry,
            calculation_models,
            legacy_takeover_models,
            statutory_models,
        )


SECRET_KEY = "hr16-isolated-contract-tests"
DEBUG = False
USE_TZ = True
TIME_ZONE = "Asia/Shanghai"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
ROOT_URLCONF = "hr_exit.tests.sqlite_urls"

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "horilla_auth",
    "hr_structure",
    "hr_staff",
    "hr_time",
    "hr_contracts",
    "hr_appointment",
    "hr_exit",
    "hr_exit.tests.sqlite_settings.HrPayrollTestConfig",
]

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
AUTH_USER_MODEL = "horilla_auth.HorillaUser"
MIDDLEWARE = []
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {},
    }
]

# Service tests validate ORM and workflow contracts without requiring a host
# MySQL credential.  MySQL DDL seals remain covered by static migration tests.
MIGRATION_MODULES = {
    "horilla_auth": None,
    "hr_structure": None,
    "hr_staff": None,
    "hr_time": None,
    "hr_contracts": None,
    "hr_appointment": None,
    "hr_exit": None,
    "hr_payroll": None,
}

