from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path


class MySQLSettingsContractTests(unittest.TestCase):
    def test_compose_allows_migration_user_to_install_triggers(self):
        repository_root = Path(__file__).resolve().parents[1]
        compose = (repository_root / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("--log-bin-trust-function-creators=1", compose)

    def test_db_engine_mysql_never_inherits_sqlite_timeout(self):
        repository_root = Path(__file__).resolve().parents[1]
        environment = os.environ.copy()
        environment.pop("DATABASE_URL", None)
        environment.update(
            {
                "DB_ENGINE": "django.db.backends.mysql",
                "DB_NAME": "renshi_settings_contract",
                "DB_USER": "contract_user",
                "DB_PASSWORD": "contract_password",
                "DB_HOST": "127.0.0.1",
                "DB_PORT": "3306",
                "DB_INIT_PASSWORD": "contract-init-password",
                "SECRET_KEY": "contract-only-strong-secret-key",
                "ALLOWED_HOSTS": "localhost,127.0.0.1",
            }
        )
        script = """
from horilla.settings import DATABASES

database = DATABASES["default"]
assert database["ENGINE"] == "django.db.backends.mysql", database
assert "timeout" not in database["OPTIONS"], database["OPTIONS"]
assert database["OPTIONS"]["charset"] == "utf8mb4", database["OPTIONS"]
assert database["OPTIONS"]["isolation_level"] == "read committed", database["OPTIONS"]
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=repository_root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
