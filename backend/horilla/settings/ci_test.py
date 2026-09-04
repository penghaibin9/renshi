"""CI settings: MySQL is the only acceptance database."""

import os

# CI must exercise the same canonical HR01-HR18 app registry and provider
# configuration as the unified runtime settings entrypoint. Importing base.py
# directly silently omitted HR09-HR18 and made migration/test discovery partial.
from horilla.settings import *  # noqa: F401,F403
from horilla.settings.runtime_seals import install_legacy_runtime_seals

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.getenv("MYSQL_DATABASE", "renshi_db"),
        "USER": os.getenv("MYSQL_USER", "renshi_user"),
        "PASSWORD": os.getenv("MYSQL_PASSWORD", "renshi_pass"),
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

# Database-backed template overrides are an integration concern. Static and
# permission contract tests must be able to compile filesystem templates
# without making forbidden database queries from SimpleTestCase.
TEMPLATES[0]["OPTIONS"]["loaders"] = [
    ("django.template.loaders.filesystem.Loader", [BASE_DIR / THEME_APP / "templates"]),
    "django.template.loaders.app_directories.Loader",
    ("django.template.loaders.filesystem.Loader", [FRONTEND_DIR / "templates"]),
]

install_legacy_runtime_seals(globals())
