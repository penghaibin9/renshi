"""
hr_recruitment/services/offer_service.py

HR04-06 Offer 服务（《04_HR04_总册》§13.6/§25.5）。

状态机：DRAFT → APPROVED → ISSUED → VIEWED → ACCEPTED / DECLINED / EXPIRED / WITHDRAWN。
硬规则：Offer 接受重复点击幂等（§25.5）。
"""

from __future__ import annotations

from datetime import timedelta, date
import hashlib
import json

from django.db import transaction
from django.utils import timezone

from hr_recruitment.constants import (
    ApplicationCanonicalStatus as S,
    OfferStatus,
)
from hr_recruitment.models import HrRecruitmentOffer, HrProposedHire
from hr_recruitment.services.audit_service import audit_event


class OfferServiceError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 422):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


def offer_snapshot(offer):
    """Saved terms, not a re-created frontend draft. No resume/account data."""
    body = {
        "id": str(offer.id), "offer_no": offer.offer_no,
        "proposed_hire_id": str(offer.proposed_hire_id_id), "status": offer.status,
        "employment_type": offer.employment_type,
        "expected_report_date": str(offer.expected_report_date) if offer.expected_report_date else None,
        "expires_at": offer.expires_at.isoformat() if offer.expires_at else None,
        "document_id": str(offer.document_id) if offer.document_id else None,
        "version": offer.version,
    }
    body["fingerprint"] = hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()
    return body


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
        proposed = HrProposedHire.objects.select_for_update().filter(
            pk=proposed_hire_id, tenant_id=self.tenant_id,
            application_id__tenant_id=self.tenant_id, recruitment_position_id__tenant_id=self.tenant_id,
            application_id__candidate_id__tenant_id=self.tenant_id,
        ).first()
        if proposed is None:
            raise OfferServiceError("PROPOSED_HIRE_NOT_FOUND", "拟录用记录不存在或学校归属不一致", http_status=404)
        if not isinstance(offer_no, str) or not offer_no.strip() or len(offer_no)>64:
            raise OfferServiceError("OFFER_NUMBER_INVALID", "录用通知编号必填且不得超过64字")
        offer_no = offer_no.strip()
        try:
            days = int(expires_in_days)
            if isinstance(expires_in_days, bool) or str(days) != str(expires_in_days) or days <= 0:
                raise ValueError()
            expires_at = timezone.now() + timedelta(days=days)
        except (ValueError, TypeError, OverflowError):
            raise OfferServiceError("OFFER_EXPIRY_INVALID", "有效天数必须为可表示的正整数")
        if expected_report_date and isinstance(expected_report_date, str):
            try: expected_report_date = date.fromisoformat(expected_report_date)
            except ValueError: raise OfferServiceError("OFFER_REPORT_DATE_INVALID", "预计报到日期无效")
        if not isinstance(employment_type, str) or len(employment_type)>64:
            raise OfferServiceError("OFFER_EMPLOYMENT_TYPE_INVALID", "用工性质格式无效")
        if HrRecruitmentOffer.objects.filter(tenant_id=self.tenant_id, offer_no=offer_no).exists():
            raise OfferServiceError("OFFER_NO_DUPLICATE", f"Offer 编号 {offer_no} 已存在", http_status=409)
        return HrRecruitmentOffer.objects.create(
            tenant_id=self.tenant_id,
            proposed_hire_id_id=proposed_hire_id,
            offer_no=offer_no,
            status=OfferStatus.DRAFT,
            expires_at=expires_at,
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
    def transition(self, *, offer_id: str, target: str, expected_fingerprint: str | None = None) -> HrRecruitmentOffer:
        offer = self._get(offer_id)
        before = offer_snapshot(offer)
        if expected_fingerprint is not None and before["fingerprint"] != expected_fingerprint:
            raise OfferServiceError("OFFER_VERSION_CONFLICT", "录用通知内容或状态已改变，请重新核对实际保存的内容", http_status=409)
        self._assert(offer, target)
        if target == OfferStatus.ISSUED:
            offer.issued_at = timezone.now()
        if target == OfferStatus.ACCEPTED:
            offer.accepted_at = timezone.now()
        if target == OfferStatus.DECLINED:
            offer.declined_at = timezone.now()
        offer.status = target
        offer.version += 1
        offer.save(update_fields=["status", "issued_at", "accepted_at", "declined_at", "version"])
        if target == OfferStatus.ACCEPTED:
            self._on_accepted(offer)
            self._seal_hiring_authority(offer)
        audit_event(tenant_id=self.tenant_id, event_type="OFFER_STATUS_CHANGED", business_object="HrRecruitmentOffer",
            business_object_id=str(offer.id), actor_id=self.actor, action=target,
            summary="录用通知内容与状态核对", before={"version": before["version"], "fingerprint": before["fingerprint"], "status": before["status"]},
            after={"version": offer.version, "fingerprint": offer_snapshot(offer)["fingerprint"], "status": offer.status})
        return offer

    @transaction.atomic
    def accept(self, *, offer_id: str) -> HrRecruitmentOffer:
        """接受 Offer（幂等：已 ACCEPTED 直接返回；过期拒绝）。"""
        offer = self._get(offer_id)
        if offer.status == OfferStatus.ACCEPTED:
            self._seal_hiring_authority(offer)
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
        self._seal_hiring_authority(offer)
        return offer

    def _seal_hiring_authority(self, offer: HrRecruitmentOffer) -> None:
        """Create the immutable hiring fact in the same database transaction."""
        from hr_recruitment.services.hiring_authority_service import (
            HiringAuthorityService,
        )

        HiringAuthorityService(
            tenant_id=self.tenant_id,
            actor_id=self.actor,
        ).seal_accepted_offer(offer_id=offer.id)

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
            return HrRecruitmentOffer.objects.select_for_update().select_related(
                "proposed_hire_id__application_id"
            ).get(id=offer_id, tenant_id=self.tenant_id,
                  proposed_hire_id__tenant_id=self.tenant_id,
                  proposed_hire_id__application_id__tenant_id=self.tenant_id,
                  proposed_hire_id__recruitment_position_id__tenant_id=self.tenant_id)
        except HrRecruitmentOffer.DoesNotExist:
            raise OfferServiceError("OFFER_NOT_FOUND", "Offer 不存在", http_status=404)
