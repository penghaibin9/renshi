"""Isolated SQLite settings for configuration/integration infrastructure unit tests."""
import os
from cryptography.fernet import Fernet

SECRET_KEY = "hr-integration-mini-settings-only"
DEBUG = True
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "hr_configuration",
    "hr_integration",
]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "Asia/Shanghai"
MIDDLEWARE = []
ROOT_URLCONF = "hr_integration.tests.mini_urls"
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": [], "APP_DIRS": True, "OPTIONS": {}}]
FIELD_ENCRYPTION_KEYS = "test:" + Fernet.generate_key().decode("ascii")
HR_INTEGRATION_ALLOWED_HOSTS = ("127.0.0.1", "localhost", "example.edu.cn", "sso.example.edu.cn")
HR_INTEGRATION_HTTP_TIMEOUT_SECONDS = 2
