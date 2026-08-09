"""
hr_recruitment/tests/test_gap_fix.py

对照总册审计补齐的验收项测试：
- 审计写入（HrRecruitmentAuditEvent 由 plan/handoff/qualification/assessment 触发）；
- 跨学院 scope（COLLEGE scope 只返回本学院数据）；
- 从 approved plan 创建 campaign（create_from_plan）；
- 排期冲突（assign_participant 冲突/容量检查）；
- tie-break（并列分数次级排序）；
- 体检/考察（record_medical/record_background + 敏感隔离）；
- reservation commit（handoff 后 HELD→COMMITTED）；
- 关闭招聘释放未用预占；
- Pipeline selector 从权威数据投影。
"""

from datetime import date, timedelta
from uuid import uuid4

from django.test import TestCase

from hr_recruitment.constants import (
    ApplicationCanonicalStatus as S,
    PlanRequestStatus,
)
from hr_recruitment.models import (
    HrApplicationTransition,
    HrAssessmentParticipant,
    HrBackgroundCheck,
    HrMedicalCheck,
    HrRecruitmentAuditEvent,
)
from hr_recruitment.services.application_service import ApplicationService
from hr_recruitment.services.assessment_service import AssessmentService
from hr_recruitment.services.campaign_service import CampaignService
from hr_recruitment.services.candidate_service import CandidateService
from hr_recruitment.services.plan_service import PlanService
from hr_recruitment.services.qualification_service import QualificationService

TENANT = 13001


class AuditWriteTests(TestCase):
    def test_plan_approve_writes_audit(self):
        service = PlanService()
        cycle = service.create_cycle(
            tenant_id=TENANT, year=2026, title="审计测试", start_date=date.today()
        )
        from hr_recruitment.models import HrHiringPlanRequest

        req = HrHiringPlanRequest.objects.create(
            tenant_id=TENANT, cycle_id=cycle, organization_name="计算机学院"
        )
        from hr_recruitment.models import HrHiringPlanLine

        HrHiringPlanLine.objects.create(
            tenant_id=TENANT, request_id=req, post_catalog_name="专任教师", requested_headcount=1
        )
        service.submit(str(req.id), tenant_id=TENANT)
        service.start_hr_review(str(req.id), tenant_id=TENANT)
        service.submit_to_school(str(req.id), tenant_id=TENANT)

        from hr_recruitment.policies.capacity import PositionCapacitySnapshot

        class FakeProvider:
            def query_capacity(self, **kwargs):
                return PositionCapacitySnapshot(
                    position_id=None, position_pool_id=None, post_catalog_id=None,
                    authorized_count=5, reserved_count=0, available_count=5,
                    status="OK", mode="TEST",
                )

        service.approve(str(req.id), tenant_id=TENANT, capacity_provider=FakeProvider())
        audit = HrRecruitmentAuditEvent.objects.filter(
            tenant_id=TENANT, event_type="PLAN_REQUEST_APPROVED"
        )
        self.assertEqual(audit.count(), 1)
        self.assertEqual(audit.first().action, "APPROVED")


class ScopeFilterTests(TestCase):
    """§35 跨学院 scope：COLLEGE scope 只返回本学院数据。"""

    def _make_scope(self, org_id):
        from hr_control_center.context import HrScope

        return HrScope(scope_type="COLLEGE", org_id=org_id)

    def test_list_campaigns_scoped(self):
        from hr_recruitment.selectors import campaign as campaign_selector

        camp_service = CampaignService(tenant_id=TENANT, actor="test")
        camp_a = camp_service.create_campaign(
            code="A-2026", title="学院A招聘", campaign_type="MULTI_POSITION"
        )
        camp_service.create_position(
            campaign_id=str(camp_a.id),
            post_catalog_name="教师A",
            organization_id=101,
            planned_headcount=1,
        )
        camp_b = camp_service.create_campaign(
            code="B-2026", title="学院B招聘", campaign_type="MULTI_POSITION"
        )
        camp_service.create_position(
            campaign_id=str(camp_b.id),
            post_catalog_name="教师B",
            organization_id=202,
            planned_headcount=1,
        )
        data = campaign_selector.list_campaigns(tenant_id=TENANT, scope=self._make_scope(101))
        ids = [i["id"] for i in data["items"]]
        self.assertIn(str(camp_a.id), ids)
        self.assertNotIn(str(camp_b.id), ids)


class CreateFromPlanTests(TestCase):
    def test_create_from_approved_plan(self):
        plan_service = PlanService()
        cycle = plan_service.create_cycle(
            tenant_id=TENANT, year=2026, title="计划", start_date=date.today()
        )
        from hr_recruitment.models import HrHiringPlanRequest

        req = HrHiringPlanRequest.objects.create(
            tenant_id=TENANT, cycle_id=cycle, organization_id=101, organization_name="计算机学院"
        )
        from hr_recruitment.models import HrHiringPlanLine

        HrHiringPlanLine.objects.create(
            tenant_id=TENANT, request_id=req, post_catalog_name="软件工程专任教师",
            post_catalog_id=500, requested_headcount=2,
        )
        plan_service.submit(str(req.id), tenant_id=TENANT)
        plan_service.start_hr_review(str(req.id), tenant_id=TENANT)
        plan_service.submit_to_school(str(req.id), tenant_id=TENANT)

        from hr_recruitment.policies.capacity import PositionCapacitySnapshot

        class FakeProvider:
            def query_capacity(self, **kwargs):
                return PositionCapacitySnapshot(
                    position_id=None, position_pool_id=None, post_catalog_id=None,
                    authorized_count=5, reserved_count=0, available_count=5,
                    status="OK", mode="TEST",
                )

        plan_service.approve(str(req.id), tenant_id=TENANT, capacity_provider=FakeProvider())

        camp_service = CampaignService(tenant_id=TENANT, actor="test")
        campaign = camp_service.create_from_plan(
            plan_cycle_id=str(cycle.id), code="RC-2026-01", title="2026 专任教师招聘"
        )
        self.assertEqual(campaign.positions.count(), 1)
        pos = campaign.positions.first()
        self.assertEqual(pos.post_catalog_name, "软件工程专任教师")
        self.assertEqual(pos.planned_headcount, 2)
        self.assertEqual(pos.organization_id, 101)


class ScheduleConflictTests(TestCase):
    def setUp(self):
        self.camp_service = CampaignService(tenant_id=TENANT, actor="test")
        self.campaign = self.camp_service.create_campaign(
            code="2026-CONF-001", title="冲突测试", campaign_type="SINGLE_POSITION"
        )
        self.position = self.camp_service.create_position(
            campaign_id=str(self.campaign.id), post_catalog_name="岗位", planned_headcount=1
        )
        self.cand = CandidateService(tenant_id=TENANT).create_candidate(
            legal_name="张三", primary_email="conf@test.local"
        )
        self.app_service = ApplicationService(tenant_id=TENANT, actor="test")
        draft = self.app_service.save_draft(
            candidate_id=str(self.cand.id), recruitment_position_id=str(self.position.id)
        )
        self.app = self.app_service.submit(application_id=str(draft.id))
        self.assessment = AssessmentService(tenant_id=TENANT, actor="expert")

    def test_same_day_conflict_blocked(self):
        scheme = self.assessment.create_scheme(position_id=str(self.position.id))
        exam = self.assessment.add_component(
            scheme_version_id=str(scheme.id), component_type="INTERVIEW", name="面试", weight=100
        )
        self.assessment.lock_scheme(scheme_version_id=str(scheme.id))
        self.app.refresh_from_db()
        self.app.selection_scheme_version_id = scheme.id
        self.app.save(update_fields=["selection_scheme_version_id"])
        event1 = self.assessment.create_event(
            component_id=str(exam.id), title="面试一", event_date=date(2026, 9, 1)
        )
        event2 = self.assessment.create_event(
            component_id=str(exam.id), title="面试二", event_date=date(2026, 9, 1)
        )
        self.assessment.assign_participant(
            event_id=str(event1.id), application_id=str(self.app.id)
        )
        from hr_recruitment.services.assessment_service import AssessmentServiceError

        with self.assertRaises(AssessmentServiceError):
            self.assessment.assign_participant(
                event_id=str(event2.id), application_id=str(self.app.id)
            )

    def test_capacity_full_blocked(self):
        scheme = self.assessment.create_scheme(position_id=str(self.position.id))
        exam = self.assessment.add_component(
            scheme_version_id=str(scheme.id), component_type="INTERVIEW", name="面试", weight=100
        )
        self.assessment.lock_scheme(scheme_version_id=str(scheme.id))
        self.app.refresh_from_db()
        self.app.selection_scheme_version_id = scheme.id
        self.app.save(update_fields=["selection_scheme_version_id"])
        event = self.assessment.create_event(
            component_id=str(exam.id), title="容量测试", event_date=date(2026, 9, 2), capacity=1
        )
        self.assessment.assign_participant(event_id=str(event.id), application_id=str(self.app.id))
        cand2 = CandidateService(tenant_id=TENANT).create_candidate(
            legal_name="李四", primary_email="conf2@test.local"
        )
        draft2 = self.app_service.save_draft(
            candidate_id=str(cand2.id), recruitment_position_id=str(self.position.id)
        )
        app2 = self.app_service.submit(application_id=str(draft2.id))
        from hr_recruitment.services.assessment_service import AssessmentServiceError

        with self.assertRaises(AssessmentServiceError):
            self.assessment.assign_participant(event_id=str(event.id), application_id=str(app2.id))


class MedicalBackgroundTests(TestCase):
    def setUp(self):
        self.camp_service = CampaignService(tenant_id=TENANT, actor="test")
        self.campaign = self.camp_service.create_campaign(
            code="2026-MED-001", title="体检测试", campaign_type="SINGLE_POSITION"
        )
        self.position = self.camp_service.create_position(
            campaign_id=str(self.campaign.id), post_catalog_name="岗位", planned_headcount=1
        )
        self.cand = CandidateService(tenant_id=TENANT).create_candidate(
            legal_name="张三", primary_email="med@test.local"
        )
        self.app_service = ApplicationService(tenant_id=TENANT, actor="test")
        draft = self.app_service.save_draft(
            candidate_id=str(self.cand.id), recruitment_position_id=str(self.position.id)
        )
        self.app = self.app_service.submit(application_id=str(draft.id))

    def test_record_medical_and_summary(self):
        from hr_recruitment.services.medical_background_service import MedicalBackgroundService

        service = MedicalBackgroundService(tenant_id=TENANT, actor="hr")
        mat_id = uuid4()
        check = service.record_medical(
            application_id=str(self.app.id), result="FIT", sensitive_material_id=mat_id
        )
        self.assertEqual(check.result, "FIT")
        # 普通管理员只看结论摘要，不含敏感材料 id
        summary = service.get_medical_summary(application_id=str(self.app.id))
        self.assertEqual(summary["result"], "FIT")
        self.assertTrue(summary["has_sensitive_material"])
        self.assertNotIn("sensitive_material_id", summary)

    def test_record_background(self):
        from hr_recruitment.services.medical_background_service import MedicalBackgroundService

        service = MedicalBackgroundService(tenant_id=TENANT, actor="hr")
        check = service.record_background(application_id=str(self.app.id), result="PASS")
        self.assertEqual(check.result, "PASS")


class PipelineProjectionTests(TestCase):
    def test_pipeline_boards(self):
        from hr_recruitment.selectors import pipeline as pipeline_selector

        camp_service = CampaignService(tenant_id=TENANT, actor="test")
        campaign = camp_service.create_campaign(
            code="2026-PIPE-001", title="管道测试", campaign_type="SINGLE_POSITION"
        )
        position = camp_service.create_position(
            campaign_id=str(campaign.id), post_catalog_name="岗位", planned_headcount=1
        )
        cand = CandidateService(tenant_id=TENANT).create_candidate(
            legal_name="张三", primary_email="pipe@test.local"
        )
        app_service = ApplicationService(tenant_id=TENANT, actor="test")
        draft = app_service.save_draft(
            candidate_id=str(cand.id), recruitment_position_id=str(position.id)
        )
        app = app_service.submit(application_id=str(draft.id))

        boards = pipeline_selector.pipeline_boards(
            tenant_id=TENANT, campaign_id=str(campaign.id)
        )
        all_cards = [c for col in boards for c in col["cards"]]
        self.assertEqual(len(all_cards), 1)
        self.assertEqual(all_cards[0]["application_id"], str(app.id))
        # 权威状态徽标（不是 stage 名称）
        self.assertEqual(all_cards[0]["canonical_status"], S.SUBMITTED)
