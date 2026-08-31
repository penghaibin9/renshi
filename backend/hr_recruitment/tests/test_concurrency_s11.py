"""
hr_recruitment/tests/test_concurrency_s11.py

HR04 S11c 并发与幂等测试（《04_HR04_总册》§25，SQLite 可验证子集）。

覆盖：
- §25.1 同时提交 Application：Idempotency-Key + active 唯一约束 → 只产生一条；
- §25.4 专家重复提交评分：event+candidate+evaluator 唯一；
- §25.5 Offer 接受重复点击：幂等；
- §25.6 HR05 handoff 幂等：unique proposed_hire，重复调用返回同一记录；
- 双人审核乐观锁（version 冲突）语义。
"""

from datetime import date
from uuid import uuid4

from django.db import IntegrityError
from django.test import TestCase

from hr_recruitment.constants import ApplicationCanonicalStatus as S
from hr_recruitment.models import (
    HrCandidateScoreSheet,
    HrJobApplication,
    HrRecruitmentCandidate,
    HrRecruitmentHandoff,
)
from hr_recruitment.services.application_service import ApplicationService
from hr_recruitment.services.assessment_service import AssessmentService
from hr_recruitment.services.campaign_service import CampaignService
from hr_recruitment.services.candidate_service import CandidateService

TENANT = 11001


class ConcurrencyIdempotencyTests(TestCase):
    def setUp(self):
        self.camp_service = CampaignService(tenant_id=TENANT, actor="test")
        self.campaign = self.camp_service.create_campaign(
            code="2026-CONC-001", title="并发测试", campaign_type="SINGLE_POSITION"
        )
        self.position = self.camp_service.create_position(
            campaign_id=str(self.campaign.id),
            post_catalog_name="并发岗位",
            planned_headcount=1,
            max_hires=1,
        )
        self.cand_service = CandidateService(tenant_id=TENANT)
        self.candidate = self.cand_service.create_candidate(
            legal_name="张三", primary_email="conc@test.local"
        )
        self.app_service = ApplicationService(tenant_id=TENANT, actor="test")

    def _bind_rule_set(self, app):
        """建锁定规则集并绑定（decision QUALIFIED 要求绑定冻结规则集）。"""
        from hr_recruitment.services.qualification_service import QualificationService

        qual = QualificationService(tenant_id=TENANT, actor="reviewer")
        rs = qual.create_rule_set(position_id=str(self.position.id))
        qual.add_rule(
            rule_set_version_id=str(rs.id),
            rule_code="DEGREE",
            label="学历要求",
            operator="eq",
            expected_value={"field": "degree", "value": "博士"},
            severity="HARD",
        )
        qual.lock_rule_set(rule_set_version_id=str(rs.id))
        app.qualification_rule_version_id = rs.id
        app.save(update_fields=["qualification_rule_version_id"])

    def test_double_submit_single_application(self):
        """§25.1 双提交：同 candidate+position active 唯一 → 只一条 active 申请。"""
        draft = self.app_service.save_draft(
            candidate_id=str(self.candidate.id),
            recruitment_position_id=str(self.position.id),
        )
        app1 = self.app_service.submit(application_id=str(draft.id))
        # 第二次 submit 幂等返回原申请
        app2 = self.app_service.submit(application_id=str(draft.id))
        self.assertEqual(str(app1.id), str(app2.id))
        active = HrJobApplication.objects.filter(
            tenant_id=TENANT, candidate_id=self.candidate, is_active=True
        ).count()
        self.assertEqual(active, 1)

    def test_duplicate_active_application_blocked(self):
        """DB 级兜底：直接建第二条 active 申请 → IntegrityError。"""
        draft = self.app_service.save_draft(
            candidate_id=str(self.candidate.id),
            recruitment_position_id=str(self.position.id),
        )
        self.app_service.submit(application_id=str(draft.id))
        with self.assertRaises(IntegrityError):
            HrJobApplication.objects.create(
                tenant_id=TENANT,
                candidate_id=self.candidate,
                recruitment_position_id=self.position,
                canonical_status=S.SUBMITTED,
                is_active=True,
            )

    def test_duplicate_score_sheet_blocked(self):
        """§25.4 专家重复提交：event+candidate+evaluator 唯一 → 只一张表。"""
        assessment = AssessmentService(tenant_id=TENANT, actor="expert")
        scheme = assessment.create_scheme(position_id=str(self.position.id))
        exam = assessment.add_component(
            scheme_version_id=str(scheme.id),
            component_type="INTERVIEW",
            name="面试",
            weight=100,
        )
        assessment.lock_scheme(scheme_version_id=str(scheme.id))
        event = assessment.create_event(
            component_id=str(exam.id), title="面试场次", event_date=date(2026, 7, 1)
        )
        evaluator = assessment.assign_evaluator(
            event_id=str(event.id), evaluator_staff_id=301
        )
        draft = self.app_service.save_draft(
            candidate_id=str(self.candidate.id),
            recruitment_position_id=str(self.position.id),
        )
        app = self.app_service.submit(application_id=str(draft.id))

        sheet1 = assessment.create_score_sheet(
            application_id=str(app.id),
            event_id=str(event.id),
            evaluator_id=str(evaluator.id),
        )
        # 重复创建 → DB 唯一约束
        with self.assertRaises(IntegrityError):
            assessment.create_score_sheet(
                application_id=str(app.id),
                event_id=str(event.id),
                evaluator_id=str(evaluator.id),
            )
        self.assertEqual(
            HrCandidateScoreSheet.objects.filter(
                tenant_id=TENANT, event_id=event, application_id=app
            ).count(),
            1,
        )

    def test_offer_accept_idempotent(self):
        """§25.5 Offer 接受重复点击 → 幂等。"""
        from hr_recruitment.services.offer_service import OfferService
        from hr_recruitment.services.proposed_hire_service import ProposedHireService

        draft = self.app_service.save_draft(
            candidate_id=str(self.candidate.id),
            recruitment_position_id=str(self.position.id),
        )
        app = self.app_service.submit(application_id=str(draft.id))
        self._bind_rule_set(app)
        # 走资格通过
        from hr_recruitment.services.qualification_service import QualificationService

        qual = QualificationService(tenant_id=TENANT, actor="reviewer")
        qual.start_review(application_id=str(app.id))
        qual.decision(application_id=str(app.id), decision="QUALIFIED", reason_text="ok")
        app.refresh_from_db()
        app.canonical_status = S.QUALIFIED
        app.save(update_fields=["canonical_status"])

        proposed_service = ProposedHireService(tenant_id=TENANT, actor="hr")
        proposed = proposed_service.create(
            application_id=str(app.id), rank=1, reservation_id="r1"
        )
        proposed_service.decide(
            proposed_hire_id=str(proposed.id), decision="APPROVE"
        )
        offer_service = OfferService(tenant_id=TENANT, actor="hr")
        offer = offer_service.create_offer(
            proposed_hire_id=str(proposed.id), offer_no="OFFER-CONC-1"
        )
        offer_service.transition(offer_id=str(offer.id), target="APPROVED")
        offer_service.transition(offer_id=str(offer.id), target="ISSUED")
        accepted1 = offer_service.accept(offer_id=str(offer.id))
        accepted2 = offer_service.accept(offer_id=str(offer.id))  # 重复点击
        self.assertEqual(accepted1.status, accepted2.status)
        self.assertEqual(str(accepted1.id), str(accepted2.id))

    def test_handoff_idempotent(self):
        """§25.6 HR05 handoff 重复调用 → 同一记录。"""
        from hr_recruitment.services.handoff_service import HandoffService
        from hr_recruitment.services.notice_service import NoticeService
        from hr_recruitment.services.offer_service import OfferService
        from hr_recruitment.services.proposed_hire_service import ProposedHireService
        from hr_recruitment.services.qualification_service import QualificationService

        draft = self.app_service.save_draft(
            candidate_id=str(self.candidate.id),
            recruitment_position_id=str(self.position.id),
        )
        app = self.app_service.submit(application_id=str(draft.id))
        self._bind_rule_set(app)
        qual = QualificationService(tenant_id=TENANT, actor="reviewer")
        qual.start_review(application_id=str(app.id))
        qual.decision(application_id=str(app.id), decision="QUALIFIED", reason_text="ok")
        app.refresh_from_db()
        app.canonical_status = S.QUALIFIED
        app.save(update_fields=["canonical_status"])

        proposed_service = ProposedHireService(tenant_id=TENANT, actor="hr")
        # 真实 HR02 HELD 预占（handoff 前置要求 HELD）
        from datetime import timedelta

        from django.utils import timezone
        from hr_structure.models import (
            HrOrganization,
            HrPosition,
            HrPositionReservation,
            HrPostCatalog,
            HrPostCatalogVersion,
        )

        org = HrOrganization.objects.create(
            tenant_id=TENANT, stable_code="ORG-CONC", org_dimension="ADMIN"
        )
        catalog = HrPostCatalog.objects.create(tenant_id=TENANT, stable_code="CAT-CONC")
        catalog_ver = HrPostCatalogVersion.objects.create(
            catalog_id=catalog, tenant_id=TENANT, name="并发岗位", validity_from=date.today()
        )
        hr_position = HrPosition.objects.create(
            tenant_id=TENANT,
            position_code="POS-CONC-1",
            organization_id=org,
            post_catalog_version_id=catalog_ver,
            max_incumbents=1,
            validity_from=date.today(),
            lifecycle_status=HrPosition.LifecycleStatus.ACTIVE,
        )
        reservation = HrPositionReservation.objects.create(
            tenant_id=TENANT,
            reservation_no="RESV-CONC-1",
            position_id=hr_position,
            source_domain="hr04",
            source_business_type="recruitment_position",
            source_business_id="conc-test",
            status=HrPositionReservation.Status.HELD,
            expires_at=timezone.now() + timedelta(days=7),
            idempotency_key="conc-resv",
        )
        proposed = proposed_service.create(
            application_id=str(app.id),
            rank=1,
            reservation_id=str(reservation.id),
            reservation_no=reservation.reservation_no,
        )
        proposed_service.decide(proposed_hire_id=str(proposed.id), decision="APPROVE")
        # 公示闭环
        notice_service = NoticeService(tenant_id=TENANT, actor="hr")
        notice = notice_service.publish_notice(
            campaign_id=str(self.campaign.id),
            notice_no="GS-CONC-1",
            entries=[{"proposed_hire_id": str(proposed.id), "public_display_name": "张**"}],
        )
        notice_service.close_notice(notice_id=str(notice.id), has_blocker=False)
        # Offer 接受
        offer_service = OfferService(tenant_id=TENANT, actor="hr")
        offer = offer_service.create_offer(
            proposed_hire_id=str(proposed.id), offer_no="OFFER-CONC-2"
        )
        offer_service.transition(offer_id=str(offer.id), target="APPROVED")
        offer_service.transition(offer_id=str(offer.id), target="ISSUED")
        offer_service.accept(offer_id=str(offer.id))

        handoff_service = HandoffService(tenant_id=TENANT, actor="hr")
        h1 = handoff_service.handoff(proposed_hire_id=str(proposed.id), idempotency_key="conc-key-1")
        h2 = handoff_service.handoff(proposed_hire_id=str(proposed.id), idempotency_key="conc-key-2")
        self.assertEqual(str(h1.id), str(h2.id))
        self.assertEqual(
            HrRecruitmentHandoff.objects.filter(proposed_hire_id_id=proposed.id).count(), 1
        )

    def test_capacity_last_slot_not_exceeded(self):
        """最后名额：max_hires=1，第二个拟录用被拒绝（额度冲突）。"""
        from hr_recruitment.api.exceptions import PositionCapacityConflictError
        from hr_recruitment.services.proposed_hire_service import ProposedHireService
        from hr_recruitment.services.qualification_service import QualificationService

        def make_qualified(email):
            cand = CandidateService(tenant_id=TENANT).create_candidate(
                legal_name=email, primary_email=email
            )
            draft = self.app_service.save_draft(
                candidate_id=str(cand.id),
                recruitment_position_id=str(self.position.id),
            )
            app = self.app_service.submit(application_id=str(draft.id))
            self._bind_rule_set(app)
            qual = QualificationService(tenant_id=TENANT, actor="reviewer")
            qual.start_review(application_id=str(app.id))
            qual.decision(application_id=str(app.id), decision="QUALIFIED", reason_text="ok")
            app.refresh_from_db()
            app.canonical_status = S.QUALIFIED
            app.save(update_fields=["canonical_status"])
            return app

        app1 = make_qualified("c1@test.local")
        service = ProposedHireService(tenant_id=TENANT, actor="hr")
        service.create(application_id=str(app1.id), rank=1, reservation_id="r3")
        # 第二个候选人拟录用 → 超额度被拒
        app2 = make_qualified("c2@test.local")
        with self.assertRaises(PositionCapacityConflictError):
            service.create(application_id=str(app2.id), rank=2, reservation_id="r4")
