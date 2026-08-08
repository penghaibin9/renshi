"""
hr_recruitment/services/handoff_service.py

HANDOFF_TO_HR05 服务（《04_HR04_总册》§13.7/§25.6 + HR05 RecruitToHireMapping）。

前置条件（全部满足才允许）：
- HrProposedHire APPROVED；
- 公示 HrPublicNotice CLOSED_NO_BLOCKER（公示闭环无 blocker）；
- HrRecruitmentOffer ACCEPTED（学校流程要求时）；
- PositionReservation VALID（HELD 可 commit）。

幂等：同一 proposed_hire 重复调用返回同一 HR05 case；
DB 约束 unique(tenant, proposed_hire) + idempotency_key unique 兜底，绝不生成第二份。

HR04 保存 handoff_id / handoff_at / hr05_case_id。
"""

from __future__ import annotations

from django.db import IntegrityError, transaction
from django.utils import timezone

from hr_recruitment.api.exceptions import HandoffPreconditionError
from hr_recruitment.constants import (
    ApplicationCanonicalStatus as S,
    HandoffStatus,
    OfferStatus,
    PublicNoticeStatus,
)
from hr_recruitment.models import (
    HrProposedHire,
    HrPublicNotice,
    HrRecruitmentHandoff,
    HrRecruitmentOffer,
)


class HandoffServiceError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 422):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


class HandoffService:
    def __init__(self, *, tenant_id: int, actor: str = ""):
        self.tenant_id = tenant_id
        self.actor = actor

    @transaction.atomic
    def handoff(
        self,
        *,
        proposed_hire_id: str,
        idempotency_key: str,
        hr05_consumer: object | None = None,
    ) -> HrRecruitmentHandoff:
        """
        HANDOFF_TO_HR05（幂等）。

        hr05_consumer：HR05 侧幂等消费者回调（V1 占位，返回 hr05_case_id）。
        # [总控占位] 待 HR05 `HandleRecruitmentHandoff` 交付后改为 outbox 事件消费。
        """
        # 幂等重放：同一 proposed_hire 已 handoff → 返回原记录
        existing = HrRecruitmentHandoff.objects.filter(
            tenant_id=self.tenant_id, proposed_hire_id_id=proposed_hire_id
        ).first()
        if existing is not None:
            return existing

        proposed = self._get_proposed(proposed_hire_id)
        self._check_preconditions(proposed)

        try:
            handoff = HrRecruitmentHandoff.objects.create(
                tenant_id=self.tenant_id,
                proposed_hire_id=proposed,
                application_id=proposed.application_id,
                reservation_id=proposed.reservation_id,
                status=HandoffStatus.CREATED,
                idempotency_key=idempotency_key,
                payload_snapshot=self._payload(proposed),
                created_by=self.actor,
            )
        except IntegrityError:
            # 并发重复：返回已存在记录
            return HrRecruitmentHandoff.objects.get(
                tenant_id=self.tenant_id, proposed_hire_id_id=proposed_hire_id
            )

        # 调用 HR05 消费端（V1 契约占位）
        hr05_case_id = ""
        if hr05_consumer is not None:
            hr05_case_id = hr05_consumer.handle(proposed_hire_id=proposed_hire_id, idempotency_key=idempotency_key)
            handoff.hr05_case_id = hr05_case_id or ""
            handoff.save(update_fields=["hr05_case_id"])

        # 申请状态 → HANDOFF_TO_HR05
        app = proposed.application_id
        if app.canonical_status != S.HANDOFF_TO_HR05:
            app.canonical_status = S.HANDOFF_TO_HR05
            app.version += 1
            app.save(update_fields=["canonical_status", "version"])
        return handoff

    def _check_preconditions(self, proposed: HrProposedHire) -> None:
        """前置条件（§13.7）：全部满足才允许。"""
        missing = []
        if proposed.approval_status != "APPROVE":
            missing.append("ProposedHire 未批准")
        # 公示闭环（无 blocker）
        notice = HrPublicNotice.objects.filter(
            tenant_id=self.tenant_id, entries__proposed_hire_id=proposed
        ).order_by("-published_at").first()
        if notice is None or notice.status != PublicNoticeStatus.CLOSED_NO_BLOCKER:
            missing.append("公示未闭环（需 CLOSED_NO_BLOCKER）")
        # Offer ACCEPTED（学校流程要求时）
        offer = HrRecruitmentOffer.objects.filter(
            tenant_id=self.tenant_id, proposed_hire_id=proposed
        ).order_by("-id").first()
        if offer is None or offer.status != OfferStatus.ACCEPTED:
            missing.append("Offer 未接受")
        # Reservation VALID
        if not proposed.reservation_id:
            missing.append("岗位预占缺失")
        if missing:
            raise HandoffPreconditionError("；".join(missing))

    def _payload(self, proposed: HrProposedHire) -> dict:
        app = proposed.application_id
        return {
            "proposed_hire_id": str(proposed.id),
            "application_id": str(app.id),
            "reservation_id": proposed.reservation_id or "",
            "candidate_uid": app.candidate_id.candidate_uid if app.candidate_id else "",
            "legal_name": app.candidate_id.legal_name if app.candidate_id else "",
            "primary_email": app.candidate_id.primary_email if app.candidate_id else "",
            "position_id": str(proposed.recruitment_position_id_id),
            "rank": proposed.rank,
            "final_score": str(proposed.final_score),
            "handoff_at": timezone.now().isoformat(),
        }

    def _get_proposed(self, proposed_hire_id: str) -> HrProposedHire:
        try:
            return HrProposedHire.objects.select_related("application_id__candidate_id").get(
                id=proposed_hire_id, tenant_id=self.tenant_id
            )
        except HrProposedHire.DoesNotExist:
            raise HandoffServiceError("PROPOSED_HIRE_NOT_FOUND", "拟录用不存在", http_status=404)
