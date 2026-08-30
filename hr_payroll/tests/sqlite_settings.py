"""Minimal SQLite settings for isolated HR15 service and API contract tests."""

from django.apps import AppConfig


class HrPayrollTestConfig(AppConfig):
    """Load HR15 models without wiring the legacy Payslip runtime seal."""

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

SECRET_KEY = "hr15-payment-provider-sqlite-tests"
DEBUG = False
USE_TZ = True
TIME_ZONE = "Asia/Shanghai"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
ROOT_URLCONF = "hr_payroll.tests.sqlite_urls"

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "horilla_auth",
    "hr_structure",
    "hr_staff",
    "hr_time",
    "hr_exit",
    "hr_payroll.tests.sqlite_settings.HrPayrollTestConfig",
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

# These tests validate current ORM/service contracts, not production migration
# replay. MySQL migration acceptance remains a separate normal-settings gate.
MIGRATION_MODULES = {
    "hr_structure": None,
    "hr_staff": None,
    "horilla_auth": None,
    "hr_time": None,
    "hr_exit": None,
    "hr_payroll": None,
}
