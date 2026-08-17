"""Qualification review authority for HR13 title applications."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from django.db import transaction
from django.db.models import Max

from hr_title.models import TitleApplicationCase, TitleQualificationDecision


class TitleQualificationError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class QualificationOutcome:
    decision: TitleQualificationDecision
    case: TitleApplicationCase
    created: bool


class TitleQualificationService:
    _TARGET_STATUS = {
        TitleQualificationDecision.Decision.ELIGIBLE: TitleApplicationCase.Status.ELIGIBLE,
        TitleQualificationDecision.Decision.RETURNED: TitleApplicationCase.Status.RETURNED,
        TitleQualificationDecision.Decision.REJECTED: TitleApplicationCase.Status.REJECTED,
    }

    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise TitleQualificationError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    def _existing_idempotent(
        self,
        *,
        decision_no: str,
        case_id,
        decision: str,
        reason_code: str,
        reason: str,
    ) -> QualificationOutcome | None:
        existing = TitleQualificationDecision.objects.filter(
            tenant_id=self.tenant_id,
            decision_no=decision_no,
        ).first()
        if existing is None:
            return None
        if (
            existing.application_case_id != case_id
            or existing.decision != decision
            or existing.reason_code != reason_code
            or existing.reason != reason
        ):
            raise TitleQualificationError(
                "TITLE_QUALIFICATION_IDEMPOTENCY_CONFLICT",
                "decision_no already exists with different review content",
            )
        case = TitleApplicationCase.objects.filter(
            tenant_id=self.tenant_id,
            id=case_id,
        ).first()
        if case is None:
            raise TitleQualificationError("TITLE_CASE_NOT_FOUND", "application case not found")
        return QualificationOutcome(existing, case, False)

    @transaction.atomic
    def decide(
        self,
        *,
        case_id,
        decision_no: str,
        decision: str,
        reason_code: str = "",
        reason: str = "",
    ) -> QualificationOutcome:
        decision_no = str(decision_no or "").strip()
        decision = str(decision or "").strip().upper()
        reason_code = str(reason_code or "").strip()
        reason = str(reason or "").strip()
        if not decision_no:
            raise TitleQualificationError(
                "TITLE_QUALIFICATION_DECISION_NO_REQUIRED",
                "decision_no is required",
            )
        if decision not in self._TARGET_STATUS:
            raise TitleQualificationError(
                "TITLE_QUALIFICATION_DECISION_INVALID",
                f"unsupported qualification decision: {decision}",
            )
        if decision in {
            TitleQualificationDecision.Decision.RETURNED,
            TitleQualificationDecision.Decision.REJECTED,
        } and not reason:
            raise TitleQualificationError(
                "TITLE_QUALIFICATION_REASON_REQUIRED",
                "returned/rejected qualification decisions require a reason",
            )

        idempotent = self._existing_idempotent(
            decision_no=decision_no,
            case_id=case_id,
            decision=decision,
            reason_code=reason_code,
            reason=reason,
        )
        if idempotent is not None:
            return idempotent

        case = (
            TitleApplicationCase.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, id=case_id)
            .first()
        )
        if case is None:
            raise TitleQualificationError("TITLE_CASE_NOT_FOUND", "application case not found")
        if case.status != TitleApplicationCase.Status.SUBMITTED:
            raise TitleQualificationError(
                "TITLE_QUALIFICATION_INVALID_STATE",
                f"qualification review requires SUBMITTED case, got {case.status}",
            )

        last_attempt = (
            TitleQualificationDecision.objects.filter(
                tenant_id=self.tenant_id,
                application_case_id=case.id,
            ).aggregate(max_attempt=Max("attempt_no"))["max_attempt"]
            or 0
        )
        review = TitleQualificationDecision.objects.create(
            tenant_id=self.tenant_id,
            decision_no=decision_no,
            application_case_id=case.id,
            attempt_no=last_attempt + 1,
            decision=decision,
            reason_code=reason_code,
            reason=reason,
            decided_by=self.actor_user_id,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        case.status = self._TARGET_STATUS[decision]
        case.updated_by = self.actor_user_id
        case.save(update_fields=["status", "updated_by", "updated_at"])
        return QualificationOutcome(review, case, True)
