"""HR14 formal appointment effect orchestration.

A collective/publicity result is not yet an effective personnel fact.  HR14
first records an ``EFFECT_PENDING`` result tied to the exact HR02 reservation,
then asks HR03 to switch the primary assignment.  Only when the HR03 write and
HR02 reservation commit succeed in the same savepoint may HR14 expose the
result as ``EFFECTIVE``.

If the provider write fails, the pending fact and reservation receipt remain so
reconciliation can retry.  No caller should infer appointment effectiveness
from a FINAL/publicity decision alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from hr_appointment.models import AppointmentApplicationCase, PositionAppointmentFact


class AppointmentEffectError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class AppointmentEffectResult:
    fact: PositionAppointmentFact
    effective: bool
    error: str = ""


class AppointmentEffectService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise AppointmentEffectError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id

    def _lock_case(self, case_id) -> AppointmentApplicationCase:
        case = (
            AppointmentApplicationCase.objects.select_for_update()
            .filter(id=case_id, tenant_id=self.tenant_id)
            .first()
        )
        if case is None:
            raise AppointmentEffectError("APPOINTMENT_CASE_NOT_FOUND", "appointment case not found")
        if case.status not in (
            AppointmentApplicationCase.Status.PUBLICITY,
            AppointmentApplicationCase.Status.EFFECT_PENDING,
        ):
            raise AppointmentEffectError(
                "APPOINTMENT_CASE_INVALID_STATE",
                f"case status {case.status} cannot enter appointment effect",
            )
        return case

    def _get_or_create_pending_fact(
        self,
        *,
        case: AppointmentApplicationCase,
        appointment_no: str,
        reservation_id: int,
        effective_from: date,
        level_code: str,
    ) -> PositionAppointmentFact:
        fact = (
            PositionAppointmentFact.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, appointment_no=appointment_no)
            .first()
        )
        if fact is not None:
            if (
                str(fact.application_case_id) != str(case.id)
                or str(fact.person_id) != str(case.person_id)
                or fact.position_instance_id != case.position_instance_id
                or fact.reservation_id != reservation_id
                or fact.effective_from != effective_from
            ):
                raise AppointmentEffectError(
                    "APPOINTMENT_EFFECT_IDEMPOTENCY_CONFLICT",
                    "appointment_no already belongs to a different effect payload",
                )
            if fact.status == PositionAppointmentFact.Status.EFFECTIVE:
                return fact
            if fact.status != PositionAppointmentFact.Status.EFFECT_PENDING:
                raise AppointmentEffectError(
                    "APPOINTMENT_RESULT_INVALID_STATE",
                    f"fact status {fact.status} cannot be retried",
                )
            return fact

        return PositionAppointmentFact.objects.create(
            tenant_id=self.tenant_id,
            appointment_no=appointment_no,
            person_id=case.person_id,
            position_instance_id=case.position_instance_id,
            application_case_id=case.id,
            reservation_id=reservation_id,
            level_code=level_code,
            effective_from=effective_from,
            status=PositionAppointmentFact.Status.EFFECT_PENDING,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )

    def _lock_capacity_receipt(self, case, reservation_id):
        from hr_structure.models import HrPosition, HrPositionReservation

        reservation = (
            HrPositionReservation.objects.select_for_update()
            .filter(id=reservation_id, tenant_id=self.tenant_id)
            .first()
        )
        if reservation is None:
            raise AppointmentEffectError(
                "APPOINTMENT_RESERVATION_NOT_FOUND", "HR02 reservation not found"
            )
        if reservation.status != HrPositionReservation.Status.HELD:
            raise AppointmentEffectError(
                "APPOINTMENT_RESERVATION_INVALID_STATE",
                f"reservation status {reservation.status} is not HELD",
            )
        if reservation.expires_at <= timezone.now():
            raise AppointmentEffectError(
                "APPOINTMENT_RESERVATION_EXPIRED", "HR02 reservation has expired"
            )
        if reservation.position_id_id != case.position_instance_id:
            raise AppointmentEffectError(
                "APPOINTMENT_RESERVATION_POSITION_MISMATCH",
                "reservation does not belong to the appointed position",
            )
        if reservation.source_domain and reservation.source_domain != "HR14":
            raise AppointmentEffectError(
                "APPOINTMENT_RESERVATION_SOURCE_MISMATCH",
                "reservation is not owned by HR14",
            )

        # Capacity-sensitive writers serialize on the HR02 position row.
        position = (
            HrPosition.objects.select_for_update()
            .filter(
                id=case.position_instance_id,
                tenant_id=self.tenant_id,
                lifecycle_status=HrPosition.LifecycleStatus.ACTIVE,
            )
            .first()
        )
        if position is None:
            raise AppointmentEffectError(
                "APPOINTMENT_POSITION_NOT_ACTIVE", "target HR02 position is not active"
            )
        return reservation, position

    def _active_staff_relationship(self, person_id, as_of: date):
        from hr_staff.constants import RelationshipStatus
        from hr_staff.models import HrEmploymentRelationship, HrStaffMaster

        staff = (
            HrStaffMaster.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, person_id_id=person_id)
            .first()
        )
        if staff is None:
            raise AppointmentEffectError(
                "APPOINTMENT_STAFF_NOT_FOUND", "HR03 staff master not found"
            )

        relationship = (
            HrEmploymentRelationship.objects.select_for_update()
            .filter(
                tenant_id=self.tenant_id,
                staff_id=staff,
                status=RelationshipStatus.ACTIVE,
                effective_from__lte=as_of,
            )
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=as_of))
            .order_by("effective_from", "id")
            .first()
        )
        if relationship is None:
            raise AppointmentEffectError(
                "APPOINTMENT_ACTIVE_RELATIONSHIP_REQUIRED",
                "no active HR03 employment relationship exists on effective date",
            )
        return staff, relationship

    @transaction.atomic
    def apply(
        self,
        *,
        case_id,
        appointment_no: str,
        reservation_id: int,
        effective_from: date,
        level_code: str = "",
    ) -> AppointmentEffectResult:
        """Create/retry a formal appointment and apply it to HR03 atomically."""
        case = self._lock_case(case_id)
        fact = self._get_or_create_pending_fact(
            case=case,
            appointment_no=appointment_no,
            reservation_id=reservation_id,
            effective_from=effective_from,
            level_code=level_code or case.requested_level_code,
        )
        if fact.status == PositionAppointmentFact.Status.EFFECTIVE:
            return AppointmentEffectResult(fact=fact, effective=True)

        reservation, position = self._lock_capacity_receipt(case, reservation_id)
        staff, relationship = self._active_staff_relationship(case.person_id, effective_from)

        # Persist the recoverable business state before invoking provider writes.
        case.status = AppointmentApplicationCase.Status.EFFECT_PENDING
        case.updated_by = self.actor_user_id
        case.save(update_fields=["status", "updated_by", "updated_at"])
        fact.status = PositionAppointmentFact.Status.EFFECT_PENDING
        fact.last_effect_error = ""
        fact.updated_by = self.actor_user_id
        fact.save(
            update_fields=["status", "last_effect_error", "updated_by", "updated_at"]
        )

        try:
            # One inner savepoint covers both Authority write and reservation
            # consumption. If either fails, HR03 must not be half-effective.
            with transaction.atomic():
                from hr_staff.services.assignment_service import AssignmentService
                from hr_structure.scope import Hr02Scope
                from hr_structure.services.position import PositionService

                assignment = AssignmentService(
                    self.tenant_id, audit_actor_user_id=self.actor_user_id
                ).switch_primary(
                    employment_relationship_id=relationship,
                    effective_from=effective_from,
                    organization_id=position.organization_id,
                    position_id=position,
                    post_catalog_id=position.post_catalog_version_id,
                    source_business_type="HR14_APPOINTMENT",
                    source_business_id=str(fact.id),
                )
                PositionService(
                    Hr02Scope("SCHOOL", tenant_id=self.tenant_id),
                    actor=str(self.actor_user_id or ""),
                ).commit(reservation.id)
        except Exception as exc:
            # Do not re-raise: the outer transaction must retain EFFECT_PENDING
            # and the receipt so a reconciliation worker can retry later.
            fact.last_effect_error = str(exc)[:2000]
            fact.save(update_fields=["last_effect_error", "updated_at"])
            return AppointmentEffectResult(
                fact=fact,
                effective=False,
                error=fact.last_effect_error,
            )

        fact.status = PositionAppointmentFact.Status.EFFECTIVE
        fact.effect_receipt_json = {
            "hr03AssignmentId": str(assignment.id),
            "hr03RelationshipId": str(relationship.id),
            "hr02ReservationId": reservation.id,
            "hr02PositionId": position.id,
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
        case.status = AppointmentApplicationCase.Status.EFFECTIVE
        case.updated_by = self.actor_user_id
        case.save(update_fields=["status", "updated_by", "updated_at"])
        return AppointmentEffectResult(fact=fact, effective=True)
