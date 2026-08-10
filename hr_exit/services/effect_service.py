"""HR16 core exit-effect orchestration.

Approval, handover, settlement and account operations are not employment facts.
The exit becomes effective only after HR03 ends the referenced employment
relationship.  HR16 therefore persists a recoverable ``EFFECT_PENDING`` fact,
executes the HR03 Authority write in a savepoint, and exposes ``EFFECTIVE`` only
when that write succeeds.

This is deliberately only the core HR03 participant of the larger HR16 saga.
IAM, HR14, HR15, archive and other downstream effects must be tracked
separately; they are not collapsed into a fake ``all_done`` flag here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from django.db import transaction

from hr_exit.models import ExitCase, ExitFact


class ExitEffectError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ExitEffectResult:
    fact: ExitFact
    effective: bool
    error: str = ""


class ExitEffectService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise ExitEffectError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id

    def _lock_case(self, case_id) -> ExitCase:
        case = (
            ExitCase.objects.select_for_update()
            .filter(id=case_id, tenant_id=self.tenant_id)
            .first()
        )
        if case is None:
            raise ExitEffectError("EXIT_CASE_NOT_FOUND", "exit case not found")
        if case.status not in (
            ExitCase.Status.SETTLEMENT,
            ExitCase.Status.EFFECT_PENDING,
        ):
            raise ExitEffectError(
                "EXIT_CASE_INVALID_STATE",
                f"case status {case.status} cannot enter employment effect",
            )
        if case.planned_employment_end_date is None:
            raise ExitEffectError(
                "EXIT_EMPLOYMENT_END_DATE_REQUIRED",
                "planned employment end date is required before effect",
            )
        return case

    def _lock_relationship(self, case: ExitCase):
        from hr_staff.models import HrEmploymentRelationship

        relationship = (
            HrEmploymentRelationship.objects.select_for_update()
            .select_related("staff_id__person_id")
            .filter(
                id=case.employment_relationship_id,
                tenant_id=self.tenant_id,
            )
            .first()
        )
        if relationship is None:
            raise ExitEffectError(
                "EXIT_RELATIONSHIP_NOT_FOUND",
                "HR03 employment relationship not found inside tenant",
            )
        if str(relationship.staff_id.person_id_id) != str(case.person_id):
            raise ExitEffectError(
                "EXIT_RELATIONSHIP_PERSON_MISMATCH",
                "case person does not own the referenced HR03 relationship",
            )
        return relationship

    def _get_or_create_pending_fact(
        self,
        *,
        case: ExitCase,
        fact_no: str,
    ) -> ExitFact:
        fact = (
            ExitFact.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, fact_no=fact_no)
            .first()
        )
        if fact is not None:
            expected = {
                "source_case_id": str(case.id),
                "person_id": str(case.person_id),
                "employment_relationship_id": str(case.employment_relationship_id),
                "exit_type": case.exit_type,
                "employment_end_date": case.planned_employment_end_date,
                "last_working_date": case.last_working_date,
            }
            observed = {
                "source_case_id": str(fact.source_case_id),
                "person_id": str(fact.person_id),
                "employment_relationship_id": str(fact.employment_relationship_id),
                "exit_type": fact.exit_type,
                "employment_end_date": fact.employment_end_date,
                "last_working_date": fact.last_working_date,
            }
            if observed != expected:
                raise ExitEffectError(
                    "EXIT_EFFECT_IDEMPOTENCY_CONFLICT",
                    "fact_no already belongs to a different exit payload",
                )
            if fact.status == ExitFact.Status.EFFECTIVE:
                return fact
            if fact.status != ExitFact.Status.EFFECT_PENDING:
                raise ExitEffectError(
                    "EXIT_FACT_INVALID_STATE",
                    f"fact status {fact.status} cannot be retried",
                )
            return fact

        return ExitFact.objects.create(
            tenant_id=self.tenant_id,
            fact_no=fact_no,
            person_id=case.person_id,
            employment_relationship_id=case.employment_relationship_id,
            source_case_id=case.id,
            exit_type=case.exit_type,
            employment_end_date=case.planned_employment_end_date,
            last_working_date=case.last_working_date,
            access_end_at=case.planned_access_end_at,
            status=ExitFact.Status.EFFECT_PENDING,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )

    @transaction.atomic
    def apply(self, *, case_id, fact_no: str, reason_code: str = "") -> ExitEffectResult:
        """Apply the core HR03 employment termination and publish ExitFact."""
        case = self._lock_case(case_id)
        relationship = self._lock_relationship(case)
        fact = self._get_or_create_pending_fact(case=case, fact_no=fact_no)

        if fact.status == ExitFact.Status.EFFECTIVE:
            return ExitEffectResult(fact=fact, effective=True)

        case.status = ExitCase.Status.EFFECT_PENDING
        case.updated_by = self.actor_user_id
        case.save(update_fields=["status", "updated_by", "updated_at"])

        fact.status = ExitFact.Status.EFFECT_PENDING
        fact.last_effect_error = ""
        fact.updated_by = self.actor_user_id
        fact.save(
            update_fields=["status", "last_effect_error", "updated_by", "updated_at"]
        )

        try:
            # Keep the HR03 Authority write inside a savepoint.  If it fails,
            # HR16 retains the pending case/fact for reconciliation instead of
            # fabricating EFFECTIVE or leaving a half-written relationship.
            with transaction.atomic():
                from hr_staff.services.employment_service import EmploymentService

                ended_relationship = EmploymentService(
                    self.tenant_id,
                    audit_actor_user_id=self.actor_user_id,
                ).end_relationship(
                    relationship_id=relationship.id,
                    effective_to=case.planned_employment_end_date,
                    reason_code=reason_code or case.exit_type,
                    source_business_type="HR16_EXIT",
                    source_business_id=str(fact.id),
                )
        except Exception as exc:
            fact.last_effect_error = str(exc)[:2000]
            fact.save(update_fields=["last_effect_error", "updated_at"])
            return ExitEffectResult(
                fact=fact,
                effective=False,
                error=fact.last_effect_error,
            )

        fact.status = ExitFact.Status.EFFECTIVE
        fact.effect_receipt_json = {
            "hr03RelationshipId": str(ended_relationship.id),
            "hr03RelationshipStatus": str(ended_relationship.status),
            "employmentEndDate": case.planned_employment_end_date.isoformat(),
        }
        fact.last_effect_error = ""
        fact.updated_by = self.actor_user_id
        fact.save(
            update_fields=[
                "status",
                "effect_receipt_json",
                "last_effect_error",
                "updated_by",
                "updated_at",
            ]
        )

        case.status = ExitCase.Status.EFFECTIVE
        case.updated_by = self.actor_user_id
        case.save(update_fields=["status", "updated_by", "updated_at"])
        return ExitEffectResult(fact=fact, effective=True)
