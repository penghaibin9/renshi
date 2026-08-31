"""HR14 appointment application lifecycle authority service.

This service owns the applicant/review workflow only. It deliberately stops at
PUBLICITY; making the appointment effective still requires
``AppointmentEffectService`` and a valid HR02 capacity reservation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from django.db import transaction

from hr_appointment.models import (
    AppointmentApplicationCase,
    AppointmentBatch,
    AppointmentPositionSupplySnapshot,
)


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

    def _lock_case(self, case_id, *, actor_person_id=None) -> AppointmentApplicationCase:
        case = (
            AppointmentApplicationCase.objects.select_for_update()
            .filter(id=case_id, tenant_id=self.tenant_id)
            .first()
        )
        if case is None:
            raise AppointmentApplicationError(
                "APPOINTMENT_CASE_NOT_FOUND", "appointment application case not found"
            )
        if actor_person_id is not None and str(case.person_id) != str(actor_person_id):
            raise AppointmentApplicationError(
                "APPOINTMENT_APPLICATION_SELF_ONLY",
                "applicant permission can only operate the current account's own application",
            )
        return case

    def _lock_batch(self, batch_no: str) -> AppointmentBatch:
        batch = (
            AppointmentBatch.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, batch_no=batch_no)
            .first()
        )
        if batch is None:
            raise AppointmentApplicationError(
                "APPOINTMENT_BATCH_NOT_FOUND", "appointment batch not found"
            )
        return batch

    def _lock_open_batch(self, batch_no: str) -> AppointmentBatch:
        batch = self._lock_batch(batch_no)
        if batch.status != AppointmentBatch.Status.APPLICATION_OPEN:
            raise AppointmentApplicationError(
                "APPOINTMENT_BATCH_NOT_OPEN",
                f"batch status {batch.status} does not accept new applications",
            )
        return batch

    def _require_batch_phase(self, case: AppointmentApplicationCase, allowed, code: str):
        batch = self._lock_batch(case.batch_no)
        if batch.status not in allowed:
            raise AppointmentApplicationError(
                code,
                f"case action is not allowed while batch status is {batch.status}",
            )
        return batch

    def _position_supply(self, batch: AppointmentBatch, position_instance_id: int):
        supply = (
            AppointmentPositionSupplySnapshot.objects.filter(
                tenant_id=self.tenant_id,
                batch=batch,
                position_instance_id=position_instance_id,
            )
            .first()
        )
        if supply is None:
            raise AppointmentApplicationError(
                "APPOINTMENT_POSITION_NOT_IN_FROZEN_SUPPLY",
                "target position is not part of the frozen appointment batch supply",
            )
        return supply

    def _require_population_member(self, batch: AppointmentBatch, person_id):
        from hr_appointment.services.population_service import (
            AppointmentPopulationError,
            AppointmentPopulationService,
        )

        try:
            return AppointmentPopulationService(
                self.tenant_id,
                actor_user_id=self.actor_user_id,
            ).require_member(batch=batch, person_id=person_id)
        except AppointmentPopulationError as exc:
            raise AppointmentApplicationError(exc.code, str(exc)) from exc

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
        case_no = str(payload.case_no or "").strip()
        batch_no = str(payload.batch_no or "").strip()
        if not case_no or not batch_no:
            raise AppointmentApplicationError(
                "APPOINTMENT_CASE_IDENTITY_REQUIRED", "case_no and batch_no are required"
            )
        if not payload.position_instance_id:
            raise AppointmentApplicationError(
                "APPOINTMENT_POSITION_REQUIRED", "position_instance_id is required"
            )

        batch = self._lock_open_batch(batch_no)
        if str(payload.policy_version_id) != str(batch.policy_version_id):
            raise AppointmentApplicationError(
                "APPOINTMENT_POLICY_VERSION_MISMATCH",
                "application policy version must match the frozen appointment batch policy",
            )
        self._require_population_member(batch, payload.person_id)
        supply = self._position_supply(batch, payload.position_instance_id)
        requested_level = str(payload.requested_level_code or "").strip()
        frozen_level = str(supply.level_code or "").strip()
        if frozen_level and requested_level and requested_level != frozen_level:
            raise AppointmentApplicationError(
                "APPOINTMENT_APPLICATION_LEVEL_MISMATCH",
                "requested appointment level does not match the frozen position supply",
            )
        requested_level = frozen_level or requested_level

        return AppointmentApplicationCase.objects.create(
            tenant_id=self.tenant_id,
            case_no=case_no,
            person_id=payload.person_id,
            policy_version_id=batch.policy_version_id,
            position_instance_id=payload.position_instance_id,
            batch_no=batch.batch_no,
            requested_level_code=requested_level,
            status=AppointmentApplicationCase.Status.DRAFT,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )

    @transaction.atomic
    def submit(self, case_id, *, actor_person_id=None) -> AppointmentApplicationCase:
        case = self._lock_case(case_id, actor_person_id=actor_person_id)
        if case.status == AppointmentApplicationCase.Status.DRAFT:
            self._require_batch_phase(
                case,
                {AppointmentBatch.Status.APPLICATION_OPEN},
                "APPOINTMENT_BATCH_NOT_OPEN",
            )
        elif case.status == AppointmentApplicationCase.Status.RETURNED:
            self._require_batch_phase(
                case,
                {
                    AppointmentBatch.Status.APPLICATION_OPEN,
                    AppointmentBatch.Status.ELIGIBILITY_REVIEW,
                },
                "APPOINTMENT_APPLICATION_CORRECTION_WINDOW_CLOSED",
            )
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
        self._require_batch_phase(
            case,
            {AppointmentBatch.Status.ELIGIBILITY_REVIEW},
            "APPOINTMENT_ELIGIBILITY_REVIEW_NOT_OPEN",
        )
        return self._transition(
            case,
            allowed_from={AppointmentApplicationCase.Status.SUBMITTED},
            target=AppointmentApplicationCase.Status.RETURNED,
        )

    @transaction.atomic
    def pass_eligibility(self, case_id) -> AppointmentApplicationCase:
        case = self._lock_case(case_id)
        self._require_batch_phase(
            case,
            {AppointmentBatch.Status.ELIGIBILITY_REVIEW},
            "APPOINTMENT_ELIGIBILITY_REVIEW_NOT_OPEN",
        )
        return self._transition(
            case,
            allowed_from={AppointmentApplicationCase.Status.SUBMITTED},
            target=AppointmentApplicationCase.Status.ELIGIBLE,
        )

    @transaction.atomic
    def reject_eligibility(self, case_id) -> AppointmentApplicationCase:
        case = self._lock_case(case_id)
        self._require_batch_phase(
            case,
            {AppointmentBatch.Status.ELIGIBILITY_REVIEW},
            "APPOINTMENT_ELIGIBILITY_REVIEW_NOT_OPEN",
        )
        return self._transition(
            case,
            allowed_from={AppointmentApplicationCase.Status.SUBMITTED},
            target=AppointmentApplicationCase.Status.REJECTED,
        )

    @transaction.atomic
    def withdraw(self, case_id, *, actor_person_id=None) -> AppointmentApplicationCase:
        case = self._lock_case(case_id, actor_person_id=actor_person_id)
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
        self._require_batch_phase(
            case,
            {AppointmentBatch.Status.REVIEWING},
            "APPOINTMENT_REVIEW_NOT_OPEN",
        )
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
