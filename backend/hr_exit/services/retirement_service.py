"""HR16 retirement fact authority.

Retirement is a specialization of an already-effective HR16 exit.  A retirement
fact can only be materialized after the core HR03 employment termination has
succeeded; approval or a planned retirement date is never enough.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from django.db import transaction
from django.utils import timezone

from horilla.hr_event_service import emit_registered_event
from hr_exit.archive_registry import (
    EVENT_RETIREMENT_FACT_EFFECTIVE,
    EVENT_RETIREMENT_FACT_REVISED,
    EVENT_RETIREMENT_FACT_REVOKED,
    EVENT_RETIREMENT_PENSION_STATUS_CHANGED,
)
from hr_exit.models import (
    ExitCase,
    ExitFact,
    RetirementFact,
    RetirementPensionTransition,
)


class RetirementFactError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class RetirementFactResult:
    fact: RetirementFact
    created: bool


class RetirementFactService:
    def __init__(
        self,
        tenant_id: int,
        actor_user_id: Optional[int] = None,
        correlation_id: str = "",
    ):
        if not tenant_id:
            raise RetirementFactError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id
        self.correlation_id = str(correlation_id or "")

    def _lock_exit_fact(self, exit_fact_id) -> ExitFact:
        fact = (
            ExitFact.objects.select_for_update()
            .filter(id=exit_fact_id, tenant_id=self.tenant_id)
            .first()
        )
        if fact is None:
            raise RetirementFactError("EXIT_FACT_NOT_FOUND", "exit fact not found inside tenant")
        if fact.status not in {
            ExitFact.Status.EFFECTIVE,
            ExitFact.Status.REVISED,
            ExitFact.Status.REVOKED,
        }:
            raise RetirementFactError(
                "RETIREMENT_EXIT_NOT_EFFECTIVE",
                "retirement fact requires a sealed formal exit fact",
            )
        if fact.exit_type != ExitCase.ExitType.RETIREMENT:
            raise RetirementFactError(
                "RETIREMENT_EXIT_TYPE_REQUIRED",
                "retirement fact can only be created from a RETIREMENT exit",
            )
        return fact

    @transaction.atomic
    def finalize(
        self,
        *,
        exit_fact_id,
        fact_no: str,
        retirement_type: str,
        statutory_date=None,
        evidence_ref: str = "",
    ) -> RetirementFactResult:
        fact_no = str(fact_no or "").strip()
        retirement_type = str(retirement_type or "").strip().upper()
        if not fact_no:
            raise RetirementFactError("RETIREMENT_FACT_NO_REQUIRED", "fact_no is required")
        if len(fact_no) > 64:
            raise RetirementFactError(
                "RETIREMENT_FACT_NO_INVALID", "fact_no exceeds 64 characters"
            )
        if not retirement_type:
            raise RetirementFactError(
                "RETIREMENT_TYPE_REQUIRED", "retirement_type is required"
            )
        if len(retirement_type) > 32:
            raise RetirementFactError(
                "RETIREMENT_TYPE_INVALID", "retirement_type exceeds 32 characters"
            )

        exit_fact = self._lock_exit_fact(exit_fact_id)
        predecessor = None
        if exit_fact.supersedes_fact_id:
            predecessor = (
                RetirementFact.objects.select_for_update()
                .filter(
                    tenant_id=self.tenant_id,
                    exit_fact_id=exit_fact.supersedes_fact_id,
                )
                .first()
            )
            if predecessor is None:
                raise RetirementFactError(
                    "RETIREMENT_PREDECESSOR_NOT_FOUND",
                    "finalize the predecessor ExitFact retirement specialization first",
                )
            if RetirementFact.objects.filter(
                tenant_id=self.tenant_id,
                supersedes_fact_id=predecessor.id,
            ).exists():
                raise RetirementFactError(
                    "RETIREMENT_FACT_ALREADY_SUPERSEDED",
                    "retirement specialization already follows this ExitFact successor",
                )
        evidence_ref = str(
            evidence_ref or exit_fact.evidence_ref or f"exitfact://{exit_fact.id}"
        ).strip()
        if len(evidence_ref) > 256:
            raise RetirementFactError(
                "RETIREMENT_EVIDENCE_INVALID", "evidence_ref exceeds 256 characters"
            )

        existing_by_no = (
            RetirementFact.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, fact_no=fact_no)
            .first()
        )
        if existing_by_no is not None:
            if (
                str(existing_by_no.exit_fact_id) != str(exit_fact.id)
                or str(existing_by_no.person_id) != str(exit_fact.person_id)
                or existing_by_no.retirement_type != retirement_type
                or existing_by_no.statutory_date != statutory_date
                or existing_by_no.effective_date != exit_fact.employment_end_date
                or existing_by_no.evidence_ref != evidence_ref
                or existing_by_no.status != exit_fact.status
                or existing_by_no.supersedes_fact_id
                != (predecessor.id if predecessor else None)
            ):
                raise RetirementFactError(
                    "RETIREMENT_FACT_IDEMPOTENCY_CONFLICT",
                    "fact_no already belongs to a different retirement payload",
                )
            return RetirementFactResult(existing_by_no, False)

        existing_for_exit = (
            RetirementFact.objects.select_for_update()
            .filter(
                tenant_id=self.tenant_id,
                exit_fact_id=exit_fact.id,
                status__in=(
                    ExitFact.Status.EFFECTIVE,
                    ExitFact.Status.REVISED,
                    ExitFact.Status.REVOKED,
                ),
            )
            .first()
        )
        if existing_for_exit is not None:
            raise RetirementFactError(
                "RETIREMENT_FACT_ALREADY_EXISTS",
                "an effective retirement fact already exists for this exit fact",
            )

        retirement = RetirementFact(
            tenant_id=self.tenant_id,
            fact_no=fact_no,
            person_id=exit_fact.person_id,
            exit_fact_id=exit_fact.id,
            retirement_type=retirement_type,
            statutory_date=statutory_date,
            effective_date=exit_fact.employment_end_date,
            pension_processing_status=RetirementFact.PensionStatus.NOT_STARTED,
            status=exit_fact.status,
            supersedes_fact_id=predecessor.id if predecessor else None,
            evidence_ref=evidence_ref,
            sealed_at=timezone.now(),
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        retirement.content_hash = retirement.calculate_content_hash()
        retirement.save(force_insert=True)
        event_name = {
            ExitFact.Status.EFFECTIVE: EVENT_RETIREMENT_FACT_EFFECTIVE,
            ExitFact.Status.REVISED: EVENT_RETIREMENT_FACT_REVISED,
            ExitFact.Status.REVOKED: EVENT_RETIREMENT_FACT_REVOKED,
        }[retirement.status]
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=event_name,
            correlation_id=self.correlation_id,
            payload={
                "retirementFactId": str(retirement.id),
                "exitFactId": str(retirement.exit_fact_id),
                "personId": str(retirement.person_id),
                "factNo": retirement.fact_no,
                "effectiveDate": retirement.effective_date.isoformat(),
                "evidenceRef": retirement.evidence_ref,
                "contentHash": retirement.content_hash,
                "sealedAt": retirement.sealed_at.isoformat(),
            },
        )
        return RetirementFactResult(retirement, True)

    @transaction.atomic
    def set_pension_status(
        self,
        retirement_fact_id,
        *,
        status: str,
        evidence_ref: str = "",
    ) -> RetirementFact:
        status = str(status or "").strip().upper()
        if status not in RetirementFact.PensionStatus.values:
            raise RetirementFactError(
                "RETIREMENT_PENSION_STATUS_INVALID",
                f"unsupported pension status: {status}",
            )
        fact = (
            RetirementFact.objects.select_for_update()
            .filter(id=retirement_fact_id, tenant_id=self.tenant_id)
            .first()
        )
        if fact is None:
            raise RetirementFactError(
                "RETIREMENT_FACT_NOT_FOUND", "retirement fact not found inside tenant"
            )
        order = {
            RetirementFact.PensionStatus.NOT_STARTED: 0,
            RetirementFact.PensionStatus.IN_PROGRESS: 1,
            RetirementFact.PensionStatus.COMPLETED: 2,
        }
        current = fact.pension_processing_status
        if order[status] < order[current]:
            raise RetirementFactError(
                "RETIREMENT_PENSION_STATUS_REGRESSION",
                "pension processing status cannot move backwards",
            )
        if current == status:
            return fact
        if order[status] != order[current] + 1:
            raise RetirementFactError(
                "RETIREMENT_PENSION_STATUS_SKIP",
                "pension processing status must advance exactly one state",
            )
        evidence_ref = str(
            evidence_ref
            or f"retirementfact://{fact.id}/pension/{status.lower()}"
        ).strip()
        if len(evidence_ref) > 256:
            raise RetirementFactError(
                "RETIREMENT_PENSION_EVIDENCE_INVALID",
                "pension progress evidence_ref exceeds 256 characters",
            )

        sealed_at = timezone.now()
        transition = RetirementPensionTransition(
            tenant_id=self.tenant_id,
            retirement_fact_id=fact.id,
            from_status=current,
            to_status=status,
            evidence_ref=evidence_ref,
            sealed_at=sealed_at,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        transition.content_hash = transition.calculate_content_hash()
        transition.save(force_insert=True)
        fact.pension_processing_status = status
        fact.updated_by = self.actor_user_id
        fact.save(
            update_fields=[
                "pension_processing_status",
                "updated_by",
                "updated_at",
            ]
        )
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=EVENT_RETIREMENT_PENSION_STATUS_CHANGED,
            correlation_id=self.correlation_id,
            payload={
                "retirementFactId": str(fact.id),
                "personId": str(fact.person_id),
                "fromStatus": current,
                "toStatus": status,
                "evidenceRef": evidence_ref,
                "transitionId": str(transition.id),
                "contentHash": transition.content_hash,
                "sealedAt": sealed_at.isoformat(),
            },
        )
        return fact
