"""
hr_recruitment/services/handoff_service.py

HANDOFF_TO_HR05 服务（《04_HR04_总册》§13.7/§25.6 + HR05 RecruitToHireMapping）。

前置条件（全部满足才允许）：
- HrProposedHire APPROVED；
- 公示 HrPublicNotice CLOSED_NO_BLOCKER；
- HrRecruitmentOffer ACCEPTED；
- PositionReservation VALID（必须保持 HELD，真正 COMMIT 由 HR05 ActivationService 在 HR03 生效后执行）。

幂等：同一 proposed_hire 重复调用返回同一 HR05 case；
DB 约束 unique(tenant, proposed_hire) + idempotency_key unique 兜底。

关键安全纪律：HR04 handoff 只完成招聘事实到 HR05 case 的交接，绝不能提前占用正式岗位额度。
HR05 ActivationService 在 HR03 Person/Staff/Employment/Assignment 全部成功后才把 HR02 reservation
从 HELD 提交为 COMMITTED；失败或放弃仍可由 HR05 释放 reservation。
"""

from __future__ import annotations

import logging

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

logger = logging.getLogger(__name__)


class HandoffServiceError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 422):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


class HandoffService:
    def __init__(self, *, tenant_id: int, actor: str = ""):
        if not tenant_id:
            raise HandoffServiceError("TENANT_REQUIRED", "tenant_id is required")
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
        existing = HrRecruitmentHandoff.objects.filter(
            tenant_id=self.tenant_id,
            proposed_hire_id_id=proposed_hire_id,
        ).first()
        if existing is not None:
            if existing.status == HandoffStatus.CREATED:
                return existing
            if hr05_consumer is None:
                return existing
            return self._complete_handoff(existing, hr05_consumer, idempotency_key)

        proposed = self._get_proposed(proposed_hire_id, for_update=True)
        self._check_preconditions(proposed)

        try:
            handoff = HrRecruitmentHandoff.objects.create(
                tenant_id=self.tenant_id,
                proposed_hire_id=proposed,
                application_id=proposed.application_id,
                reservation_id=proposed.reservation_id,
                status=HandoffStatus.FAILED,
                idempotency_key=idempotency_key,
                payload_snapshot=self._payload(proposed),
                created_by=self.actor,
            )
        except IntegrityError:
            existing = HrRecruitmentHandoff.objects.get(
                tenant_id=self.tenant_id,
                proposed_hire_id_id=proposed_hire_id,
            )
            if existing.status == HandoffStatus.CREATED or hr05_consumer is None:
                return existing
            return self._complete_handoff(existing, hr05_consumer, idempotency_key)

        if hr05_consumer is not None:
            return self._complete_handoff(handoff, hr05_consumer, idempotency_key)
        return handoff

    def _complete_handoff(
        self,
        handoff,
        hr05_consumer,
        idempotency_key,
    ) -> HrRecruitmentHandoff:
        """HR05 case 创建成功且 HR02 reservation 仍 HELD 后，才允许标 CREATED。"""
        from hr_recruitment.services.audit_service import audit_event

        if getattr(handoff, "tenant_id", None) != self.tenant_id:
            raise HandoffServiceError("CROSS_TENANT_HANDOFF", "handoff tenant mismatch")

        try:
            hr05_case_id = hr05_consumer.handle(
                tenant_id=self.tenant_id,
                proposed_hire_id=str(handoff.proposed_hire_id_id),
                idempotency_key=idempotency_key,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "HR04->HR05 consumer failed tenant=%s handoff=%s",
                self.tenant_id,
                getattr(handoff, "id", None),
            )
            audit_event(
                tenant_id=self.tenant_id,
                event_type="HANDOFF_HR05_CONSUMER_FAILED",
                business_object="HrRecruitmentHandoff",
                business_object_id=str(handoff.id),
                actor_id=self.actor,
                action="CONSUMER_FAILED",
                summary=f"HR05 消费失败：{str(exc)[:300]}",
            )
            return handoff

        # HR05 已成功创建/返回幂等 case；先保存 case_id，但 handoff 仍保持 FAILED。
        handoff.hr05_case_id = hr05_case_id or ""
        handoff.save(update_fields=["hr05_case_id"])

        proposed = handoff.proposed_hire_id

        # HR04 不再提前 COMMIT 岗位。交接后重新锁行确认 reservation 仍为 HELD，
        # 真正 HELD -> COMMITTED 只允许在 HR05 ActivationService 完成人员事实后执行。
        if proposed.reservation_id:
            try:
                from hr_structure.models import HrPositionReservation

                reservation = HrPositionReservation.objects.select_for_update().filter(
                    tenant_id=self.tenant_id,
                    id=int(proposed.reservation_id),
                ).first()
                if (
                    reservation is None
                    or reservation.status != HrPositionReservation.Status.HELD
                    or (reservation.expires_at and reservation.expires_at <= timezone.now())
                ):
                    raise HandoffServiceError(
                        "POSITION_RESERVATION_NOT_HELD",
                        "HR05 case 已创建，但岗位预占不再是有效 HELD 状态",
                        http_status=409,
                    )
            except (ValueError, TypeError, HandoffServiceError) as exc:
                logger.warning(
                    "HR02 reservation invalid after HR05 consumer tenant=%s reservation=%s handoff=%s",
                    self.tenant_id,
                    proposed.reservation_id,
                    getattr(handoff, "id", None),
                )
                audit_event(
                    tenant_id=self.tenant_id,
                    event_type="RESERVATION_INVALID_AFTER_HR05",
                    business_object="HrRecruitmentHandoff",
                    business_object_id=str(handoff.id),
                    actor_id=self.actor,
                    action="VALIDATION_FAILED",
                    summary=(
                        f"HR05 case 已创建但岗位预占无效（reservation={proposed.reservation_id}）："
                        f"{str(exc)[:300]}"
                    ),
                    after={
                        "status": HandoffStatus.FAILED,
                        "hr05_case_id": handoff.hr05_case_id,
                    },
                )
                return handoff

        handoff.status = HandoffStatus.CREATED
        handoff.save(update_fields=["status"])

        from hr_recruitment.models import HrApplicationTransition
        from hr_recruitment.policies.state_machine import assert_transition

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

        audit_event(
            tenant_id=self.tenant_id,
            event_type="HANDOFF_TO_HR05",
            business_object="HrRecruitmentHandoff",
            business_object_id=str(handoff.id),
            actor_id=self.actor,
            action="HANDOFF_CREATED",
            summary=(
                f"HR05 交接创建（hr05_case_id={handoff.hr05_case_id}，"
                f"proposed={proposed.id}）"
            ),
            after={
                "status": handoff.status,
                "hr05_case_id": handoff.hr05_case_id,
                "reservation_status": "HELD_PENDING_HR05_ACTIVATION",
            },
        )
        return handoff

    def _check_preconditions(self, proposed: HrProposedHire) -> None:
        missing = []
        if proposed.approval_status != "APPROVE":
            missing.append("ProposedHire 未批准")
        notice = (
            HrPublicNotice.objects.filter(
                tenant_id=self.tenant_id,
                entries__proposed_hire_id=proposed,
            )
            .order_by("-published_at")
            .first()
        )
        if notice is None or notice.status != PublicNoticeStatus.CLOSED_NO_BLOCKER:
            missing.append("公示未闭环（需 CLOSED_NO_BLOCKER）")
        offer = (
            HrRecruitmentOffer.objects.filter(
                tenant_id=self.tenant_id,
                proposed_hire_id=proposed,
            )
            .order_by("-created_at")
            .first()
        )
        if offer is None or offer.status != OfferStatus.ACCEPTED:
            missing.append("Offer 未接受")
        if not proposed.reservation_id:
            missing.append("岗位预占缺失")
        else:
            try:
                from hr_structure.models import HrPositionReservation

                reservation = HrPositionReservation.objects.filter(
                    tenant_id=self.tenant_id,
                    id=int(proposed.reservation_id),
                ).first()
                if (
                    reservation is None
                    or reservation.status != HrPositionReservation.Status.HELD
                ):
                    missing.append("岗位预占无效（须为 HELD）")
                elif reservation.expires_at and reservation.expires_at <= timezone.now():
                    missing.append("岗位预占已过期")
            except (ValueError, TypeError):
                missing.append("岗位预占无效")
        if missing:
            raise HandoffPreconditionError("；".join(missing))

    def _payload(self, proposed: HrProposedHire) -> dict:
        app = proposed.application_id
        position = proposed.recruitment_position_id
        offer = (
            HrRecruitmentOffer.objects.filter(
                tenant_id=self.tenant_id,
                proposed_hire_id=proposed,
                status=OfferStatus.ACCEPTED,
            )
            .order_by("-accepted_at", "-created_at")
            .first()
        )
        return {
            "tenant_id": self.tenant_id,
            "proposed_hire_id": str(proposed.id),
            "application_id": str(app.id),
            "reservation_id": proposed.reservation_id or "",
            "candidate_uid": app.candidate_id.candidate_uid if app.candidate_id else "",
            "legal_name": app.candidate_id.legal_name if app.candidate_id else "",
            "primary_email": app.candidate_id.primary_email if app.candidate_id else "",
            "organization_id": position.organization_id if position else None,
            "post_catalog_id": position.post_catalog_id if position else None,
            "position_id": position.position_id if position else None,
            "recruitment_position_id": str(position.id) if position else "",
            "employment_type": offer.employment_type if offer else "",
            "expected_report_date": (
                offer.expected_report_date.isoformat()
                if offer and offer.expected_report_date
                else None
            ),
            "rank": proposed.rank,
            "final_score": str(proposed.final_score),
            "handoff_at": timezone.now().isoformat(),
        }

    def _get_proposed(
        self,
        proposed_hire_id: str,
        for_update: bool = False,
    ) -> HrProposedHire:
        qs = HrProposedHire.objects.select_related(
            "application_id__candidate_id",
            "recruitment_position_id",
        )
        if for_update:
            qs = qs.select_for_update()
        try:
            return qs.get(id=proposed_hire_id, tenant_id=self.tenant_id)
        except HrProposedHire.DoesNotExist:
            raise HandoffServiceError(
                "PROPOSED_HIRE_NOT_FOUND",
                "拟录用不存在",
                http_status=404,
            )
