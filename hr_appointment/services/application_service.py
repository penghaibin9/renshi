"""HR14 appointment application lifecycle authority service.

This service owns the applicant/review workflow only. It deliberately stops at
PUBLICITY; making the appointment effective still requires
``AppointmentEffectService`` and a valid HR02 capacity reservation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from django.db import transaction

from hr_appointment.models import AppointmentApplicationCase


class AppointmentApplicationError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class AppointmentApplicationInput:
    case_no: str
    person_id: object
    policy_version_id: object
    position_instance_id: int
    batch_no: str
    requested_level_code: str = ""


class AppointmentApplicationService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise AppointmentApplicationError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id

    def _lock_case(self, case_id) -> AppointmentApplicationCase:
        case = (
            AppointmentApplicationCase.objects.select_for_update()
            .filter(id=case_id, tenant_id=self.tenant_id)
            .first()
        )
        if case is None:
            raise AppointmentApplicationError(
                "APPOINTMENT_CASE_NOT_FOUND", "appointment application case not found"
            )
        return case

    def _transition(self, case: AppointmentApplicationCase, *, allowed_from, target: str):
        if case.status not in allowed_from:
            raise AppointmentApplicationError(
                "APPOINTMENT_CASE_INVALID_STATE",
                f"cannot transition appointment case from {case.status} to {target}",
            )
        case.status = target
        case.updated_by = self.actor_user_id
        case.save(update_fields=["status", "updated_by", "updated_at"])
        return case

    @transaction.atomic
    def create_draft(self, payload: AppointmentApplicationInput) -> AppointmentApplicationCase:
        if not payload.case_no.strip() or not payload.batch_no.strip():
            raise AppointmentApplicationError(
                "APPOINTMENT_CASE_IDENTITY_REQUIRED", "case_no and batch_no are required"
            )
        if not payload.position_instance_id:
            raise AppointmentApplicationError(
                "APPOINTMENT_POSITION_REQUIRED", "position_instance_id is required"
            )
        return AppointmentApplicationCase.objects.create(
            tenant_id=self.tenant_id,
            case_no=payload.case_no.strip(),
            person_id=payload.person_id,
            policy_version_id=payload.policy_version_id,
            position_instance_id=payload.position_instance_id,
            batch_no=payload.batch_no.strip(),
            requested_level_code=payload.requested_level_code.strip(),
            status=AppointmentApplicationCase.Status.DRAFT,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )

    @transaction.atomic
    def submit(self, case_id) -> AppointmentApplicationCase:
        case = self._lock_case(case_id)
        return self._transition(
            case,
            allowed_from={
                AppointmentApplicationCase.Status.DRAFT,
                AppointmentApplicationCase.Status.RETURNED,
            },
            target=AppointmentApplicationCase.Status.SUBMITTED,
        )

    @transaction.atomic
    def return_for_correction(self, case_id) -> AppointmentApplicationCase:
        case = self._lock_case(case_id)
        return self._transition(
            case,
            allowed_from={AppointmentApplicationCase.Status.SUBMITTED},
            target=AppointmentApplicationCase.Status.RETURNED,
        )

    @transaction.atomic
    def pass_eligibility(self, case_id) -> AppointmentApplicationCase:
        case = self._lock_case(case_id)
        return self._transition(
            case,
            allowed_from={AppointmentApplicationCase.Status.SUBMITTED},
            target=AppointmentApplicationCase.Status.ELIGIBLE,
        )

    @transaction.atomic
    def reject_eligibility(self, case_id) -> AppointmentApplicationCase:
        case = self._lock_case(case_id)
        return self._transition(
            case,
            allowed_from={AppointmentApplicationCase.Status.SUBMITTED},
            target=AppointmentApplicationCase.Status.REJECTED,
        )

    @transaction.atomic
    def withdraw(self, case_id) -> AppointmentApplicationCase:
        case = self._lock_case(case_id)
        return self._transition(
            case,
            allowed_from={
                AppointmentApplicationCase.Status.DRAFT,
                AppointmentApplicationCase.Status.RETURNED,
                AppointmentApplicationCase.Status.SUBMITTED,
            },
            target=AppointmentApplicationCase.Status.WITHDRAWN,
        )

    @transaction.atomic
    def start_review(self, case_id) -> AppointmentApplicationCase:
        case = self._lock_case(case_id)
        return self._transition(
            case,
            allowed_from={AppointmentApplicationCase.Status.ELIGIBLE},
            target=AppointmentApplicationCase.Status.UNDER_REVIEW,
        )

    @transaction.atomic
    def propose(self, case_id) -> AppointmentApplicationCase:
        case = self._lock_case(case_id)
        return self._transition(
            case,
            allowed_from={AppointmentApplicationCase.Status.UNDER_REVIEW},
            target=AppointmentApplicationCase.Status.PROPOSED,
        )

    @transaction.atomic
    def enter_publicity(self, case_id) -> AppointmentApplicationCase:
        case = self._lock_case(case_id)
        return self._transition(
            case,
            allowed_from={AppointmentApplicationCase.Status.PROPOSED},
            target=AppointmentApplicationCase.Status.PUBLICITY,
        )
