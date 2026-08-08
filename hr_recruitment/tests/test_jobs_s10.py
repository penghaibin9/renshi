"""
hr_recruitment/tests/test_jobs_s10.py

HR04 S10 对账与迁移测试：
- DUAL_READ_COMPARE 生成 discrepancy（legacy hired ≠ authority handoff）；
- 迁移 dry-run 统计（POSSIBLE_MATCH 进人工队列，禁止自动 merge）。
"""

from datetime import date

from django.test import TestCase

from base.models import Company, Department, JobPosition

from hr_recruitment.jobs.dual_read_compare import run_dual_read_compare
from hr_recruitment.jobs.legacy_migrate import migrate_legacy_candidates

TENANT = 9001


class DualReadCompareTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            company="测试大学", hq=True, address="x", country="CN", state="S", city="C", zip="1"
        )
        self.dept = Department.objects.create(department="计算机学院")
        self.dept.company_id.add(self.company)
        self.position = JobPosition.objects.create(
            job_position="专任教师", department_id=self.dept
        )
        self.position.company_id.add(self.company)

    def test_compare_reports_discrepancy(self):
        from recruitment.models import Candidate, Recruitment, Stage

        rec = Recruitment.objects.create(
            title="2026 招聘", vacancy=1, is_published=True,
            company_id=self.company, start_date=date(2026, 1, 1),
        )
        rec.open_positions.add(self.position)
        hired_stage = Stage.objects.create(
            recruitment_id=rec, stage="已录用", stage_type="hired", sequence=5
        )
        Candidate.objects.create(
            name="张三", email="legacy@test.local", mobile="13800003333",
            recruitment_id=rec, job_position_id=self.position, stage_id=hired_stage,
            hired=True, resume="r.pdf",
        )
        report = run_dual_read_compare(tenant_id=TENANT)
        self.assertEqual(report.metrics["legacy_recruitments"], 1)
        self.assertEqual(report.metrics["legacy_hired"], 1)
        # legacy hired 1 ≠ authority handoff 0 → discrepancy
        self.assertTrue(
            any(d["dimension"] == "hired_vs_handoff" for d in report.discrepancies)
        )


class LegacyMigrateTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            company="测试大学", hq=True, address="x", country="CN", state="S", city="C", zip="1"
        )
        self.dept = Department.objects.create(department="计算机学院")
        self.dept.company_id.add(self.company)
        self.position = JobPosition.objects.create(
            job_position="专任教师", department_id=self.dept
        )
        self.position.company_id.add(self.company)

    def test_migrate_dry_run_no_auto_merge(self):
        from recruitment.models import Candidate, Recruitment, Stage

        rec = Recruitment.objects.create(
            title="2026 招聘", vacancy=2, is_published=True,
            company_id=self.company, start_date=date(2026, 1, 1),
        )
        rec.open_positions.add(self.position)
        stage = Stage.objects.create(
            recruitment_id=rec, stage="已报名", stage_type="applied", sequence=0
        )
        Candidate.objects.create(
            name="张三", email="mig@test.local", mobile="13800004444",
            recruitment_id=rec, job_position_id=self.position, stage_id=stage, resume="r.pdf",
        )
        result = migrate_legacy_candidates(tenant_id=TENANT, dry_run=True)
        self.assertEqual(result.candidates_processed, 1)
        # dry-run 不实际创建
        from hr_recruitment.models import HrJobApplication

        self.assertEqual(HrJobApplication.objects.count(), 0)
        self.assertFalse(result.possible_matches)
