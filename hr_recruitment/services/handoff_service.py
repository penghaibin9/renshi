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

        终态安全：消费者未交付（None）时 handoff 标 FAILED 且申请保持 OFFER_ACCEPTED，
        不推入不可逆 HANDOFF_TO_HR05 终态（防 HR05 从未收到但申请已锁死）。
        """
        # 幂等：同一 proposed_hire 已有记录（任意 status，唯一约束保证只有一条）
        existing = HrRecruitmentHandoff.objects.filter(
            tenant_id=self.tenant_id,
            proposed_hire_id_id=proposed_hire_id,
        ).first()
        if existing is not None:
            if existing.status == HandoffStatus.CREATED:
                return existing  # 已成功交接
            if hr05_consumer is None:
                return existing  # 消费者未交付：返回 FAILED 占位（重复调用不重复建）
            # FAILED + 有消费者：补消费（重试），不重建记录
            return self._complete_handoff(existing, hr05_consumer, idempotency_key)

        # 行锁 proposed（防 TOCTOU：precondition 检查与 create 之间 offer/notice 被改）
        proposed = self._get_proposed(proposed_hire_id, for_update=True)
        self._check_preconditions(proposed)

        try:
            handoff = HrRecruitmentHandoff.objects.create(
                tenant_id=self.tenant_id,
                proposed_hire_id=proposed,
                application_id=proposed.application_id,
                reservation_id=proposed.reservation_id,
                status=HandoffStatus.FAILED,  # 先占位 FAILED，消费成功才置 CREATED
                idempotency_key=idempotency_key,
                payload_snapshot=self._payload(proposed),
                created_by=self.actor,
            )
        except IntegrityError:
            # 并发重复：返回已存在记录
            existing = HrRecruitmentHandoff.objects.get(
                tenant_id=self.tenant_id, proposed_hire_id_id=proposed_hire_id
            )
            if existing.status == HandoffStatus.CREATED or hr05_consumer is None:
                return existing
            return self._complete_handoff(existing, hr05_consumer, idempotency_key)

        # 调用 HR05 消费端（V1 契约占位）
        if hr05_consumer is not None:
            return self._complete_handoff(handoff, hr05_consumer, idempotency_key)
        # 消费者未交付：handoff 占位 FAILED，申请保持 OFFER_ACCEPTED（不推终态）
        return handoff

    def _complete_handoff(self, handoff, hr05_consumer, idempotency_key) -> HrRecruitmentHandoff:
        """调用 HR05 消费端；成功置 CREATED + 推终态；失败保留 FAILED。"""
        try:
            hr05_case_id = hr05_consumer.handle(
                proposed_hire_id=str(handoff.proposed_hire_id_id),
                idempotency_key=idempotency_key,
            )
        except Exception:  # noqa: BLE001
            # 消费失败：保留 FAILED，申请不进终态，由重试机制补偿
            return handoff
        handoff.hr05_case_id = hr05_case_id or ""
        handoff.status = HandoffStatus.CREATED
        handoff.save(update_fields=["hr05_case_id", "status"])

        # 消费成功后才推终态（走状态机 + 写 ledger）
        from hr_recruitment.models import HrApplicationTransition
        from hr_recruitment.policies.state_machine import assert_transition

        proposed = handoff.proposed_hire_id
        app = proposed.application_id
        if app.canonical_status != S.HANDOFF_TO_HR05:
            assert_transition(app.canonical_status, S.HANDOFF_TO_HR05)
            from_status = app.canonical_status
            app.canonical_status = S.HANDOFF_TO_HR05
            app.version += 1
            app.save(update_fields=["canonical_status", "version"])
            HrApplicationTransition.objects.create(
                tenant_id=self.tenant_id,
                application_id=app,
                from_status=from_status,
                to_status=S.HANDOFF_TO_HR05,
                action="HANDOFF_TO_HR05",
                actor_id=self.actor,
                source="HR_ADMIN",
            )
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
        # Offer ACCEPTED（学校流程要求时；用 created_at 排序，UUID 无时间语义）
        offer = HrRecruitmentOffer.objects.filter(
            tenant_id=self.tenant_id, proposed_hire_id=proposed
        ).order_by("-created_at").first()
        if offer is None or offer.status != OfferStatus.ACCEPTED:
            missing.append("Offer 未接受")
        # Reservation VALID：须为 HELD 预占（§13.7）
        if not proposed.reservation_id:
            missing.append("岗位预占缺失")
        else:
            try:
                from hr_structure.models import HrPositionReservation

                reservation = HrPositionReservation.objects.filter(
                    tenant_id=self.tenant_id, id=int(proposed.reservation_id)
                ).first()
                if reservation is None or reservation.status != HrPositionReservation.Status.HELD:
                    missing.append("岗位预占无效（须为 HELD）")
            except (ValueError, TypeError):
                missing.append("岗位预占无效")
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

    def _get_proposed(self, proposed_hire_id: str, for_update: bool = False) -> HrProposedHire:
        qs = HrProposedHire.objects.select_related("application_id__candidate_id")
        if for_update:
            qs = qs.select_for_update()
        try:
            return qs.get(id=proposed_hire_id, tenant_id=self.tenant_id)
        except HrProposedHire.DoesNotExist:
            raise HandoffServiceError("PROPOSED_HIRE_NOT_FOUND", "拟录用不存在", http_status=404)
