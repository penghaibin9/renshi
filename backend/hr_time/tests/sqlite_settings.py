"""Isolated SQLite settings for the complete HR11 contract suite.

The production settings intentionally reject SQLite.  These settings exercise
HR11 and the two read-only legacy adapters without contacting the workstation's
MySQL runtime or starting legacy schedulers from AppConfig.ready().
"""

SECRET_KEY = "hr11-isolated-contract-tests"
DEBUG = False
USE_TZ = True
TIME_ZONE = "Asia/Shanghai"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
ROOT_URLCONF = "hr_time.tests.sqlite_urls"
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "horilla_auth",
    "hr_structure",
    "hr_staff",
    "hr_time",
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
MIDDLEWARE = [
]
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {},
    }
]

# Tests validate Python/ORM behavior here. MySQL DDL authority seals have their
# own static and MySQL acceptance tests.
MIGRATION_MODULES = {
    "horilla_auth": None,
    "hr_structure": None,
    "hr_staff": None,
    "hr_time": None,
}

LOGIN_URL = "/login/"
STATIC_URL = "/static/"
