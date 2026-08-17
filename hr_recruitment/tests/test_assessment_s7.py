"""
hr_recruitment/tests/test_assessment_s7.py

HR04-05 考试面试与考察（S7）测试：
- 评分方案版本（LOCKED 后不可变）；
- 组件权重、服务端总分（禁止前端提交 total）；
- 评分 DRAFT→SUBMITTED→LOCKED；
- 解锁特权流程（REOPEN_REQUESTED→APPROVED→DRAFT）；
- 专家回避（conflict status）；
- 盲评上下文服务端裁剪；
- 结果快照冻结排名（锁定后不改）。
"""

from datetime import date
from uuid import uuid4

from django.test import TestCase

from hr_recruitment.api.exceptions import ScoreAlreadyLockedError
from hr_recruitment.constants import ScoreSheetStatus
from hr_recruitment.models import (
    HrAssessmentEvent,
    HrCandidateScoreSheet,
    HrEvaluatorAssignment,
    HrRecruitmentCandidate,
)
from hr_recruitment.services.application_service import ApplicationService
from hr_recruitment.services.assessment_service import (
    AssessmentService,
    AssessmentServiceError,
)
from hr_recruitment.services.campaign_service import CampaignService
from hr_recruitment.services.candidate_service import CandidateService
from hr_recruitment.services.qualification_service import QualificationService

TENANT = 6001


class AssessmentServiceTests(TestCase):
    def setUp(self):
        self.camp_service = CampaignService(tenant_id=TENANT, actor="test")
        self.campaign = self.camp_service.create_campaign(
            code="2026-A-001", title="选拔测试", campaign_type="SINGLE_POSITION"
        )
        self.position = self.camp_service.create_position(
            campaign_id=str(self.campaign.id),
            post_catalog_name="专任教师",
            planned_headcount=1,
        )
        self.service = AssessmentService(tenant_id=TENANT, actor="expert-1")
        # 评分方案：笔试 30 + 面试 70
        self.scheme = self.service.create_scheme(position_id=str(self.position.id))
        self.exam = self.service.add_component(
            scheme_version_id=str(self.scheme.id),
            component_type="WRITTEN_EXAM",
            name="笔试",
            weight=30,
            max_score=100,
        )
        self.interview = self.service.add_component(
            scheme_version_id=str(self.scheme.id),
            component_type="INTERVIEW",
            name="面试",
            weight=70,
            max_score=100,
        )
        self.service.lock_scheme(scheme_version_id=str(self.scheme.id))
        # 申请（QUALIFIED 后进入选拔）
        self.candidate_service = CandidateService(tenant_id=TENANT)
        self.candidate = self.candidate_service.create_candidate(
            legal_name="张三", primary_email="a@test.local"
        )
        self.app_service = ApplicationService(tenant_id=TENANT, actor="test")
        draft = self.app_service.save_draft(
            candidate_id=str(self.candidate.id),
            recruitment_position_id=str(self.position.id),
        )
        self.app = self.app_service.submit(application_id=str(draft.id))
        # 场次 + 专家
        self.event = self.service.create_event(
            component_id=str(self.exam.id),
            title="笔试场次",
            event_date=date(2026, 5, 1),
        )
        self.evaluator = self.service.assign_evaluator(
            event_id=str(self.event.id), evaluator_staff_id=101, role="主考"
        )

    def test_scheme_locked_immutable(self):
        with self.assertRaises(AssessmentServiceError):
            self.service.add_component(
                scheme_version_id=str(self.scheme.id),
                component_type="INTERVIEW",
                name="追加面试",
                weight=10,
            )

    def test_score_sheet_lifecycle(self):
        sheet = self.service.create_score_sheet(
            application_id=str(self.app.id),
            event_id=str(self.event.id),
            evaluator_id=str(self.evaluator.id),
        )
        self.assertEqual(sheet.status, ScoreSheetStatus.DRAFT)
        # 保存草稿（不提交）
        sheet = self.service.save_scores(
            score_sheet_id=str(sheet.id),
            scores={str(self.exam.id): 80},
        )
        self.assertEqual(sheet.status, ScoreSheetStatus.DRAFT)
        # 提交 → SUBMITTED，总分服务端计算 = 80/100×30 = 24
        sheet = self.service.save_scores(
            score_sheet_id=str(sheet.id),
            scores={str(self.exam.id): 80},
            submit=True,
        )
        self.assertEqual(sheet.status, ScoreSheetStatus.SUBMITTED)
        self.assertAlmostEqual(float(sheet.total_score), 80 / 100 * 30, places=2)

    def test_score_lock_then_immutable(self):
        sheet = self.service.create_score_sheet(
            application_id=str(self.app.id),
            event_id=str(self.event.id),
            evaluator_id=str(self.evaluator.id),
        )
        sheet = self.service.save_scores(
            score_sheet_id=str(sheet.id),
            scores={str(self.exam.id): 80},
            submit=True,
        )
        sheet = self.service.lock_score_sheet(score_sheet_id=str(sheet.id))
        self.assertEqual(sheet.status, ScoreSheetStatus.LOCKED)
        with self.assertRaises(ScoreAlreadyLockedError):
            self.service.save_scores(
                score_sheet_id=str(sheet.id),
                scores={str(self.exam.id): 100},
            )

    def test_reopen_privilege_flow(self):
        sheet = self.service.create_score_sheet(
            application_id=str(self.app.id),
            event_id=str(self.event.id),
            evaluator_id=str(self.evaluator.id),
        )
        sheet = self.service.save_scores(
            score_sheet_id=str(sheet.id), scores={str(self.exam.id): 80}, submit=True
        )
        self.service.lock_score_sheet(score_sheet_id=str(sheet.id))
        # 无 reason 拒绝
        with self.assertRaises(AssessmentServiceError):
            self.service.reopen_score_sheet(score_sheet_id=str(sheet.id), reason="")
        # 请求解锁
        sheet = self.service.reopen_score_sheet(
            score_sheet_id=str(sheet.id), reason="分数录入错误"
        )
        self.assertEqual(sheet.status, ScoreSheetStatus.REOPEN_REQUESTED)
        # 特权批准
        sheet = self.service.reopen_score_sheet(
            score_sheet_id=str(sheet.id), reason="", approve=True, approving_user="director"
        )
        self.assertEqual(sheet.status, ScoreSheetStatus.REOPEN_APPROVED)
        # 回 DRAFT
        sheet = self.service.reopen_score_sheet(score_sheet_id=str(sheet.id), reason="")
        self.assertEqual(sheet.status, ScoreSheetStatus.DRAFT)

    def test_conflict_declared(self):
        self.service.declare_conflict(
            assignment_id=str(self.evaluator.id),
            status="RECUSED",
            recusal_reason="与候选人有亲属关系",
        )
        self.evaluator.refresh_from_db()
        self.assertEqual(self.evaluator.conflict_status, "RECUSED")

    def test_blind_context_hides_name(self):
        sheet = self.service.create_score_sheet(
            application_id=str(self.app.id),
            event_id=str(self.event.id),
            evaluator_id=str(self.evaluator.id),
        )
        context = self.service.get_score_sheet_context(score_sheet_id=str(sheet.id), blind=True)
        self.assertEqual(context["candidate_name"], "（盲评）")
        self.assertTrue(context["candidate_no"])

    def test_freeze_result_snapshot(self):
        # 笔试 sheet（exam 组件）
        sheet1 = self.service.create_score_sheet(
            application_id=str(self.app.id),
            event_id=str(self.event.id),
            evaluator_id=str(self.evaluator.id),
        )
        sheet1 = self.service.save_scores(
            score_sheet_id=str(sheet1.id),
            scores={str(self.exam.id): 90},
            submit=True,
        )
        self.service.lock_score_sheet(score_sheet_id=str(sheet1.id))
        # 面试 sheet（interview 组件，独立场次）
        interview_event = self.service.create_event(
            component_id=str(self.interview.id),
            title="面试场次",
            event_date=date(2026, 5, 2),
        )
        interview_evaluator = self.service.assign_evaluator(
            event_id=str(interview_event.id), evaluator_staff_id=102, role="面试官"
        )
        sheet2 = self.service.create_score_sheet(
            application_id=str(self.app.id),
            event_id=str(interview_event.id),
            evaluator_id=str(interview_evaluator.id),
        )
        sheet2 = self.service.save_scores(
            score_sheet_id=str(sheet2.id),
            scores={str(self.interview.id): 90},
            submit=True,
        )
        self.service.lock_score_sheet(score_sheet_id=str(sheet2.id))

        snapshots = self.service.freeze_result_snapshot(position_id=str(self.position.id))
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].rank, 1)
        # 笔试 90/100×30 + 面试 90/100×70 = 27 + 63 = 90
        self.assertAlmostEqual(float(snapshots[0].final_score), 90.0, places=2)
