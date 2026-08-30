"""S5 · 聘用审批契约测试。

覆盖（总册 §32-43）：
- 审批状态机：DRAFT→SUBMITTED→学院→HR→学校（学校批准执行 §35 审批前检查）→APPROVED→WAITING_AGREEMENT；
- 审批前检查 BLOCKER（身份未核验/缺教师资格）阻断学校批准；
- HR07 Agreement gate：Provider 占位 UNAVAILABLE → REQUIRED_BEFORE_ACTIVATION 不能激活（§42/§93）；
- Activation（§43）：创建 Engagement + Assignment + LifecycleEvent + case ACTIVATED；
- 返回/拒绝/撤销等异常分支。
"""

from datetime import date

from django.test import TestCase
from django.utils import timezone

from hr_external.constants import (
    AgreementProviderStatus,
    EthicsReviewStatus,
    ExternalEngagementStatus,
    ExternalHiringStatus,
)
from hr_external.models import (
    HrExternalEngagement,
    HrExternalEngagementAssignment,
    HrExternalEthicsReview,
    HrExternalHiringCase,
    HrExternalLifecycleEvent,
    HrExternalTeacherProfile,
)
from hr_external.services.category_service import CategoryService
from hr_external.services.hiring_service import (
    AgreementNotReady,
    ComplianceBlocked,
    HiringService,
    InvalidHiringState,
)
from hr_external.services.profile_service import ProfileService


class HiringFlowTests(TestCase):
    def setUp(self):
        from hr_staff.models import HrPerson

        self.tenant = 101
        CategoryService().ensure_default_categories(self.tenant)
        self.person = HrPerson.objects.create(tenant_id=self.tenant, legal_name="钱教授")
        # 身份标记为已核验以通过审批前检查
        self.profile = ProfileService().create_profile(
            tenant_id=self.tenant,
            person_id=self.person.id,
            primary_category_code="INDUSTRY_PROFESSOR",
            source_organization_name="XX集团",
        )
        self.profile.identity_verification_status = "VERIFIED"
        self.profile.ethics_status = "PASS"
        self.profile.save()
        self.category = self.profile.primary_category

        self.case = HrExternalHiringCase.objects.create(
            tenant_id=self.tenant,
            case_no="C20260001",
            request_org_id=1,
            requester_id=1,
            category_id=self.category,
            purpose="产业教授授课与专业建设",
            proposed_person_id=self.person,
            requested_start=date(2026, 9, 1),
            requested_end=date(2027, 8, 31),
            planned_assignments_json=[
                {"assignmentType": "TEACHING", "roleTitle": "产业教授", "organizationId": 1}
            ],
            estimated_workload=None,
            status=ExternalHiringStatus.DRAFT,
        )
        # INDUSTRY_PROFESSOR 要求伦理审查（§36）：创建 PASS 的 ethics review，
        # 否则审批前检查 ETHICS_REVIEW_FAILED 会误阻断（compliance 查 case 级审查记录）
        HrExternalEthicsReview.objects.create(
            tenant_id=self.tenant,
            person_id=self.person,
            case_id=self.case,
            review_type="HIRING",
            status=EthicsReviewStatus.PASS,
            reviewer=1,
            reviewed_at=timezone.now(),
        )
        self.service = HiringService()

    def test_full_approval_flow(self):
        self.case = self.service.submit(self.case, tenant_id=self.tenant)
        self.assertEqual(self.case.status, ExternalHiringStatus.SUBMITTED)
        self.case = self.service.college_approve(self.case, tenant_id=self.tenant)
        self.assertEqual(self.case.status, ExternalHiringStatus.UNDER_HR_REVIEW)
        self.case = self.service.hr_approve(self.case, tenant_id=self.tenant)
        self.assertEqual(self.case.status, ExternalHiringStatus.UNDER_SCHOOL_APPROVAL)
        self.case = self.service.school_approve(self.case, tenant_id=self.tenant)
        self.assertEqual(self.case.status, ExternalHiringStatus.APPROVED)
        self.case = self.service.wait_agreement(self.case, tenant_id=self.tenant)
        self.assertEqual(self.case.status, ExternalHiringStatus.WAITING_AGREEMENT)

    def test_illegal_transition_blocked(self):
        with self.assertRaises(InvalidHiringState):
            self.service.college_approve(
                self.case, tenant_id=self.tenant
            )  # DRAFT 不能直接学院审批

    def test_return_flow(self):
        self.case = self.service.submit(self.case, tenant_id=self.tenant)
        self.case = self.service.college_approve(self.case, tenant_id=self.tenant)
        self.case = self.service.return_to_draft(
            self.case, tenant_id=self.tenant
        )
        self.assertEqual(self.case.status, ExternalHiringStatus.RETURNED)

    def test_compliance_blocker_blocks_school_approval(self):
        # 撤回身份核验 → 学校批准必须被 BLOCKER 阻断（§35）
        self.profile.identity_verification_status = "UNVERIFIED"
        self.profile.save()
        self.case = self.service.submit(self.case, tenant_id=self.tenant)
        self.case = self.service.college_approve(self.case, tenant_id=self.tenant)
        self.case = self.service.hr_approve(self.case, tenant_id=self.tenant)
        with self.assertRaises(ComplianceBlocked):
            self.service.school_approve(self.case, tenant_id=self.tenant)
        self.assertEqual(self.case.status, ExternalHiringStatus.UNDER_SCHOOL_APPROVAL)

    def test_activation_requires_ready_to_activate(self):
        with self.assertRaises(InvalidHiringState):
            self.service.activate(self.case, tenant_id=self.tenant)

    def test_activation_creates_engagement_assignment_event(self):
        # 走完整审批到 WAITING_AGREEMENT → 手动置 READY_TO_ACTIVATE（协议已签场景）
        self.case = self.service.submit(self.case, tenant_id=self.tenant)
        self.case = self.service.college_approve(self.case, tenant_id=self.tenant)
        self.case = self.service.hr_approve(self.case, tenant_id=self.tenant)
        self.case = self.service.school_approve(self.case, tenant_id=self.tenant)
        self.case = self.service.wait_agreement(self.case, tenant_id=self.tenant)
        self.case.status = ExternalHiringStatus.READY_TO_ACTIVATE
        self.case.save(update_fields=["status", "updated_at"])
        # 类别 REQUIRED_BEFORE_ACTIVATION 且 Provider 占位 UNAVAILABLE → 激活被协议闸门阻断
        with self.assertRaises(AgreementNotReady):
            self.service.activate(self.case, tenant_id=self.tenant)

        # 模拟协议已签（直接改 agreement gate 不适用时，把类别改为 NOT_REQUIRED 场景）
        self.category.agreement_requirement = "NOT_REQUIRED"
        self.category.save()
        eng = self.service.activate(self.case, tenant_id=self.tenant)
        # activate 为并发安全会 select_for_update 重新读取 case；刷新调用方实例再断言终态。
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, ExternalHiringStatus.ACTIVATED)
        self.assertEqual(eng.status, ExternalEngagementStatus.ACTIVE)
        self.assertTrue(HrExternalEngagementAssignment.objects.filter(engagement_id=eng).exists())
        self.assertTrue(
            HrExternalLifecycleEvent.objects.filter(
                event_type="ExternalEngagementActivated", engagement_id=eng
            ).exists()
        )

    def test_agreement_gate_placeholder_unavailable(self):
        # # [总控占位] HR07 未交付 → gate 恒为 False（不 silent fallback）
        self.assertFalse(
            self.service.agreement_gate(tenant_id=self.tenant, agreement_type_code="EXTERNAL_EXPERT")
        )
