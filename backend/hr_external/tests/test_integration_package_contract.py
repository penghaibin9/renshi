from pathlib import Path

from django.test import SimpleTestCase


class IntegrationPackageContractTests(SimpleTestCase):
    def test_package_exports_do_not_eagerly_import_optional_authorities(self):
        source = (
            Path(__file__).resolve().parents[1] / "integrations" / "__init__.py"
        ).read_text(encoding="utf-8")

        self.assertIn("def __getattr__(name):", source)
        self.assertNotIn("from hr_external.integrations.hr07 import", source)
        self.assertNotIn("from hr_external.integrations.hr15 import", source)
