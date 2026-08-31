"""
hr_staff/tests/mini_settings.py —— 轻量验证 settings（仅用于迁移生成与 system check）。

用途：在不加载 Horilla 全栈依赖（pandas/PIL/psycopg2…）的前提下，对 hr_staff + hr_structure
做 makemigrations / check / 迁移重放验证。运行方式：
    python -m django makemigrations hr_staff --settings=hr_staff.tests.mini_settings
    python -m django check --settings=hr_staff.tests.mini_settings
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
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.path.join(os.path.dirname(os.path.dirname(__file__)), "mini_check.sqlite3"),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "Asia/Shanghai"
MIDDLEWARE = []
ROOT_URLCONF = "hr_staff.tests.mini_urls"
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": [], "APP_DIRS": True, "OPTIONS": {}}]
