"""
hr_recruitment/tests/test_offer_s8.py

HR04-06 录用与人才引进（S8）测试：
- 拟录用创建校验（资格/评分锁定/额度上限/rank 唯一）；
- 决策 APPROVE；
- 公示 + 异议（RESOLVED_CHANGE 创建新决策版本）；
- Offer 状态机 + 接受幂等；
- HANDOFF_TO_HR05 前置条件 + 幂等（重复调用返回同一 handoff）。
"""

from datetime import date

from django.test import TestCase

from hr_recruitment.api.exceptions import HandoffPreconditionError
from hr_recruitment.constants import (
    ApplicationCanonicalStatus as S,
    OfferStatus,
)
from hr_recruitment.models import (
    HrCandidateScoreSheet,
    HrPublicNotice,
    HrRecruitmentHandoff,
    HrRecruitmentOffer,
)
from hr_recruitment.services.application_service import ApplicationService
from hr_recruitment.services.assessment_service import AssessmentService
from hr_recruitment.services.campaign_service import CampaignService
from hr_recruitment.services.candidate_service import CandidateService
from hr_recruitment.services.handoff_service import HandoffService
from hr_recruitment.services.notice_service import NoticeService
from hr_recruitment.services.offer_service import OfferService
from hr_recruitment.services.proposed_hire_service import ProposedHireService
from hr_recruitment.services.qualification_service import QualificationService

TENANT = 7001


class OfferFlowTests(TestCase):
    def setUp(self):
        self.camp_service = CampaignService(tenant_id=TENANT, actor="test")
        self.campaign = self.camp_service.create_campaign(
            code="2026-O-001", title="录用测试", campaign_type="SINGLE_POSITION"
        )
        self.position = self.camp_service.create_position(
            campaign_id=str(self.campaign.id),
            post_catalog_name="专任教师",
            planned_headcount=1,
            max_hires=1,
        )
        self.candidate_service = CandidateService(tenant_id=TENANT)
        self.candidate = self.candidate_service.create_candidate(
            legal_name="张三", primary_email="offer@test.local"
        )
        self.app_service = ApplicationService(tenant_id=TENANT, actor="test")
        draft = self.app_service.save_draft(
            candidate_id=str(self.candidate.id),
            recruitment_position_id=str(self.position.id),
            form_data={"degree": "博士"},
        )
        self.app = self.app_service.submit(application_id=str(draft.id))
        # 资格通过
        self.qual_service = QualificationService(tenant_id=TENANT, actor="reviewer")
        self.qual_service.start_review(application_id=str(self.app.id))
        self.qual_service.decision(
            application_id=str(self.app.id), decision="QUALIFIED", reason_text="满足"
        )
        # 评分锁定（selection scheme）
        self.assessment = AssessmentService(tenant_id=TENANT, actor="expert")
        self.scheme = self.assessment.create_scheme(position_id=str(self.position.id))
        self.exam = self.assessment.add_component(
            scheme_version_id=str(self.scheme.id),
            component_type="INTERVIEW",
            name="面试",
            weight=100,
        )
        self.assessment.lock_scheme(scheme_version_id=str(self.scheme.id))
        self.app.refresh_from_db()
        self.app.selection_scheme_version_id = self.scheme.id
        self.app.canonical_status = S.QUALIFIED
        self.app.save(update_fields=["selection_scheme_version_id", "canonical_status"])
        event = self.assessment.create_event(
            component_id=str(self.exam.id), title="面试", event_date=date(2026, 6, 1)
        )
        evaluator = self.assessment.assign_evaluator(
            event_id=str(event.id), evaluator_staff_id=201
        )
        sheet = self.assessment.create_score_sheet(
            application_id=str(self.app.id),
            event_id=str(event.id),
            evaluator_id=str(evaluator.id),
        )
        sheet = self.assessment.save_scores(
            score_sheet_id=str(sheet.id), scores={str(self.exam.id): 90}, submit=True
        )
        self.assessment.lock_score_sheet(score_sheet_id=str(sheet.id))

        self.proposed_service = ProposedHireService(tenant_id=TENANT, actor="hr")
        # 真实 HR02 预占（handoff 前置要求 HELD）
        from datetime import timedelta

        from django.utils import timezone
        from hr_structure.models import HrOrganization, HrPosition, HrPositionPool, HrPositionReservation

        org = HrOrganization.objects.create(
            tenant_id=TENANT, stable_code="ORG-OFFER", org_dimension="ADMIN"
        )
        hr_position = HrPosition.objects.create(
            tenant_id=TENANT,
            position_code="POS-OFFER-1",
            organization_id=org,
            post_catalog_version_id_id=None,
            max_incumbents=1,
            validity_from=date.today(),
            lifecycle_status=HrPosition.LifecycleStatus.ACTIVE,
        )
        reservation = HrPositionReservation.objects.create(
            tenant_id=TENANT,
            reservation_no="RESV-TEST-1",
            position_id=hr_position,
            source_domain="hr04",
            source_business_type="recruitment_position",
            source_business_id="offer-test",
            status=HrPositionReservation.Status.HELD,
            expires_at=timezone.now() + timedelta(days=7),
            idempotency_key="offer-test-resv",
        )
        self.proposed = self.proposed_service.create(
            application_id=str(self.app.id),
            rank=1,
            reservation_id=str(reservation.id),
            reservation_no=reservation.reservation_no,
        )
        self.proposed_service.decide(
            proposed_hire_id=str(self.proposed.id), decision="APPROVE"
        )

    def test_proposed_hire_created_approved(self):
        self.proposed.refresh_from_db()
        self.assertEqual(self.proposed.approval_status, "APPROVE")

    def test_notice_publish_and_close(self):
        notice_service = NoticeService(tenant_id=TENANT, actor="hr")
        notice = notice_service.publish_notice(
            campaign_id=str(self.campaign.id),
            notice_no="GS-2026-001",
            entries=[
                {
                    "proposed_hire_id": str(self.proposed.id),
                    "public_display_name": "张**",
                    "public_fields": {"岗位": "专任教师"},
                }
            ],
        )
        self.app.refresh_from_db()
        self.assertEqual(self.app.canonical_status, S.PUBLIC_NOTICE)
        notice = notice_service.close_notice(notice_id=str(notice.id), has_blocker=False)
        self.assertEqual(notice.status, "CLOSED_NO_BLOCKER")

    def test_offer_accept_idempotent(self):
        offer_service = OfferService(tenant_id=TENANT, actor="hr")
        offer = offer_service.create_offer(
            proposed_hire_id=str(self.proposed.id), offer_no="OFFER-001"
        )
        offer_service.transition(offer_id=str(offer.id), target="APPROVED")
        offer_service.transition(offer_id=str(offer.id), target="ISSUED")
        offer = offer_service.accept(offer_id=str(offer.id))
        self.assertEqual(offer.status, OfferStatus.ACCEPTED)
        self.app.refresh_from_db()
        self.assertEqual(self.app.canonical_status, S.OFFER_ACCEPTED)
        # 幂等重放
        offer_again = offer_service.accept(offer_id=str(offer.id))
        self.assertEqual(offer_again.status, OfferStatus.ACCEPTED)

    def test_handoff_preconditions_and_idempotent(self):
        """前置条件满足后才允许 handoff；重复调用返回同一 handoff。"""
        # 先走公示闭环
        notice_service = NoticeService(tenant_id=TENANT, actor="hr")
        notice = notice_service.publish_notice(
            campaign_id=str(self.campaign.id),
            notice_no="GS-2026-002",
            entries=[
                {
                    "proposed_hire_id": str(self.proposed.id),
                    "public_display_name": "张**",
                }
            ],
        )
        notice_service.close_notice(notice_id=str(notice.id), has_blocker=False)
        # Offer 接受
        offer_service = OfferService(tenant_id=TENANT, actor="hr")
        offer = offer_service.create_offer(
            proposed_hire_id=str(self.proposed.id), offer_no="OFFER-002"
        )
        offer_service.transition(offer_id=str(offer.id), target="APPROVED")
        offer_service.transition(offer_id=str(offer.id), target="ISSUED")
        offer_service.accept(offer_id=str(offer.id))

        handoff_service = HandoffService(tenant_id=TENANT, actor="hr")

        class FakeConsumer:
            def handle(self, *, proposed_hire_id, idempotency_key):
                return "hr05-case-1"

        handoff = handoff_service.handoff(
            proposed_hire_id=str(self.proposed.id),
            idempotency_key="handoff-key-1",
            hr05_consumer=FakeConsumer(),
        )
        self.assertEqual(handoff.status, "CREATED")
        self.assertEqual(handoff.hr05_case_id, "hr05-case-1")
        self.app.refresh_from_db()
        self.assertEqual(self.app.canonical_status, S.HANDOFF_TO_HR05)

        # 幂等重放：同一 proposed_hire 返回同一 handoff
        handoff2 = handoff_service.handoff(
            proposed_hire_id=str(self.proposed.id),
            idempotency_key="handoff-key-2",  # 不同 key 也应命中 proposed 唯一
            hr05_consumer=FakeConsumer(),
        )
        self.assertEqual(str(handoff2.id), str(handoff.id))
        self.assertEqual(HrRecruitmentHandoff.objects.filter(proposed_hire_id_id=self.proposed.id).count(), 1)

    def test_handoff_without_consumer_stays_failed(self):
        """消费者未交付：handoff FAILED，申请不推终态（防 HR05 从未收到但申请锁死）。"""
        notice_service = NoticeService(tenant_id=TENANT, actor="hr")
        notice = notice_service.publish_notice(
            campaign_id=str(self.campaign.id),
            notice_no="GS-2026-003",
            entries=[{"proposed_hire_id": str(self.proposed.id), "public_display_name": "张**"}],
        )
        notice_service.close_notice(notice_id=str(notice.id), has_blocker=False)
        offer_service = OfferService(tenant_id=TENANT, actor="hr")
        offer = offer_service.create_offer(
            proposed_hire_id=str(self.proposed.id), offer_no="OFFER-003"
        )
        offer_service.transition(offer_id=str(offer.id), target="APPROVED")
        offer_service.transition(offer_id=str(offer.id), target="ISSUED")
        offer_service.accept(offer_id=str(offer.id))

        handoff_service = HandoffService(tenant_id=TENANT, actor="hr")
        handoff = handoff_service.handoff(
            proposed_hire_id=str(self.proposed.id), idempotency_key="no-consumer-key"
        )
        self.assertEqual(handoff.status, "FAILED")
        self.app.refresh_from_db()
        # 不推终态：保持 OFFER_ACCEPTED
        self.assertEqual(self.app.canonical_status, S.OFFER_ACCEPTED)

    def test_handoff_blocked_without_preconditions(self):
        """未公示闭环/未 Offer 接受 → 拒绝 handoff。"""
        handoff_service = HandoffService(tenant_id=TENANT, actor="hr")
        with self.assertRaises(HandoffPreconditionError):
            handoff_service.handoff(
                proposed_hire_id=str(self.proposed.id),
                idempotency_key="handoff-blocked",
            )
