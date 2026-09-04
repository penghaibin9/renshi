"""跨域迁移/对账任务必须显式限定学校，且不得猜测跨域主键。"""

from pathlib import Path

from django.test import SimpleTestCase

from hr_changes.jobs.reconcile_projection import run_reconcile


BACKEND = Path(__file__).resolve().parents[2]


class LegacyTenantScopeContractTests(SimpleTestCase):
    def test_hr04_compare_and_migration_scope_legacy_rows(self):
        compare = (BACKEND / "hr_recruitment" / "jobs" / "dual_read_compare.py").read_text(
            encoding="utf-8"
        )
        migrate = (BACKEND / "hr_recruitment" / "jobs" / "legacy_migrate.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("company_id_id=tenant_id", compare)
        self.assertIn("recruitment_id__company_id_id=tenant_id", compare)
        self.assertIn("recruitment_id__company_id_id=tenant_id", migrate)

    def test_hr04_position_mapping_uses_hr02_link_not_equal_integer_ids(self):
        source = (BACKEND / "hr_recruitment" / "jobs" / "legacy_migrate.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("HrLegacyObjectLink.objects.filter", source)
        self.assertIn('legacy_model="jobposition"', source)
        self.assertNotIn("post_catalog_id=legacy_candidate.job_position_id_id", source)

    def test_hr06_reconcile_refuses_unscoped_run(self):
        with self.assertRaises(ValueError):
            run_reconcile(tenant_id=None)

    def test_hr12_legacy_queries_are_tenant_scoped(self):
        compare = (
            BACKEND / "hr_assessment" / "management" / "commands" / "dual_read_compare.py"
        ).read_text(encoding="utf-8")
        migrate = (
            BACKEND / "hr_assessment" / "management" / "commands" / "migrate_pms.py"
        ).read_text(encoding="utf-8")
        for source in (compare, migrate):
            self.assertIn("company_id_id=tenant_id", source)
            self.assertIn("employee_work_info__company_id_id=tenant_id", source)

    def test_hr12_migration_has_no_dry_run_only_noop_steps(self):
        source = (
            BACKEND / "hr_assessment" / "management" / "commands" / "migrate_pms.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("if dry else 0", source)
        self.assertNotIn("objects.all()", source)
        self.assertIn("HrGoalAssignment.objects.get_or_create", source)
        self.assertIn("HrGoalMeasure.objects.get_or_create", source)
        self.assertIn("HrQuestionnaireVersion.objects.get_or_create", source)
        self.assertIn("HrMultiRaterSession.objects.get_or_create", source)
        self.assertIn("HrMultiRaterFeedback.objects.get_or_create", source)
