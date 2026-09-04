"""Keep optional dynamic-field startup separate from migration discovery."""

from pathlib import Path

from django.test import SimpleTestCase


BACKEND_ROOT = Path(__file__).resolve().parents[1]


class DynamicFieldsStartupContractTests(SimpleTestCase):
    def test_runtime_signals_are_loaded_by_app_config_not_migration_package(self):
        migration_init = (
            BACKEND_ROOT / "dynamic_fields" / "migrations" / "__init__.py"
        ).read_text(encoding="utf-8")
        app_config = (
            BACKEND_ROOT / "dynamic_fields" / "apps.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn("from dynamic_fields import signals", migration_init)
        self.assertIn("from dynamic_fields import signals", app_config)
