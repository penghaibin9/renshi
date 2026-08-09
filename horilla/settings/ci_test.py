"""
CI test settings — inherits base, overrides DB for Docker PostgreSQL.
"""
import os
from horilla.settings.base import *  # noqa: F401,F403

# Override database for CI testing
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "horilla_db",
        "USER": "horilla_user",
        "PASSWORD": "horilla_pass",
        "HOST": "127.0.0.1",
        "PORT": "5432",
        "OPTIONS": {
            "connect_timeout": 10,
        },
    }
}

# Disable Redis for CI (not needed for check + test)
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}
