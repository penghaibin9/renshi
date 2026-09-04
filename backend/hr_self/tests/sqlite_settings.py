"""Minimal SQLite settings for the isolated HR17 production contract suite."""

from pathlib import Path

from django.apps import AppConfig


class HrAssessmentTestConfig(AppConfig):
    """Load HR12 Authority models without installing legacy PMS write seals."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "hr_assessment"


class HrPayrollTestConfig(AppConfig):
    """Load HR15 Authority models without importing retired payroll models."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "hr_payroll"

    def ready(self):
        from hr_payroll import (  # noqa: F401
            authority_models,
            calculation_models,
            legacy_takeover_models,
            statutory_models,
        )


SECRET_KEY = "hr17-isolated-contract-tests"
DEBUG = False
USE_TZ = True
TIME_ZONE = "Asia/Shanghai"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = BASE_DIR.parent / "frontend"
ROOT_URLCONF = "hr_self.tests.sqlite_urls"

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "horilla_auth",
    "hr_structure",
    "hr_staff",
    "hr_time",
    "hr_contracts",
    "hr_external",
    "hr_qualification",
    "hr10_development",
    "hr_self.tests.sqlite_settings.HrAssessmentTestConfig",
    "hr_title",
    "hr_appointment",
    "hr_exit",
    "hr_self.tests.sqlite_settings.HrPayrollTestConfig",
    "hr_self",
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
        "DIRS": [FRONTEND_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {},
    }
]
MIGRATION_MODULES = {
    "horilla_auth": None,
    "hr_structure": None,
    "hr_staff": None,
    "hr_time": None,
    "hr_contracts": None,
    "hr_external": None,
    "hr_qualification": None,
    "hr10_development": None,
    "hr_assessment": None,
    "hr_title": None,
    "hr_appointment": None,
    "hr_exit": None,
    "hr_payroll": None,
    "hr_self": None,
}
