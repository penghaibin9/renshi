from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class Hr05MigrationPackageContractTests(SimpleTestCase):
    def test_hr05_migrations_are_an_importable_single_graph(self):
        root = Path(settings.BASE_DIR) / "hr_onboarding" / "migrations"
        self.assertTrue((root / "__init__.py").is_file())

        migration_0007 = (
            root
            / "0007_rename_hr_ob_act_case_status_idx_hr_onboardi_case_id_1fc858_idx_and_more.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '("hr_onboarding", "0004_hronboardingauthoritymode")',
            migration_0007,
        )
        self.assertIn(
            '("hr_onboarding", "0006_hronboardingpermissionmeta")',
            migration_0007,
        )
        self.assertEqual(migration_0007.count("migrations.RenameIndex("), 15)
        self.assertIn('new_name="hr_onboardi_case_id_1fc858_idx"', migration_0007)

        migration_0008 = (
            root / "0008_hronboardingcase_actual_report_idx.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '"0007_rename_hr_ob_act_case_status_idx_hr_onboardi_case_id_1fc858_idx_and_more"',
            migration_0008,
        )

        migration_0009 = (
            root / "0009_auto_index_complete.py"
        ).read_text(encoding="utf-8")
        self.assertIn("hr_onboardi_tenant__6b7ff7_idx", migration_0009)
