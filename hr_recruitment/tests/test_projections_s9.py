"""
hr_recruitment/tests/test_projections_s9.py

HR04 S9 Legacy Projection 测试：
- Recruitment → Campaign 投影（只读，vacancy 仅展示）；
- Stage → WorkflowStage 投影（stage_type 不作权威）；
- Candidate → Candidate+Application 投影（一条 legacy = 一次申请）。
"""

from datetime import date

from django.test import TestCase

from base.models import Company, Department, JobPosition

from hr_recruitment.projections.horilla_candidate import project_candidate
from hr_recruitment.projections.horilla_recruitment import project_recruitment_to_campaign
from hr_recruitment.projections.horilla_stage import project_stage, stage_type_to_canonical

TENANT = 8001


class HorillaRecruitmentProjectionTests(TestCase):
    def setUp(self):
        from recruitment.models import Recruitment

        self.company = Company.objects.create(
            company="测试大学", hq=True, address="x", country="CN", state="S", city="C", zip="1"
        )
        self.dept = Department.objects.create(department="计算机学院")
        self.dept.company_id.add(self.company)
        self.position = JobPosition.objects.create(
            job_position="专任教师", department_id=self.dept
        )
        self.position.company_id.add(self.company)
        self.rec = Recruitment.objects.create(
            title="2026 教师招聘",
            description="测试",
            is_event_based=False,
            vacancy=3,
            is_published=True,
            company_id=self.company,
            start_date=date(2026, 3, 1),
        )
        self.rec.open_positions.add(self.position)

    def test_recruitment_to_campaign_projection(self):
        projection = project_recruitment_to_campaign(self.rec)
        self.assertEqual(projection.legacy_recruitment_id, self.rec.id)
        self.assertEqual(projection.title, "2026 教师招聘")
        self.assertEqual(projection.vacancy, 3)
        self.assertEqual(projection.source, "LEGACY_RECRUITING_ONLY")
        # 只读投影，不改 legacy
        self.rec.refresh_from_db()
        self.assertFalse(self.rec.closed)

    def test_stage_projection_maps_type(self):
        from recruitment.models import Stage

        stage = Stage.objects.create(
            recruitment_id=self.rec, stage="笔试", stage_type="test", sequence=1
        )
        projection = project_stage(stage)
        self.assertEqual(projection.stage_type, "test")
        self.assertEqual(projection.suggested_canonical_status, "ASSESSMENT_PENDING")
        self.assertEqual(stage_type_to_canonical("hired"), "PROPOSED_HIRE")
        # stage_type 只作建议，不是权威判定
        self.assertNotEqual(projection.suggested_canonical_status, "HANDOFF_TO_HR05")

    def test_candidate_projection_single_application(self):
        from recruitment.models import Candidate, Stage

        stage = Stage.objects.create(
            recruitment_id=self.rec, stage="已报名", stage_type="applied", sequence=0
        )
        cand = Candidate.objects.create(
            name="张三",
            email="proj@test.local",
            mobile="13800002222",
            recruitment_id=self.rec,
            job_position_id=self.position,
            stage_id=stage,
            resume="x.pdf",
        )
        projection = project_candidate(cand)
        self.assertEqual(projection.legacy_candidate_id, cand.id)
        self.assertEqual(projection.recruitment_id, self.rec.id)
        # 未迁移 → INSUFFICIENT_DATA
        self.assertEqual(projection.identity_match_result, "INSUFFICIENT_DATA")
        self.assertIsNone(projection.candidate_id)
        # hired 只是 legacy 展示
        self.assertFalse(projection.hired)
