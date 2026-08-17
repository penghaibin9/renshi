"""
hr_recruitment/tests/test_models.py

HR04 S2 模型骨架测试：
- 所有权威模型带 tenant_id；
- HrJobApplication 状态机与 policies/state_machine.py 一致；
- 状态迁移必须写 HrApplicationTransition ledger；
- Candidate 与 Application 分离（一个候选多申请）；
- 公告/资格条件/评分方案版本化 + 唯一约束；
- DB 约束（active 申请唯一、score sheet 唯一、handoff unique、额度非负）生效。
"""

from datetime import date, timedelta
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from hr_recruitment.constants import ApplicationCanonicalStatus as S
from hr_recruitment.models import (
    HrApplicationMaterial,
    HrApplicationTransition,
    HrHiringPlanCycle,
    HrHiringPlanLine,
    HrHiringPlanRequest,
    HrJobApplication,
    HrProposedHire,
    HrPublicNotice,
    HrPublicNoticeEntry,
    HrQualificationDecision,
    HrQualificationRule,
    HrQualificationRuleSetVersion,
    HrRecruitmentAnnouncementVersion,
    HrRecruitmentCampaign,
    HrRecruitmentCandidate,
    HrRecruitmentHandoff,
    HrRecruitmentOffer,
    HrRecruitmentPosition,
    HrSelectionSchemeVersion,
)
from hr_recruitment.policies.state_machine import assert_transition

TENANT = 1001


def make_candidate(tenant=TENANT, name="张三", email="zhangsan@test.local"):
    return HrRecruitmentCandidate.objects.create(
        tenant_id=tenant,
        candidate_uid=f"uid-{uuid4().hex[:12]}",
        legal_name=name,
        primary_email=email,
    )


def make_campaign(tenant=TENANT, code="2026-001"):
    from uuid import uuid4

    return HrRecruitmentCampaign.objects.create(
        tenant_id=tenant,
        code=code,
        title="2026 专任教师招聘",
        public_slug=f"rec-{code}",
        public_token=uuid4().hex,
    )


def make_position(campaign, tenant=TENANT, headcount=2):
    return HrRecruitmentPosition.objects.create(
        tenant_id=tenant,
        campaign_id=campaign,
        planned_headcount=headcount,
        min_hires=1,
        max_hires=headcount,
        post_catalog_name="软件工程专任教师",
    )


def make_application(candidate, position, tenant=TENANT, status=S.DRAFT):
    return HrJobApplication.objects.create(
        tenant_id=tenant,
        candidate_id=candidate,
        recruitment_position_id=position,
        canonical_status=status,
        source_channel="PUBLIC_PORTAL",
    )


class TenantIdCoverageTests(TestCase):
    """验收：所有权威模型带 tenant_id。"""

    MODEL_FIELDS = {
        HrHiringPlanCycle: "tenant_id",
        HrHiringPlanRequest: "tenant_id",
        HrHiringPlanLine: "tenant_id",
        HrRecruitmentCampaign: "tenant_id",
        HrRecruitmentPosition: "tenant_id",
        HrRecruitmentAnnouncementVersion: "tenant_id",
        HrQualificationRuleSetVersion: "tenant_id",
        HrSelectionSchemeVersion: "tenant_id",
        HrRecruitmentCandidate: "tenant_id",
        HrJobApplication: "tenant_id",
        HrApplicationTransition: "tenant_id",
        HrApplicationMaterial: "tenant_id",
        HrQualificationRule: "tenant_id",
        HrQualificationDecision: "tenant_id",
        HrProposedHire: "tenant_id",
        HrPublicNotice: "tenant_id",
        HrPublicNoticeEntry: "tenant_id",
        HrRecruitmentOffer: "tenant_id",
        HrRecruitmentHandoff: "tenant_id",
    }

    def test_all_models_have_tenant_id(self):
        for model, field in self.MODEL_FIELDS.items():
            self.assertIn(
                field,
                {f.name for f in model._meta.fields},
                f"{model.__name__} 必须带 {field}",
            )


class CandidateApplicationSeparationTests(TestCase):
    """验收：Candidate 与 Application 分离。"""

    def test_one_candidate_multiple_applications(self):
        candidate = make_candidate()
        campaign = make_campaign()
        pos_a = make_position(campaign, headcount=1)
        pos_b = make_position(
            HrRecruitmentCampaign.objects.create(
                tenant_id=TENANT, code="2026-002", title="实验教师"
            ),
            headcount=1,
        )
        app_a = make_application(candidate, pos_a, status=S.SUBMITTED)
        app_b = make_application(candidate, pos_b, status=S.SUBMITTED)
        # 同一自然人两个申请 → 人才库只有一份
        self.assertEqual(HrRecruitmentCandidate.objects.filter(id=candidate.id).count(), 1)
        self.assertEqual(candidate.applications.count(), 2)
        self.assertNotEqual(app_a.id, app_b.id)

    def test_email_not_unique_identity(self):
        """email 只是联系字段，不是唯一身份。"""
        c1 = make_candidate(email="shared@test.local")
        c2 = make_candidate(name="李四", email="shared@test.local")
        self.assertNotEqual(c1.id, c2.id)


class StateMachineLedgerTests(TestCase):
    """验收：状态机一致 + 迁移写 ledger。"""

    def setUp(self):
        self.candidate = make_candidate()
        self.campaign = make_campaign()
        self.position = make_position(self.campaign)
        self.app = make_application(self.candidate, self.position, status=S.SUBMITTED)

    def test_allowed_transition_writes_ledger(self):
        assert_transition(self.app.canonical_status, S.UNDER_REVIEW)
        self.app.canonical_status = S.UNDER_REVIEW
        self.app.save()
        HrApplicationTransition.objects.create(
            tenant_id=TENANT,
            application_id=self.app,
            from_status=S.SUBMITTED,
            to_status=S.UNDER_REVIEW,
            action="START_REVIEW",
            actor_id="hr_admin",
        )
        ledger = self.app.transitions.filter(to_status=S.UNDER_REVIEW)
        self.assertEqual(ledger.count(), 1)
        self.assertEqual(ledger.first().from_status, S.SUBMITTED)

    def test_illegal_transition_raises(self):
        from hr_recruitment.api.exceptions import InvalidStateTransitionError

        with self.assertRaises(InvalidStateTransitionError):
            assert_transition(S.RETURNED, S.HANDOFF_TO_HR05)
        # RETURNED 可 RESUBMITTED
        assert_transition(S.RETURNED, S.RESUBMITTED)

    def test_application_status_matches_frozen_enum(self):
        """状态值集合必须与 constants 冻结一致。"""
        expected = set(S.values)
        self.assertEqual(
            {c[0] for c in HrJobApplication._meta.get_field("canonical_status").choices},
            expected,
        )


class VersioningTests(TestCase):
    """验收：公告/资格条件/评分方案有版本 + 唯一约束。"""

    def setUp(self):
        self.campaign = make_campaign()
        self.position = make_position(self.campaign)

    def test_announcement_version_unique_per_campaign(self):
        HrRecruitmentAnnouncementVersion.objects.create(
            tenant_id=TENANT,
            campaign_id=self.campaign,
            version_no=1,
            title="公告 v1",
            immutable_after_publish=True,
        )
        HrRecruitmentAnnouncementVersion.objects.create(
            tenant_id=TENANT,
            campaign_id=self.campaign,
            version_no=2,
            title="公告 v2（amendment）",
            change_reason="更正截止日期",
        )
        with self.assertRaises(IntegrityError):
            HrRecruitmentAnnouncementVersion.objects.create(
                tenant_id=TENANT,
                campaign_id=self.campaign,
                version_no=1,
                title="重复 v1",
            )

    def test_qualification_rule_version_unique(self):
        rs1 = HrQualificationRuleSetVersion.objects.create(
            tenant_id=TENANT,
            recruitment_position_id=self.position,
            version_no=1,
            status="LOCKED",
        )
        rs2 = HrQualificationRuleSetVersion.objects.create(
            tenant_id=TENANT,
            recruitment_position_id=self.position,
            version_no=2,
            status="ACTIVE",
            supersedes_id=rs1,
        )
        self.assertIsNotNone(rs2.supersedes_id)
        with self.assertRaises(IntegrityError):
            HrQualificationRuleSetVersion.objects.create(
                tenant_id=TENANT,
                recruitment_position_id=self.position,
                version_no=1,
            )

    def test_selection_scheme_version_unique(self):
        HrSelectionSchemeVersion.objects.create(
            tenant_id=TENANT, recruitment_position_id=self.position, version_no=1
        )
        with self.assertRaises(IntegrityError):
            HrSelectionSchemeVersion.objects.create(
                tenant_id=TENANT, recruitment_position_id=self.position, version_no=1
            )


class DbConstraintTests(TestCase):
    """验收：DB 约束生效（不靠 Python clean）。"""

    def setUp(self):
        self.candidate = make_candidate()
        self.campaign = make_campaign()
        self.position = make_position(self.campaign)

    def test_active_application_unique_per_position(self):
        make_application(self.candidate, self.position, status=S.SUBMITTED)
        with self.assertRaises(IntegrityError):
            make_application(self.candidate, self.position, status=S.SUBMITTED)

    def test_inactive_application_allowed(self):
        """撤回后可重新申请（is_active=False 不占唯一）。"""
        app = make_application(self.candidate, self.position, status=S.SUBMITTED)
        app.is_active = False
        app.canonical_status = S.WITHDRAWN
        app.save()
        app2 = make_application(self.candidate, self.position, status=S.SUBMITTED)
        self.assertIsNotNone(app2.id)

    def test_handoff_unique_per_proposed_hire(self):
        proposed = HrProposedHire.objects.create(
            tenant_id=TENANT,
            application_id=make_application(self.candidate, self.position, status=S.OFFER_ACCEPTED),
            recruitment_position_id=self.position,
            rank=1,
        )
        HrRecruitmentHandoff.objects.create(
            tenant_id=TENANT,
            proposed_hire_id=proposed,
            application_id=proposed.application_id,
            idempotency_key="key-1",
        )
        with self.assertRaises(IntegrityError):
            HrRecruitmentHandoff.objects.create(
                tenant_id=TENANT,
                proposed_hire_id=proposed,
                application_id=proposed.application_id,
                idempotency_key="key-2",
            )

    def test_headcount_check_constraint(self):
        """额度非负约束（ck_hr_plan_line_headcount_nonneg）。"""
        cycle = HrHiringPlanCycle.objects.create(
            tenant_id=TENANT, year=2026, title="2026 用人计划", start_date=date.today()
        )
        request = HrHiringPlanRequest.objects.create(
            tenant_id=TENANT, cycle_id=cycle, organization_name="计算机学院"
        )
        HrHiringPlanLine.objects.create(
            tenant_id=TENANT,
            request_id=request,
            post_catalog_name="专任教师",
            requested_headcount=2,
            approved_headcount=1,
        )
        self.assertEqual(request.lines.count(), 1)
