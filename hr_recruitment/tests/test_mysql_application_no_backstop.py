from pathlib import Path

from django.test import SimpleTestCase


class MysqlApplicationNumberBackstopContractTests(SimpleTestCase):
    def test_migration_enforces_non_blank_numbers_and_allows_blank_drafts(self):
        migration_path = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "0013_mysql_application_no_unique_backstop.py"
        )
        source = migration_path.read_text(encoding="utf-8")

        self.assertIn("GENERATED ALWAYS AS", source)
        self.assertIn("NULLIF(application_no, '')", source)
        self.assertIn("CREATE UNIQUE INDEX", source)
        self.assertIn("HAVING COUNT(*) > 1", source)
        self.assertIn("atomic = False", source)
        self.assertNotIn("except Exception", source)
