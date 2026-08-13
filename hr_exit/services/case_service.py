"""HR16 exit-case workflow before the employment termination effect.

Approval, handover and settlement are workflow facts only. They never end an
employment relationship. HANDOVER -> SETTLEMENT is fail-closed on the HR16
handover checklist; only ``ExitEffectService`` may cross from SETTLEMENT to an
HR03 employment effect.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from django.db import transaction

from hr_exit.models import ExitCase


class ExitCaseError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


_UNSET = object()


@dataclass(frozen=True)
class ExitCaseInput:
    case_no: str
    person_id: object
    employment_relationship_id: object
    exit_type: str
    requested_date: Optional[date] = None
    last_working_date: Optional[date] = None
    planned_employment_end_date: Optional[date] = None
    planned_access_end_at: Optional[datetime] = None


@dataclass(frozen=True)
class ExitCasePatch:
    requested_date: object = _UNSET
    last_working_date: object = _UNSET
    planned_employment_end_date: object = _UNSET
    planned_access_end_at: object = _UNSET


class ExitCaseService:
    OPEN_STATUSES = frozenset(
        {
            ExitCase.Status.DRAFT,
            ExitCase.Status.SUBMITTED,
            ExitCase.Status.RETURNED,
            ExitCase.Status.APPROVED,
            ExitCase.Status.HANDOVER,
            ExitCase.Status.SETTLEMENT,
            ExitCase.Status.EFFECT_PENDING,
        }
    )

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

    def _lock_relationship(self, relationship_id, person_id):
        from hr_staff.constants import RelationshipStatus
        from hr_staff.models import HrEmploymentRelationship

        relationship = (
            HrEmploymentRelationship.objects.select_for_update()
            .select_related("staff_id__person_id")
            .filter(id=relationship_id, tenant_id=self.tenant_id)
            .first()
        )
        if relationship is None:
            raise ExitCaseError(
                "EXIT_RELATIONSHIP_NOT_FOUND",
                "HR03 employment relationship not found inside tenant",
            )
        if str(relationship.staff_id.person_id_id) != str(person_id):
            raise ExitCaseError(
                "EXIT_RELATIONSHIP_PERSON_MISMATCH",
                "exit person does not own the referenced HR03 relationship",
            )
        if relationship.status != RelationshipStatus.ACTIVE:
            raise ExitCaseError(
                "EXIT_RELATIONSHIP_NOT_ACTIVE",
                "only an ACTIVE HR03 employment relationship can open an exit case",
            )
        return relationship

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

    @staticmethod
    def _validate_plan_dates(last_working_date, planned_employment_end_date) -> None:
        if (
            last_working_date
            and planned_employment_end_date
            and last_working_date > planned_employment_end_date
        ):
            raise ExitCaseError(
                "EXIT_WORKING_DATE_AFTER_END_DATE",
                "last working date cannot be later than planned employment end date",
            )

    @transaction.atomic
    def create_draft(self, payload: ExitCaseInput) -> ExitCase:
        case_no = str(payload.case_no or "").strip()
        exit_type = str(payload.exit_type or "").strip().upper()
        if not case_no:
            raise ExitCaseError("EXIT_CASE_NO_REQUIRED", "case_no is required")
        if exit_type not in ExitCase.ExitType.values:
            raise ExitCaseError("EXIT_TYPE_INVALID", f"unsupported exit_type: {exit_type}")
        if not payload.person_id:
            raise ExitCaseError("EXIT_PERSON_REQUIRED", "person_id is required")
        if not payload.employment_relationship_id:
            raise ExitCaseError(
                "EXIT_RELATIONSHIP_REQUIRED", "employment_relationship_id is required"
            )
        self._validate_plan_dates(
            payload.last_working_date,
            payload.planned_employment_end_date,
        )

        self._lock_relationship(payload.employment_relationship_id, payload.person_id)
        existing = (
            ExitCase.objects.select_for_update()
            .filter(
                tenant_id=self.tenant_id,
                employment_relationship_id=payload.employment_relationship_id,
                status__in=self.OPEN_STATUSES,
            )
            .first()
        )
        if existing is not None:
            raise ExitCaseError(
                "EXIT_CASE_ALREADY_OPEN",
                "an open exit case already exists for this employment relationship",
            )
        if ExitCase.objects.filter(tenant_id=self.tenant_id, case_no=case_no).exists():
            raise ExitCaseError(
                "EXIT_CASE_NO_CONFLICT", "case_no already exists inside tenant"
            )

        return ExitCase.objects.create(
            tenant_id=self.tenant_id,
            case_no=case_no,
            person_id=payload.person_id,
            employment_relationship_id=payload.employment_relationship_id,
            exit_type=exit_type,
            requested_date=payload.requested_date,
            last_working_date=payload.last_working_date,
            planned_employment_end_date=payload.planned_employment_end_date,
            planned_access_end_at=payload.planned_access_end_at,
            status=ExitCase.Status.DRAFT,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )

    @transaction.atomic
    def update_draft(self, case_id, patch: ExitCasePatch) -> ExitCase:
        case = self._lock_case(case_id)
        if case.status not in {ExitCase.Status.DRAFT, ExitCase.Status.RETURNED}:
            raise ExitCaseError(
                "EXIT_CASE_NOT_EDITABLE",
                f"case status {case.status} cannot be amended",
            )

        requested_date = (
            case.requested_date if patch.requested_date is _UNSET else patch.requested_date
        )
        last_working_date = (
            case.last_working_date
            if patch.last_working_date is _UNSET
            else patch.last_working_date
        )
        planned_end = (
            case.planned_employment_end_date
            if patch.planned_employment_end_date is _UNSET
            else patch.planned_employment_end_date
        )
        planned_access_end = (
            case.planned_access_end_at
            if patch.planned_access_end_at is _UNSET
            else patch.planned_access_end_at
        )
        self._validate_plan_dates(last_working_date, planned_end)

        updates = []
        values = {
            "requested_date": requested_date,
            "last_working_date": last_working_date,
            "planned_employment_end_date": planned_end,
            "planned_access_end_at": planned_access_end,
        }
        for field, value in values.items():
            if getattr(case, field) != value:
                setattr(case, field, value)
                updates.append(field)
        if not updates:
            return case
        case.updated_by = self.actor_user_id
        updates.extend(["updated_by", "updated_at"])
        case.save(update_fields=updates)
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
        self._validate_plan_dates(case.last_working_date, case.planned_employment_end_date)
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
        if case.status != ExitCase.Status.HANDOVER:
            raise ExitCaseError(
                "EXIT_CASE_INVALID_STATE",
                f"cannot transition exit case from {case.status} to {ExitCase.Status.SETTLEMENT}",
            )

        from hr_exit.services.handover_service import (
            ExitHandoverError,
            ExitHandoverService,
        )

        try:
            ExitHandoverService(
                self.tenant_id,
                actor_user_id=self.actor_user_id,
            ).assert_ready_for_settlement(case.id)
        except ExitHandoverError as exc:
            raise ExitCaseError(exc.code, str(exc)) from exc

        return self._transition(
            case,
            allowed_from={ExitCase.Status.HANDOVER},
            target=ExitCase.Status.SETTLEMENT,
        )
