from pathlib import Path

from django.test import SimpleTestCase


class MysqlActiveExitBackstopContractTests(SimpleTestCase):
    def test_migration_installs_fail_loud_generated_unique_guard(self):
        migration_path = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "0018_mysql_active_exit_unique_backstop.py"
        )
        source = migration_path.read_text(encoding="utf-8")

        self.assertIn("GENERATED ALWAYS AS", source)
        self.assertIn("CREATE UNIQUE INDEX", source)
        self.assertIn("active_exit_guard", source)
        self.assertIn("HAVING COUNT(*) > 1", source)
        self.assertIn("atomic = False", source)
        self.assertNotIn("except Exception", source)
