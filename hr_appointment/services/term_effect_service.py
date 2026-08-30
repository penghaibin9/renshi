"""Apply approved HR14 renewal/change decisions to formal appointment facts.

Approval is intentionally separate from effect.  This service is the only
term-governance path that may create a successor ``PositionAppointmentFact``.
It preserves the old fact, closes its effective range at the successor boundary,
and records ``supersedes_fact_id`` on the new fact.

HR03 is changed only when the primary assignment itself changes or ends:
- renewal / promotion / downgrade: verify the same HR03 primary assignment;
- transfer: atomically switch HR03 primary assignment and commit an HR02 HELD
  reservation owned by the HR14 change;
- termination: close the current HR03 primary assignment;
- correction: fail closed until an explicit correction authority payload exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from django.db import transaction
from django.utils import timezone

from hr_appointment.models import PositionAppointmentFact
from hr_appointment.term_models import (
    AppointmentChangeCase,
    AppointmentRenewalCase,
    AppointmentTerm,
)


class AppointmentTermEffectError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class AppointmentTermEffectResult:
    fact: PositionAppointmentFact
    term: Optional[AppointmentTerm]
    applied: bool
    error: str = ""


class AppointmentTermEffectService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise AppointmentTermEffectError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    def _lock_term(self, term_id) -> AppointmentTerm:
        term = (
            AppointmentTerm.objects.select_for_update()
            .filter(id=term_id, tenant_id=self.tenant_id)
            .first()
        )
        if term is None:
            raise AppointmentTermEffectError("APPOINTMENT_TERM_NOT_FOUND", "appointment term not found")
        return term

    def _lock_source_fact(self, term: AppointmentTerm) -> PositionAppointmentFact:
        fact = (
            PositionAppointmentFact.objects.select_for_update()
            .filter(id=term.appointment_fact_id, tenant_id=self.tenant_id)
            .first()
        )
        if fact is None:
            raise AppointmentTermEffectError(
                "APPOINTMENT_FACT_NOT_FOUND", "source appointment fact not found"
            )
        if str(fact.person_id) != str(term.person_id):
            raise AppointmentTermEffectError(
                "APPOINTMENT_TERM_FACT_MISMATCH", "term and appointment fact person mismatch"
            )
        return fact

    def _current_primary_assignment(self, term: AppointmentTerm, as_of: date):
        from hr_staff.models import HrStaffMaster
        from hr_staff.services.effective_dated_query_service import EffectiveDatedQueryService

        staff = (
            HrStaffMaster.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, person_id_id=term.person_id)
            .first()
        )
        if staff is None:
            raise AppointmentTermEffectError(
                "APPOINTMENT_STAFF_NOT_FOUND", "HR03 staff master not found"
            )
        assignment = EffectiveDatedQueryService(self.tenant_id).primary_assignment_as_of(
            staff.id, as_of
        )
        if assignment is None:
            raise AppointmentTermEffectError(
                "APPOINTMENT_PRIMARY_ASSIGNMENT_REQUIRED",
                "no HR03 primary assignment exists on the effect date",
            )
        if assignment.position_id_id != term.position_instance_id:
            raise AppointmentTermEffectError(
                "APPOINTMENT_PRIMARY_ASSIGNMENT_MISMATCH",
                "HR03 primary assignment no longer matches the source appointment position",
            )
        return assignment

    def _target_position(self, position_id):
        from hr_structure.models import HrPosition

        position = (
            HrPosition.objects.select_for_update()
            .filter(
                id=position_id,
                tenant_id=self.tenant_id,
                lifecycle_status=HrPosition.LifecycleStatus.ACTIVE,
            )
            .first()
        )
        if position is None:
            raise AppointmentTermEffectError(
                "APPOINTMENT_POSITION_NOT_ACTIVE", "target HR02 position is not active"
            )
        return position

    def _transfer_reservation(self, *, change: AppointmentChangeCase, reservation_id, position):
        from hr_structure.models import HrPositionReservation

        if not reservation_id:
            raise AppointmentTermEffectError(
                "APPOINTMENT_TRANSFER_RESERVATION_REQUIRED",
                "transfer effect requires an HR02 HELD reservation",
            )
        reservation = (
            HrPositionReservation.objects.select_for_update()
            .filter(id=reservation_id, tenant_id=self.tenant_id)
            .first()
        )
        if reservation is None:
            raise AppointmentTermEffectError(
                "APPOINTMENT_RESERVATION_NOT_FOUND", "HR02 reservation not found"
            )
        if reservation.status != HrPositionReservation.Status.HELD:
            raise AppointmentTermEffectError(
                "APPOINTMENT_RESERVATION_INVALID_STATE",
                f"reservation status {reservation.status} is not HELD",
            )
        if reservation.expires_at <= timezone.now():
            raise AppointmentTermEffectError(
                "APPOINTMENT_RESERVATION_EXPIRED", "HR02 reservation has expired"
            )
        if reservation.position_id_id != position.id:
            raise AppointmentTermEffectError(
                "APPOINTMENT_RESERVATION_POSITION_MISMATCH",
                "reservation does not belong to the target position",
            )
        if reservation.source_domain != "HR14":
            raise AppointmentTermEffectError(
                "APPOINTMENT_RESERVATION_SOURCE_MISMATCH",
                "reservation is not owned by HR14",
            )
        if reservation.source_business_id not in {str(change.id), change.change_no}:
            raise AppointmentTermEffectError(
                "APPOINTMENT_RESERVATION_SOURCE_MISMATCH",
                "reservation is not owned by this appointment change",
            )
        return reservation

    def _get_or_create_pending_fact(
        self,
        *,
        source_fact: PositionAppointmentFact,
        appointment_no: str,
        position_instance_id: int,
        level_code: str,
        effective_from: date,
        effective_to: Optional[date],
        reservation_id=None,
        source_kind: str,
        source_id,
    ) -> PositionAppointmentFact:
        appointment_no = (appointment_no or "").strip()
        if not appointment_no:
            raise AppointmentTermEffectError(
                "APPOINTMENT_SUCCESSOR_NO_REQUIRED", "successor appointment_no is required"
            )
        if effective_to is not None and effective_to <= effective_from:
            raise AppointmentTermEffectError(
                "APPOINTMENT_SUCCESSOR_RANGE_INVALID",
                "successor effective_to must be later than effective_from",
            )
        if effective_from <= source_fact.effective_from:
            raise AppointmentTermEffectError(
                "APPOINTMENT_SUCCESSOR_DATE_INVALID",
                "successor must start after the source appointment fact",
            )

        existing = (
            PositionAppointmentFact.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, appointment_no=appointment_no)
            .first()
        )
        if existing is not None:
            expected = {
                "person_id": source_fact.person_id,
                "position_instance_id": position_instance_id,
                "application_case_id": source_fact.application_case_id,
                "reservation_id": reservation_id,
                "level_code": level_code,
                "effective_from": effective_from,
                "effective_to": effective_to,
                "supersedes_fact_id": source_fact.id,
            }
            if any(getattr(existing, field) != value for field, value in expected.items()):
                raise AppointmentTermEffectError(
                    "APPOINTMENT_TERM_EFFECT_IDEMPOTENCY_CONFLICT",
                    "appointment_no already exists with a different successor payload",
                )
            return existing

        if PositionAppointmentFact.objects.select_for_update().filter(
            tenant_id=self.tenant_id,
            supersedes_fact_id=source_fact.id,
        ).exists():
            raise AppointmentTermEffectError(
                "APPOINTMENT_FACT_ALREADY_SUPERSEDED",
                "source appointment fact already has a successor",
            )

        return PositionAppointmentFact.objects.create(
            tenant_id=self.tenant_id,
            appointment_no=appointment_no,
            person_id=source_fact.person_id,
            position_instance_id=position_instance_id,
            application_case_id=source_fact.application_case_id,
            reservation_id=reservation_id,
            level_code=level_code,
            effective_from=effective_from,
            effective_to=effective_to,
            status=PositionAppointmentFact.Status.EFFECT_PENDING,
            fact_kind=PositionAppointmentFact.FactKind.TERM_SUCCESSOR,
            idempotency_key=f"hr14-term:{source_kind}:{source_id}",
            effect_receipt_json={
                "sourceKind": source_kind,
                "sourceId": str(source_id),
                "sourceFactId": str(source_fact.id),
            },
            supersedes_fact_id=source_fact.id,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )

    def _close_source_fact_at(self, source_fact: PositionAppointmentFact, boundary: date) -> None:
        if boundary <= source_fact.effective_from:
            raise AppointmentTermEffectError(
                "APPOINTMENT_SUCCESSOR_DATE_INVALID",
                "successor boundary must be later than the source appointment start",
            )
        if source_fact.effective_to is not None and source_fact.effective_to < boundary:
            raise AppointmentTermEffectError(
                "APPOINTMENT_SOURCE_FACT_ALREADY_ENDED",
                "source appointment fact ended before the successor boundary",
            )
        # The sealed source remains untouched.  The successor's effective_from
        # is the authoritative chain boundary; historical as-of reads select
        # the applicable chain node instead of shortening the old row.

    def _create_successor_term(
        self,
        *,
        source_term: AppointmentTerm,
        fact: PositionAppointmentFact,
        term_no: str,
        effective_from: date,
        effective_to: Optional[date],
        position_instance_id: int,
        level_code: str,
        renewal_due_at: Optional[date],
        source_kind: str,
        source_id,
    ) -> AppointmentTerm:
        term_no = (term_no or "").strip()
        if not term_no:
            raise AppointmentTermEffectError(
                "APPOINTMENT_SUCCESSOR_TERM_NO_REQUIRED", "successor term_no is required"
            )
        if effective_to is not None and effective_to <= effective_from:
            raise AppointmentTermEffectError(
                "APPOINTMENT_SUCCESSOR_TERM_RANGE_INVALID",
                "successor term effective_to must be later than effective_from",
            )
        if renewal_due_at is not None and effective_to is not None and renewal_due_at > effective_to:
            raise AppointmentTermEffectError(
                "APPOINTMENT_RENEWAL_DUE_INVALID",
                "renewal_due_at cannot be later than successor term end",
            )

        existing = (
            AppointmentTerm.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, appointment_fact_id=fact.id)
            .first()
        )
        if existing is not None:
            expected = {
                "term_no": term_no,
                "person_id": source_term.person_id,
                "position_instance_id": position_instance_id,
                "level_code": level_code,
                "policy_version_id": source_term.policy_version_id,
                "effective_from": effective_from,
                "effective_to": effective_to,
                "renewal_due_at": renewal_due_at,
                "supersedes_term_id": source_term.id,
            }
            if any(getattr(existing, field) != value for field, value in expected.items()):
                raise AppointmentTermEffectError(
                    "APPOINTMENT_TERM_EFFECT_IDEMPOTENCY_CONFLICT",
                    "successor appointment already has a different term payload",
                )
            return existing

        if AppointmentTerm.objects.select_for_update().filter(
            tenant_id=self.tenant_id,
            supersedes_term_id=source_term.id,
        ).exists():
            raise AppointmentTermEffectError(
                "APPOINTMENT_TERM_ALREADY_SUPERSEDED",
                "source appointment term already has a successor",
            )
        if AppointmentTerm.objects.filter(tenant_id=self.tenant_id, term_no=term_no).exists():
            raise AppointmentTermEffectError(
                "APPOINTMENT_TERM_EFFECT_IDEMPOTENCY_CONFLICT",
                "term_no already belongs to another appointment term",
            )

        return AppointmentTerm.objects.create(
            tenant_id=self.tenant_id,
            term_no=term_no,
            appointment_fact_id=fact.id,
            person_id=source_term.person_id,
            position_instance_id=position_instance_id,
            level_code=level_code,
            policy_version_id=source_term.policy_version_id,
            effective_from=effective_from,
            effective_to=effective_to,
            renewal_due_at=renewal_due_at,
            supersedes_term_id=source_term.id,
            source_snapshot_json={
                "sourceKind": source_kind,
                "sourceId": str(source_id),
                "sourceTermId": str(source_term.id),
                "sourceAppointmentFactId": str(source_term.appointment_fact_id),
            },
            status=AppointmentTerm.Status.ACTIVE,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )

    def _finalize_fact(self, fact, *, status: str, receipt: dict) -> None:
        pending_receipt = dict(fact.effect_receipt_json or {})
        fact.last_effect_error = ""
        fact.status = status
        fact.effect_receipt_json = receipt
        if not self.actor_user_id:
            raise AppointmentTermEffectError(
                "APPOINTMENT_FACT_PUBLISH_ACTOR_REQUIRED",
                "term effect requires an authenticated actor",
            )
        from hr_appointment.authority_registry import (
            EVENT_FACT_EFFECTIVE,
            EVENT_FACT_ENDED,
        )
        from hr_appointment.services.fact_authority_service import emit_fact_event

        source_kind = str(pending_receipt.get("sourceKind", "TERM_EFFECT"))
        source_id = str(pending_receipt.get("sourceId", ""))
        fact.seal(
            status=status,
            actor_user_id=self.actor_user_id,
            authority_receipt={
                "permissionCode": "hr.appointment.term",
                "authorityRef": f"{source_kind}:{source_id}",
                "actorUserId": self.actor_user_id,
                "evidence": dict(receipt),
            },
            effect_receipt=receipt,
        )
        emit_fact_event(
            fact=fact,
            event_name=(
                EVENT_FACT_ENDED
                if status == PositionAppointmentFact.Status.ENDED
                else EVENT_FACT_EFFECTIVE
            ),
        )

    def _record_effect_failure(self, fact, exc: Exception) -> AppointmentTermEffectResult:
        fact.last_effect_error = str(exc)[:2000]
        fact.updated_by = self.actor_user_id
        fact.save(update_fields=["last_effect_error", "updated_by", "updated_at"])
        return AppointmentTermEffectResult(
            fact=fact,
            term=None,
            applied=False,
            error=fact.last_effect_error,
        )

    def _mark_source_term(self, term: AppointmentTerm, status: str) -> None:
        term.status = status
        term.version += 1
        term.updated_by = self.actor_user_id
        term.save(update_fields=["status", "version", "updated_by", "updated_at"])

    @transaction.atomic
    def apply_renewal(
        self,
        renewal_id,
        *,
        appointment_no: str,
        successor_term_no: str,
        renewal_due_at: Optional[date] = None,
    ) -> AppointmentTermEffectResult:
        renewal = (
            AppointmentRenewalCase.objects.select_for_update()
            .filter(id=renewal_id, tenant_id=self.tenant_id)
            .first()
        )
        if renewal is None:
            raise AppointmentTermEffectError(
                "APPOINTMENT_RENEWAL_NOT_FOUND", "renewal case not found"
            )
        if renewal.status == AppointmentRenewalCase.Status.APPLIED:
            if not renewal.successor_fact_id or not renewal.successor_term_id:
                raise AppointmentTermEffectError(
                    "APPOINTMENT_RENEWAL_APPLIED_INCOMPLETE",
                    "applied renewal is missing successor authority references",
                )
            fact = PositionAppointmentFact.objects.get(
                id=renewal.successor_fact_id, tenant_id=self.tenant_id
            )
            term = AppointmentTerm.objects.get(
                id=renewal.successor_term_id, tenant_id=self.tenant_id
            )
            return AppointmentTermEffectResult(fact=fact, term=term, applied=True)
        if renewal.status != AppointmentRenewalCase.Status.APPROVED:
            raise AppointmentTermEffectError(
                "APPOINTMENT_RENEWAL_NOT_APPROVED",
                "only an APPROVED renewal can be applied",
            )
        if renewal.route == AppointmentRenewalCase.Route.REAPPOINTMENT:
            raise AppointmentTermEffectError(
                "APPOINTMENT_REAPPOINTMENT_REQUIRED",
                "reappointment route must create a new competition result before effect",
            )

        source_term = self._lock_term(renewal.source_term_id)
        if source_term.status != AppointmentTerm.Status.RENEWAL_IN_PROGRESS:
            raise AppointmentTermEffectError(
                "APPOINTMENT_RENEWAL_TERM_STATE_INVALID",
                f"source term status {source_term.status} cannot apply renewal",
            )
        source_fact = self._lock_source_fact(source_term)
        assignment = self._current_primary_assignment(
            source_term, renewal.proposed_effective_from
        )
        level_code = renewal.proposed_level_code or source_term.level_code
        fact = self._get_or_create_pending_fact(
            source_fact=source_fact,
            appointment_no=appointment_no,
            position_instance_id=source_term.position_instance_id,
            level_code=level_code,
            effective_from=renewal.proposed_effective_from,
            effective_to=renewal.proposed_effective_to,
            source_kind="RENEWAL",
            source_id=renewal.id,
        )

        self._close_source_fact_at(source_fact, renewal.proposed_effective_from)
        receipt = {
            "hr14RenewalId": str(renewal.id),
            "sourceFactId": str(source_fact.id),
            "hr03AssignmentId": str(assignment.id),
            "hr03Effect": "VERIFIED_UNCHANGED_POSITION",
        }
        self._finalize_fact(
            fact, status=PositionAppointmentFact.Status.EFFECTIVE, receipt=receipt
        )
        successor_term = self._create_successor_term(
            source_term=source_term,
            fact=fact,
            term_no=successor_term_no,
            effective_from=renewal.proposed_effective_from,
            effective_to=renewal.proposed_effective_to,
            position_instance_id=source_term.position_instance_id,
            level_code=level_code,
            renewal_due_at=renewal_due_at,
            source_kind="RENEWAL",
            source_id=renewal.id,
        )
        self._mark_source_term(source_term, AppointmentTerm.Status.RENEWED)
        renewal.status = AppointmentRenewalCase.Status.APPLIED
        renewal.successor_fact_id = fact.id
        renewal.successor_term_id = successor_term.id
        renewal.updated_by = self.actor_user_id
        renewal.save(
            update_fields=[
                "status",
                "successor_fact_id",
                "successor_term_id",
                "updated_by",
                "updated_at",
            ]
        )
        return AppointmentTermEffectResult(
            fact=fact, term=successor_term, applied=True
        )

    @transaction.atomic
    def apply_change(
        self,
        change_id,
        *,
        appointment_no: str,
        successor_term_no: str = "",
        reservation_id=None,
        renewal_due_at: Optional[date] = None,
    ) -> AppointmentTermEffectResult:
        change = (
            AppointmentChangeCase.objects.select_for_update()
            .filter(id=change_id, tenant_id=self.tenant_id)
            .first()
        )
        if change is None:
            raise AppointmentTermEffectError(
                "APPOINTMENT_CHANGE_NOT_FOUND", "appointment change not found"
            )
        if change.status == AppointmentChangeCase.Status.APPLIED:
            if not change.successor_fact_id:
                raise AppointmentTermEffectError(
                    "APPOINTMENT_CHANGE_APPLIED_INCOMPLETE",
                    "applied change is missing successor appointment fact",
                )
            fact = PositionAppointmentFact.objects.get(
                id=change.successor_fact_id, tenant_id=self.tenant_id
            )
            term = None
            if change.successor_term_id:
                term = AppointmentTerm.objects.get(
                    id=change.successor_term_id, tenant_id=self.tenant_id
                )
            return AppointmentTermEffectResult(fact=fact, term=term, applied=True)
        if change.status != AppointmentChangeCase.Status.APPROVED:
            raise AppointmentTermEffectError(
                "APPOINTMENT_CHANGE_NOT_APPROVED",
                "only an APPROVED appointment change can be applied",
            )
        if change.change_type == AppointmentChangeCase.ChangeType.CORRECTION:
            raise AppointmentTermEffectError(
                "APPOINTMENT_CORRECTION_EFFECT_AUTHORITY_REQUIRED",
                "formal correction requires an explicit correction authority payload",
            )

        source_term = self._lock_term(change.source_term_id)
        if source_term.status not in {
            AppointmentTerm.Status.ACTIVE,
            AppointmentTerm.Status.EXPIRING,
        }:
            raise AppointmentTermEffectError(
                "APPOINTMENT_CHANGE_TERM_STATE_INVALID",
                f"source term status {source_term.status} cannot apply change",
            )
        if source_term.effective_to is not None and change.effective_date >= source_term.effective_to:
            raise AppointmentTermEffectError(
                "APPOINTMENT_CHANGE_OUTSIDE_TERM",
                "change effective date must be inside the source term",
            )

        source_fact = self._lock_source_fact(source_term)
        current_assignment = self._current_primary_assignment(
            source_term, change.effective_date
        )
        target_position_id = source_term.position_instance_id
        target_level_code = source_term.level_code
        successor_effective_to = source_term.effective_to

        if change.change_type in {
            AppointmentChangeCase.ChangeType.PROMOTION,
            AppointmentChangeCase.ChangeType.DOWNGRADE,
        }:
            target_level_code = change.target_level_code
        elif change.change_type == AppointmentChangeCase.ChangeType.TRANSFER:
            target_position_id = change.target_position_instance_id
            target_level_code = change.target_level_code or source_term.level_code
        elif change.change_type == AppointmentChangeCase.ChangeType.TERMINATION:
            successor_effective_to = None

        fact = self._get_or_create_pending_fact(
            source_fact=source_fact,
            appointment_no=appointment_no,
            position_instance_id=target_position_id,
            level_code=target_level_code,
            effective_from=change.effective_date,
            effective_to=successor_effective_to,
            reservation_id=reservation_id
            if change.change_type == AppointmentChangeCase.ChangeType.TRANSFER
            else None,
            source_kind="TERM_CHANGE",
            source_id=change.id,
        )

        assignment = current_assignment
        reservation = None
        if change.change_type == AppointmentChangeCase.ChangeType.TRANSFER:
            target_position = self._target_position(target_position_id)
            reservation = self._transfer_reservation(
                change=change,
                reservation_id=reservation_id,
                position=target_position,
            )
            try:
                with transaction.atomic():
                    from hr_staff.services.assignment_service import AssignmentService
                    from hr_structure.scope import Hr02Scope
                    from hr_structure.services.position import PositionService

                    assignment = AssignmentService(
                        self.tenant_id, audit_actor_user_id=self.actor_user_id
                    ).switch_primary(
                        employment_relationship_id=current_assignment.employment_relationship_id,
                        effective_from=change.effective_date,
                        organization_id=target_position.organization_id,
                        position_id=target_position,
                        post_catalog_id=target_position.post_catalog_version_id,
                        source_business_type="HR14_APPOINTMENT",
                        source_business_id=str(fact.id),
                    )
                    PositionService(
                        Hr02Scope("SCHOOL", tenant_id=self.tenant_id),
                        actor=str(self.actor_user_id or ""),
                    ).commit(reservation.id)
            except Exception as exc:
                return self._record_effect_failure(fact, exc)
        elif change.change_type == AppointmentChangeCase.ChangeType.TERMINATION:
            try:
                with transaction.atomic():
                    from hr_staff.services.assignment_service import AssignmentService

                    assignment = AssignmentService(
                        self.tenant_id, audit_actor_user_id=self.actor_user_id
                    ).close_assignment(
                        assignment_id=current_assignment.id,
                        effective_to=change.effective_date,
                        reason_code="HR14_APPOINTMENT_TERMINATION",
                        source_business_type="HR14_APPOINTMENT",
                        source_business_id=str(fact.id),
                    )
            except Exception as exc:
                return self._record_effect_failure(fact, exc)

        self._close_source_fact_at(source_fact, change.effective_date)
        receipt = {
            "hr14ChangeId": str(change.id),
            "changeType": change.change_type,
            "sourceFactId": str(source_fact.id),
            "hr03AssignmentId": str(assignment.id),
            "hr03Effect": (
                "PRIMARY_SWITCHED"
                if change.change_type == AppointmentChangeCase.ChangeType.TRANSFER
                else "PRIMARY_CLOSED"
                if change.change_type == AppointmentChangeCase.ChangeType.TERMINATION
                else "VERIFIED_UNCHANGED_POSITION"
            ),
        }
        if reservation is not None:
            receipt["hr02ReservationId"] = reservation.id
            receipt["hr02PositionId"] = target_position_id

        final_status = (
            PositionAppointmentFact.Status.ENDED
            if change.change_type == AppointmentChangeCase.ChangeType.TERMINATION
            else PositionAppointmentFact.Status.EFFECTIVE
        )
        self._finalize_fact(fact, status=final_status, receipt=receipt)

        successor_term = None
        if change.change_type == AppointmentChangeCase.ChangeType.TERMINATION:
            self._mark_source_term(source_term, AppointmentTerm.Status.TERMINATED)
        else:
            successor_term = self._create_successor_term(
                source_term=source_term,
                fact=fact,
                term_no=successor_term_no,
                effective_from=change.effective_date,
                effective_to=source_term.effective_to,
                position_instance_id=target_position_id,
                level_code=target_level_code,
                renewal_due_at=renewal_due_at,
                source_kind="TERM_CHANGE",
                source_id=change.id,
            )
            self._mark_source_term(source_term, AppointmentTerm.Status.SUPERSEDED)

        change.status = AppointmentChangeCase.Status.APPLIED
        change.successor_fact_id = fact.id
        change.successor_term_id = successor_term.id if successor_term else None
        change.updated_by = self.actor_user_id
        change.save(
            update_fields=[
                "status",
                "successor_fact_id",
                "successor_term_id",
                "updated_by",
                "updated_at",
            ]
        )
        return AppointmentTermEffectResult(
            fact=fact,
            term=successor_term,
            applied=True,
        )
