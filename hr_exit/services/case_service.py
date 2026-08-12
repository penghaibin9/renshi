"""HR16 exit-case workflow before the employment termination effect.

Approval, handover and settlement are workflow facts only.  They never end an
employment relationship.  The last transition owned here is HANDOVER ->
SETTLEMENT; only ``ExitEffectService`` may cross from SETTLEMENT to an HR03
employment effect.
"""

from __future__ import annotations

from typing import Optional

from django.db import transaction

from hr_exit.models import ExitCase


class ExitCaseError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class ExitCaseService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise ExitCaseError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id

    def _lock_case(self, case_id) -> ExitCase:
        case = (
            ExitCase.objects.select_for_update()
            .filter(id=case_id, tenant_id=self.tenant_id)
            .first()
        )
        if case is None:
            raise ExitCaseError("EXIT_CASE_NOT_FOUND", "exit case not found")
        return case

    def _transition(self, case: ExitCase, *, allowed_from, target: str) -> ExitCase:
        if case.status not in allowed_from:
            raise ExitCaseError(
                "EXIT_CASE_INVALID_STATE",
                f"cannot transition exit case from {case.status} to {target}",
            )
        case.status = target
        case.updated_by = self.actor_user_id
        case.save(update_fields=["status", "updated_by", "updated_at"])
        return case

    @transaction.atomic
    def submit(self, case_id) -> ExitCase:
        case = self._lock_case(case_id)
        if case.requested_date is None:
            raise ExitCaseError(
                "EXIT_REQUESTED_DATE_REQUIRED",
                "requested_date is required before submission",
            )
        return self._transition(
            case,
            allowed_from={ExitCase.Status.DRAFT, ExitCase.Status.RETURNED},
            target=ExitCase.Status.SUBMITTED,
        )

    @transaction.atomic
    def return_for_correction(self, case_id) -> ExitCase:
        case = self._lock_case(case_id)
        return self._transition(
            case,
            allowed_from={ExitCase.Status.SUBMITTED},
            target=ExitCase.Status.RETURNED,
        )

    @transaction.atomic
    def approve(self, case_id) -> ExitCase:
        case = self._lock_case(case_id)
        if case.planned_employment_end_date is None:
            raise ExitCaseError(
                "EXIT_EMPLOYMENT_END_DATE_REQUIRED",
                "planned employment end date is required before approval",
            )
        if case.last_working_date and case.last_working_date > case.planned_employment_end_date:
            raise ExitCaseError(
                "EXIT_WORKING_DATE_AFTER_END_DATE",
                "last working date cannot be later than planned employment end date",
            )
        return self._transition(
            case,
            allowed_from={ExitCase.Status.SUBMITTED},
            target=ExitCase.Status.APPROVED,
        )

    @transaction.atomic
    def reject(self, case_id) -> ExitCase:
        case = self._lock_case(case_id)
        return self._transition(
            case,
            allowed_from={ExitCase.Status.SUBMITTED},
            target=ExitCase.Status.REJECTED,
        )

    @transaction.atomic
    def cancel_before_approval(self, case_id) -> ExitCase:
        case = self._lock_case(case_id)
        return self._transition(
            case,
            allowed_from={
                ExitCase.Status.DRAFT,
                ExitCase.Status.RETURNED,
                ExitCase.Status.SUBMITTED,
            },
            target=ExitCase.Status.CANCELLED,
        )

    @transaction.atomic
    def begin_handover(self, case_id) -> ExitCase:
        case = self._lock_case(case_id)
        return self._transition(
            case,
            allowed_from={ExitCase.Status.APPROVED},
            target=ExitCase.Status.HANDOVER,
        )

    @transaction.atomic
    def begin_settlement(self, case_id) -> ExitCase:
        case = self._lock_case(case_id)
        return self._transition(
            case,
            allowed_from={ExitCase.Status.HANDOVER},
            target=ExitCase.Status.SETTLEMENT,
        )
