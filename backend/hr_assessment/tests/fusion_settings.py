"""R11-to-HR archive integration tests only; never a deployment settings module.

SQLite syncs this focused app set for ORM/HTTP tests. Production settings and
MySQL seals are unchanged and must be exercised separately before release.
"""
from hr_exit.tests.sqlite_settings import *  # noqa: F403,F401
from pathlib import Path

INSTALLED_APPS = [*INSTALLED_APPS, "django.contrib.sessions", "hr_assessment", "hr_qualification", "hr10_development", "hr_external", "hr_title"]
MIGRATION_MODULES = {**MIGRATION_MODULES, **{name: None for name in ("sessions", "hr_assessment", "hr_qualification", "hr10_development", "hr_external", "hr_title")}}
ROOT_URLCONF = "hr_assessment.tests.sqlite_urls"
BASE_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = BASE_DIR
FRONTEND_DIR = BASE_DIR.parent / 'frontend'
STATIC_URL = '/static/'
MIDDLEWARE = ['django.contrib.sessions.middleware.SessionMiddleware', 'django.contrib.auth.middleware.AuthenticationMiddleware', 'django.middleware.csrf.CsrfViewMiddleware']
AUTHENTICATION_BACKENDS = ['django.contrib.auth.backends.ModelBackend']
COMPANY_SCOPED_PERMISSIONS = False  # Test identity membership is supplied explicitly.
TEMPLATES[0]['DIRS'] = [FRONTEND_DIR / 'templates']
ALLOWED_HOSTS = ['testserver', '127.0.0.1', 'localhost']

# Existing HR10 index name exceeds Django portable 30-char limit; recorded test isolation only.
SILENCED_SYSTEM_CHECKS = ["models.E034"]
