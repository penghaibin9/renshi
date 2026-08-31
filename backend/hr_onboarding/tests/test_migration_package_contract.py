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
            '("hr_onboarding", "0006_hronboardingpermissionmeta")',
            migration_0007,
        )
        self.assertEqual(migration_0007.count("migrations.RenameIndex("), 14)
        self.assertIn('new_name="hr_onboardi_case_id_1fc858_idx"', migration_0007)
        self.assertNotIn("hr_ob_outbox_tenant_status_at", migration_0007)

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

        migration_0011 = (
            root / "0011_merge_hr05_migration_branches.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '("hr_onboarding", "0004_hronboardingauthoritymode")',
            migration_0011,
        )
        self.assertIn(
            '("hr_onboarding", "0010_activation_idempotency_tenant_scope")',
            migration_0011,
        )
        self.assertEqual(migration_0011.count("migrations.RenameIndex("), 0)

        migration_0012 = (
            root
            / "0012_rename_hr_ob_outbox_tenant_status_at_hr_onboardi_tenant__8d1b93_idx.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '("hr_onboarding", "0011_merge_hr05_migration_branches")',
            migration_0012,
        )
        self.assertEqual(migration_0012.count("migrations.RenameIndex("), 1)
        self.assertIn('old_name="hr_ob_outbox_tenant_status_at"', migration_0012)
        self.assertIn('new_name="hr_onboardi_tenant__8d1b93_idx"', migration_0012)
