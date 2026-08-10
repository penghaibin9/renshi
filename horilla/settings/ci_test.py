"""CI settings: MySQL is the only acceptance database."""

import os

from horilla.settings.base import *  # noqa: F401,F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.getenv("MYSQL_DATABASE", "horilla_db"),
        "USER": os.getenv("MYSQL_USER", "horilla_user"),
        "PASSWORD": os.getenv("MYSQL_PASSWORD", "horilla_pass"),
        "HOST": os.getenv("MYSQL_HOST", "127.0.0.1"),
        "PORT": os.getenv("MYSQL_PORT", "3306"),
        "CONN_MAX_AGE": 0,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {
            "charset": "utf8mb4",
            "init_command": (
                "SET sql_mode='STRICT_TRANS_TABLES,NO_ZERO_DATE,"
                "NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO'"
            ),
            "isolation_level": "read committed",
        },
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}
