"""
hr_staff/tests/mini_settings_pg.py —— PostgreSQL 版轻量验证 settings。

在 Docker db（postgres:16）上验证 clean-DB 迁移与 HR03 全量测试。
用法：同 generate_migrations.py runner，DJANGO_SETTINGS_MODULE=hr_staff.tests.mini_settings_pg。
"""

import os

SECRET_KEY = "hr03-mini-settings-secret-key-for-verification-only"

DEBUG = True

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "hr_structure",
    "hr_staff",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("PG_DB", "horilla_db"),
        "USER": os.environ.get("PG_USER", "horilla_user"),
        "PASSWORD": os.environ.get("PG_PASSWORD", "horilla_pass"),
        "HOST": os.environ.get("PG_HOST", "127.0.0.1"),
        "PORT": os.environ.get("PG_PORT", "5432"),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "Asia/Shanghai"
MIDDLEWARE = []
ROOT_URLCONF = "hr_staff.tests.mini_urls"
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": [], "APP_DIRS": True, "OPTIONS": {}}]
