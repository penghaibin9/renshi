"""HR16 retirement fact authority.

Retirement is a specialization of an already-effective HR16 exit.  A retirement
fact can only be materialized after the core HR03 employment termination has
succeeded; approval or a planned retirement date is never enough.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from django.db import transaction

from hr_exit.models import ExitCase, ExitFact, RetirementFact


class RetirementFactError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class RetirementFactResult:
    fact: RetirementFact
    created: bool


class RetirementFactService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise RetirementFactError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    def _lock_exit_fact(self, exit_fact_id) -> ExitFact:
        fact = (
            ExitFact.objects.select_for_update()
            .filter(id=exit_fact_id, tenant_id=self.tenant_id)
            .first()
        )
        if fact is None:
            raise RetirementFactError("EXIT_FACT_NOT_FOUND", "exit fact not found inside tenant")
        if fact.status != ExitFact.Status.EFFECTIVE:
            raise RetirementFactError(
                "RETIREMENT_EXIT_NOT_EFFECTIVE",
                "retirement fact requires an EFFECTIVE exit fact",
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
                status=ExitFact.Status.EFFECTIVE,
            )
            .first()
        )
        if existing_for_exit is not None:
            raise RetirementFactError(
                "RETIREMENT_FACT_ALREADY_EXISTS",
                "an effective retirement fact already exists for this exit fact",
            )

        retirement = RetirementFact.objects.create(
            tenant_id=self.tenant_id,
            fact_no=fact_no,
            person_id=exit_fact.person_id,
            exit_fact_id=exit_fact.id,
            retirement_type=retirement_type,
            statutory_date=statutory_date,
            effective_date=exit_fact.employment_end_date,
            pension_processing_status=RetirementFact.PensionStatus.NOT_STARTED,
            status=ExitFact.Status.EFFECTIVE,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        return RetirementFactResult(retirement, True)

    @transaction.atomic
    def set_pension_status(self, retirement_fact_id, *, status: str) -> RetirementFact:
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
        if order[status] < order[fact.pension_processing_status]:
            raise RetirementFactError(
                "RETIREMENT_PENSION_STATUS_REGRESSION",
                "pension processing status cannot move backwards",
            )
        if fact.pension_processing_status == status:
            return fact
        fact.pension_processing_status = status
        fact.updated_by = self.actor_user_id
        fact.save(
            update_fields=[
                "pension_processing_status",
                "updated_by",
                "updated_at",
            ]
        )
        return fact
