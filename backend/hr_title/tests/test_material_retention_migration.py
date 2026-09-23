from pathlib import Path

from django.test import SimpleTestCase


class TitleMaterialRetentionMigrationTests(SimpleTestCase):
    def test_mysql_retention_trigger_is_installed(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "0011_title_material_retention.py"
        ).read_text(encoding="utf-8")
        self.assertIn("BEFORE DELETE ON hr13_title_material_snapshot", source)
        self.assertIn("TITLE_MATERIAL_RETENTION_REQUIRED", source)
        self.assertIn('connection.vendor != "mysql"', source)
