"""
hr_recruitment/services/offer_service.py

HR04-06 Offer 服务（《04_HR04_总册》§13.6/§25.5）。

状态机：DRAFT → APPROVED → ISSUED → VIEWED → ACCEPTED / DECLINED / EXPIRED / WITHDRAWN。
硬规则：Offer 接受重复点击幂等（§25.5）。
"""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from hr_recruitment.constants import (
    ApplicationCanonicalStatus as S,
    OfferStatus,
)
from hr_recruitment.models import HrRecruitmentOffer


class OfferServiceError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 422):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


class OfferService:
    def __init__(self, *, tenant_id: int, actor: str = ""):
        self.tenant_id = tenant_id
        self.actor = actor

    _ALLOWED = {
        OfferStatus.DRAFT: {OfferStatus.APPROVED, OfferStatus.WITHDRAWN},
        OfferStatus.APPROVED: {OfferStatus.ISSUED, OfferStatus.WITHDRAWN},
        OfferStatus.ISSUED: {OfferStatus.VIEWED, OfferStatus.ACCEPTED, OfferStatus.DECLINED, OfferStatus.EXPIRED},
        OfferStatus.VIEWED: {OfferStatus.ACCEPTED, OfferStatus.DECLINED, OfferStatus.EXPIRED},
        OfferStatus.ACCEPTED: set(),
        OfferStatus.DECLINED: set(),
        OfferStatus.EXPIRED: set(),
        OfferStatus.WITHDRAWN: set(),
    }

    @transaction.atomic
    def create_offer(
        self,
        *,
        proposed_hire_id: str,
        offer_no: str,
        employment_type="",
        expected_report_date=None,
        expires_in_days=7,
    ) -> HrRecruitmentOffer:
        if HrRecruitmentOffer.objects.filter(tenant_id=self.tenant_id, offer_no=offer_no).exists():
            raise OfferServiceError("OFFER_NO_DUPLICATE", f"Offer 编号 {offer_no} 已存在", http_status=409)
        return HrRecruitmentOffer.objects.create(
            tenant_id=self.tenant_id,
            proposed_hire_id_id=proposed_hire_id,
            offer_no=offer_no,
            status=OfferStatus.DRAFT,
            expires_at=timezone.now() + timedelta(days=expires_in_days),
            employment_type=employment_type,
            expected_report_date=expected_report_date,
            created_by=self.actor,
        )

    def _assert(self, offer, target: str) -> None:
        allowed = self._ALLOWED.get(offer.status, set())
        if target not in allowed:
            raise OfferServiceError(
                "INVALID_OFFER_TRANSITION", f"非法 Offer 状态迁移: {offer.status} -> {target}", http_status=409
            )

    @transaction.atomic
    def transition(self, *, offer_id: str, target: str) -> HrRecruitmentOffer:
        offer = self._get(offer_id)
        self._assert(offer, target)
        if target == OfferStatus.ISSUED:
            offer.issued_at = timezone.now()
        if target == OfferStatus.ACCEPTED:
            offer.accepted_at = timezone.now()
            self._on_accepted(offer)
        if target == OfferStatus.DECLINED:
            offer.declined_at = timezone.now()
        offer.status = target
        offer.version += 1
        offer.save(update_fields=["status", "issued_at", "accepted_at", "declined_at", "version"])
        return offer

    @transaction.atomic
    def accept(self, *, offer_id: str) -> HrRecruitmentOffer:
        """接受 Offer（幂等：已 ACCEPTED 直接返回；过期拒绝）。"""
        offer = self._get(offer_id)
        if offer.status == OfferStatus.ACCEPTED:
            return offer  # 幂等重放
        if offer.expires_at and offer.expires_at < timezone.now():
            raise OfferServiceError(
                "OFFER_EXPIRED", "Offer 已过期，不可接受", http_status=409
            )
        self._assert(offer, OfferStatus.ACCEPTED)
        offer.status = OfferStatus.ACCEPTED
        offer.accepted_at = timezone.now()
        offer.version += 1
        offer.save(update_fields=["status", "accepted_at", "version"])
        self._on_accepted(offer)
        return offer

    def _on_accepted(self, offer: HrRecruitmentOffer) -> None:
        """Offer 接受 → 申请状态 OFFER_ACCEPTED（走状态机 + 写 ledger，幂等）。"""
        proposed = offer.proposed_hire_id
        app = proposed.application_id
        from hr_recruitment.models import HrApplicationTransition
        from hr_recruitment.policies.state_machine import assert_transition

        if app.canonical_status == S.OFFER_ACCEPTED:
            return  # 幂等
        assert_transition(app.canonical_status, S.OFFER_ACCEPTED)
        from_status = app.canonical_status
        app.canonical_status = S.OFFER_ACCEPTED
        app.version += 1
        app.save(update_fields=["canonical_status", "version"])
        HrApplicationTransition.objects.create(
            tenant_id=self.tenant_id,
            application_id=app,
            from_status=from_status,
            to_status=S.OFFER_ACCEPTED,
            action="OFFER_ACCEPTED",
            actor_id=self.actor,
            source="HR_ADMIN",
        )

    def _get(self, offer_id: str) -> HrRecruitmentOffer:
        try:
            return HrRecruitmentOffer.objects.select_related(
                "proposed_hire_id__application_id"
            ).get(id=offer_id, tenant_id=self.tenant_id)
        except HrRecruitmentOffer.DoesNotExist:
            raise OfferServiceError("OFFER_NOT_FOUND", "Offer 不存在", http_status=404)
