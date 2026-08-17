"""HR14 appointment-term governance services.

This service owns term/renewal/change workflow facts only. Approval is not an
HR03 assignment effect. Old appointment results and old terms are never edited
to simulate renewal, promotion, downgrade, transfer or termination.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from hr_appointment.models import AppointmentApplicationCase, PositionAppointmentFact
from hr_appointment.term_models import (
    AppointmentChangeCase,
    AppointmentRenewalCase,
    AppointmentTerm,
)


class AppointmentTermError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class RenewalDecision:
    renewal: AppointmentRenewalCase
    term: AppointmentTerm


@dataclass(frozen=True)
class ChangeDecision:
    change: AppointmentChangeCase
    term: AppointmentTerm


class AppointmentTermService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise AppointmentTermError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    def _lock_term(self, term_id) -> AppointmentTerm:
        term = (
            AppointmentTerm.objects.select_for_update()
            .filter(id=term_id, tenant_id=self.tenant_id)
            .first()
        )
        if term is None:
            raise AppointmentTermError("APPOINTMENT_TERM_NOT_FOUND", "appointment term not found")
        return term

    def _set_term_status(self, term: AppointmentTerm, status: str) -> None:
        term.status = status
        term.version += 1
        term.updated_by = self.actor_user_id
        term.save(update_fields=["status", "version", "updated_by", "updated_at"])

    @transaction.atomic
    def register_from_effective_fact(
        self,
        *,
        appointment_fact_id,
        term_no: str,
        effective_to: Optional[date] = None,
        renewal_due_at: Optional[date] = None,
    ) -> AppointmentTerm:
        fact = (
            PositionAppointmentFact.objects.select_for_update()
            .filter(id=appointment_fact_id, tenant_id=self.tenant_id)
            .first()
        )
        if fact is None:
            raise AppointmentTermError("APPOINTMENT_FACT_NOT_FOUND", "appointment fact not found")
        if fact.status != PositionAppointmentFact.Status.EFFECTIVE:
            raise AppointmentTermError(
                "APPOINTMENT_FACT_NOT_EFFECTIVE",
                "only an EFFECTIVE appointment fact can establish a term",
            )
        case = (
            AppointmentApplicationCase.objects.select_for_update()
            .filter(id=fact.application_case_id, tenant_id=self.tenant_id)
            .first()
        )
        if case is None:
            raise AppointmentTermError("APPOINTMENT_CASE_NOT_FOUND", "application case not found")

        term_no = (term_no or "").strip()
        if not term_no:
            raise AppointmentTermError("APPOINTMENT_TERM_NO_REQUIRED", "term_no is required")
        term_end = effective_to if effective_to is not None else fact.effective_to
        if term_end is not None and term_end <= fact.effective_from:
            raise AppointmentTermError(
                "APPOINTMENT_TERM_RANGE_INVALID",
                "term effective_to must be later than effective_from",
            )
        if renewal_due_at is not None and term_end is not None and renewal_due_at > term_end:
            raise AppointmentTermError(
                "APPOINTMENT_RENEWAL_DUE_INVALID",
                "renewal_due_at cannot be later than the term end",
            )

        existing = (
            AppointmentTerm.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, appointment_fact_id=fact.id)
            .first()
        )
        if existing is not None:
            expected = {
                "term_no": term_no,
                "person_id": fact.person_id,
                "position_instance_id": fact.position_instance_id,
                "level_code": fact.level_code,
                "policy_version_id": case.policy_version_id,
                "effective_from": fact.effective_from,
                "effective_to": term_end,
                "renewal_due_at": renewal_due_at,
            }
            if any(getattr(existing, key) != value for key, value in expected.items()):
                raise AppointmentTermError(
                    "APPOINTMENT_TERM_IDEMPOTENCY_CONFLICT",
                    "the effective appointment already has a different term payload",
                )
            return existing

        if AppointmentTerm.objects.filter(
            tenant_id=self.tenant_id, term_no=term_no
        ).exists():
            raise AppointmentTermError(
                "APPOINTMENT_TERM_IDEMPOTENCY_CONFLICT",
                "term_no already belongs to another appointment",
            )

        return AppointmentTerm.objects.create(
            tenant_id=self.tenant_id,
            term_no=term_no,
            appointment_fact_id=fact.id,
            person_id=fact.person_id,
            position_instance_id=fact.position_instance_id,
            level_code=fact.level_code,
            policy_version_id=case.policy_version_id,
            effective_from=fact.effective_from,
            effective_to=term_end,
            renewal_due_at=renewal_due_at,
            source_snapshot_json={
                "appointmentNo": fact.appointment_no,
                "applicationCaseId": str(fact.application_case_id),
                "effectReceipt": fact.effect_receipt_json,
            },
            status=AppointmentTerm.Status.ACTIVE,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )

    @transaction.atomic
    def mark_expiring(self, term_id) -> AppointmentTerm:
        term = self._lock_term(term_id)
        if term.status == AppointmentTerm.Status.EXPIRING:
            return term
        if term.status != AppointmentTerm.Status.ACTIVE:
            raise AppointmentTermError(
                "APPOINTMENT_TERM_INVALID_STATE",
                f"term status {term.status} cannot enter EXPIRING",
            )
        self._set_term_status(term, AppointmentTerm.Status.EXPIRING)
        return term

    @transaction.atomic
    def mark_expired(self, term_id, *, as_of: Optional[date] = None) -> AppointmentTerm:
        term = self._lock_term(term_id)
        clock = as_of or timezone.localdate()
        if term.status == AppointmentTerm.Status.EXPIRED:
            return term
        if term.status not in {AppointmentTerm.Status.ACTIVE, AppointmentTerm.Status.EXPIRING}:
            raise AppointmentTermError(
                "APPOINTMENT_TERM_INVALID_STATE",
                f"term status {term.status} cannot expire",
            )
        if term.effective_to is None or term.effective_to > clock:
            raise AppointmentTermError(
                "APPOINTMENT_TERM_NOT_DUE",
                "term cannot expire before effective_to",
            )
        self._set_term_status(term, AppointmentTerm.Status.EXPIRED)
        return term

    @transaction.atomic
    def open_renewal(
        self,
        *,
        term_id,
        renewal_no: str,
        route: str,
        proposed_effective_from: date,
        proposed_effective_to: Optional[date],
        proposed_level_code: str = "",
        hr12_term_result_ref: str = "",
    ) -> AppointmentRenewalCase:
        term = self._lock_term(term_id)
        if term.status not in {AppointmentTerm.Status.ACTIVE, AppointmentTerm.Status.EXPIRING}:
            raise AppointmentTermError(
                "APPOINTMENT_RENEWAL_INVALID_TERM_STATE",
                f"term status {term.status} cannot open renewal",
            )
        renewal_no = (renewal_no or "").strip()
        route = str(route or "").strip().upper()
        hr12_term_result_ref = (hr12_term_result_ref or "").strip()
        proposed_level_code = (proposed_level_code or term.level_code).strip()
        if not renewal_no:
            raise AppointmentTermError("APPOINTMENT_RENEWAL_NO_REQUIRED", "renewal_no is required")
        if route not in AppointmentRenewalCase.Route.values:
            raise AppointmentTermError("APPOINTMENT_RENEWAL_ROUTE_INVALID", "invalid renewal route")
        if (
            route != AppointmentRenewalCase.Route.REAPPOINTMENT
            and proposed_level_code != term.level_code
        ):
            raise AppointmentTermError(
                "APPOINTMENT_RENEWAL_LEVEL_CHANGE_REQUIRES_CHANGE_WORKFLOW",
                "renewal cannot change appointment level; use the formal appointment change workflow",
            )
        if proposed_effective_to is not None and proposed_effective_to <= proposed_effective_from:
            raise AppointmentTermError(
                "APPOINTMENT_RENEWAL_RANGE_INVALID",
                "proposed_effective_to must be later than proposed_effective_from",
            )
        if term.effective_to is not None and proposed_effective_from < term.effective_to:
            raise AppointmentTermError(
                "APPOINTMENT_RENEWAL_OVERLAP",
                "renewal must not silently overlap the old term",
            )
        if route == AppointmentRenewalCase.Route.TERM_ASSESSMENT and not hr12_term_result_ref:
            raise AppointmentTermError(
                "ASSESSMENT_REQUIRED_UNAVAILABLE",
                "HR12 final term assessment is required for this renewal route",
            )

        existing = (
            AppointmentRenewalCase.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, renewal_no=renewal_no)
            .first()
        )
        if existing is not None:
            expected = {
                "source_term_id": term.id,
                "policy_version_id": term.policy_version_id,
                "route": route,
                "hr12_term_result_ref": hr12_term_result_ref,
                "proposed_effective_from": proposed_effective_from,
                "proposed_effective_to": proposed_effective_to,
                "proposed_level_code": proposed_level_code,
            }
            if any(getattr(existing, key) != value for key, value in expected.items()):
                raise AppointmentTermError(
                    "APPOINTMENT_RENEWAL_IDEMPOTENCY_CONFLICT",
                    "renewal_no already exists with different content",
                )
            return existing

        blocking = AppointmentRenewalCase.objects.select_for_update().filter(
            tenant_id=self.tenant_id,
            source_term_id=term.id,
            status__in=[
                AppointmentRenewalCase.Status.READY,
                AppointmentRenewalCase.Status.APPROVED,
                AppointmentRenewalCase.Status.REAPPOINTMENT_REQUIRED,
            ],
        )
        if blocking.exists():
            raise AppointmentTermError(
                "APPOINTMENT_RENEWAL_ALREADY_OPEN",
                "a renewal workflow is already open for this term",
            )
        attempt_no = (
            AppointmentRenewalCase.objects.filter(
                tenant_id=self.tenant_id, source_term_id=term.id
            ).aggregate(value=Max("attempt_no"))["value"]
            or 0
        ) + 1
        status = (
            AppointmentRenewalCase.Status.REAPPOINTMENT_REQUIRED
            if route == AppointmentRenewalCase.Route.REAPPOINTMENT
            else AppointmentRenewalCase.Status.READY
        )
        renewal = AppointmentRenewalCase.objects.create(
            tenant_id=self.tenant_id,
            renewal_no=renewal_no,
            source_term_id=term.id,
            attempt_no=attempt_no,
            policy_version_id=term.policy_version_id,
            route=route,
            hr12_term_result_ref=hr12_term_result_ref,
            proposed_effective_from=proposed_effective_from,
            proposed_effective_to=proposed_effective_to,
            proposed_level_code=proposed_level_code,
            status=status,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        if status == AppointmentRenewalCase.Status.REAPPOINTMENT_REQUIRED:
            self._set_term_status(term, AppointmentTerm.Status.REAPPOINTMENT_REQUIRED)
        return renewal

    @transaction.atomic
    def decide_renewal(
        self,
        renewal_id,
        *,
        outcome: str,
        decision_snapshot=None,
    ) -> RenewalDecision:
        renewal = (
            AppointmentRenewalCase.objects.select_for_update()
            .filter(id=renewal_id, tenant_id=self.tenant_id)
            .first()
        )
        if renewal is None:
            raise AppointmentTermError("APPOINTMENT_RENEWAL_NOT_FOUND", "renewal case not found")
        term = self._lock_term(renewal.source_term_id)
        if renewal.status != AppointmentRenewalCase.Status.READY:
            raise AppointmentTermError(
                "APPOINTMENT_RENEWAL_INVALID_STATE",
                f"renewal status {renewal.status} cannot be decided",
            )
        outcome = str(outcome or "").strip().upper()
        allowed = {
            AppointmentRenewalCase.Status.APPROVED,
            AppointmentRenewalCase.Status.REJECTED,
            AppointmentRenewalCase.Status.CANCELLED,
            AppointmentRenewalCase.Status.REAPPOINTMENT_REQUIRED,
        }
        if outcome not in allowed:
            raise AppointmentTermError("APPOINTMENT_RENEWAL_OUTCOME_INVALID", "invalid renewal outcome")
        decision_snapshot = {} if decision_snapshot is None else decision_snapshot
        if not isinstance(decision_snapshot, dict):
            raise AppointmentTermError(
                "APPOINTMENT_RENEWAL_DECISION_INVALID",
                "decision_snapshot must be an object",
            )
        renewal.status = outcome
        renewal.decision_snapshot_json = decision_snapshot
        renewal.decided_by = self.actor_user_id
        renewal.decided_at = timezone.now()
        renewal.updated_by = self.actor_user_id
        renewal.save(
            update_fields=[
                "status",
                "decision_snapshot_json",
                "decided_by",
                "decided_at",
                "updated_by",
                "updated_at",
            ]
        )
        if outcome == AppointmentRenewalCase.Status.APPROVED:
            self._set_term_status(term, AppointmentTerm.Status.RENEWAL_IN_PROGRESS)
        elif outcome == AppointmentRenewalCase.Status.REAPPOINTMENT_REQUIRED:
            self._set_term_status(term, AppointmentTerm.Status.REAPPOINTMENT_REQUIRED)
        return RenewalDecision(renewal=renewal, term=term)

    @transaction.atomic
    def open_change(
        self,
        *,
        term_id,
        change_no: str,
        change_type: str,
        effective_date: date,
        target_position_instance_id=None,
        target_level_code: str = "",
        reason: str = "",
    ) -> AppointmentChangeCase:
        term = self._lock_term(term_id)
        if term.status not in {AppointmentTerm.Status.ACTIVE, AppointmentTerm.Status.EXPIRING}:
            raise AppointmentTermError(
                "APPOINTMENT_CHANGE_INVALID_TERM_STATE",
                f"term status {term.status} cannot open a change",
            )
        change_no = (change_no or "").strip()
        change_type = str(change_type or "").strip().upper()
        target_level_code = (target_level_code or "").strip()
        reason = (reason or "").strip()
        if not change_no:
            raise AppointmentTermError("APPOINTMENT_CHANGE_NO_REQUIRED", "change_no is required")
        if change_type not in AppointmentChangeCase.ChangeType.values:
            raise AppointmentTermError("APPOINTMENT_CHANGE_TYPE_INVALID", "invalid change type")
        if effective_date < term.effective_from:
            raise AppointmentTermError(
                "APPOINTMENT_CHANGE_DATE_INVALID",
                "change effective_date cannot be earlier than the current term",
            )
        if change_type in {
            AppointmentChangeCase.ChangeType.PROMOTION,
            AppointmentChangeCase.ChangeType.DOWNGRADE,
        } and not target_level_code:
            raise AppointmentTermError(
                "APPOINTMENT_CHANGE_TARGET_LEVEL_REQUIRED",
                "promotion/downgrade requires target_level_code",
            )
        if change_type == AppointmentChangeCase.ChangeType.TRANSFER and not target_position_instance_id:
            raise AppointmentTermError(
                "APPOINTMENT_CHANGE_TARGET_POSITION_REQUIRED",
                "transfer requires target_position_instance_id",
            )
        if change_type in {
            AppointmentChangeCase.ChangeType.TERMINATION,
            AppointmentChangeCase.ChangeType.CORRECTION,
        } and not reason:
            raise AppointmentTermError(
                "APPOINTMENT_CHANGE_REASON_REQUIRED",
                "termination/correction requires a reason",
            )

        existing = (
            AppointmentChangeCase.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, change_no=change_no)
            .first()
        )
        if existing is not None:
            expected = {
                "source_term_id": term.id,
                "change_type": change_type,
                "policy_version_id": term.policy_version_id,
                "target_position_instance_id": target_position_instance_id,
                "target_level_code": target_level_code,
                "effective_date": effective_date,
                "reason": reason,
            }
            if any(getattr(existing, key) != value for key, value in expected.items()):
                raise AppointmentTermError(
                    "APPOINTMENT_CHANGE_IDEMPOTENCY_CONFLICT",
                    "change_no already exists with different content",
                )
            return existing

        blocking = AppointmentChangeCase.objects.select_for_update().filter(
            tenant_id=self.tenant_id,
            source_term_id=term.id,
            status__in=[
                AppointmentChangeCase.Status.REVIEW_REQUIRED,
                AppointmentChangeCase.Status.APPROVED,
                AppointmentChangeCase.Status.REAPPOINTMENT_REQUIRED,
            ],
        )
        if blocking.exists():
            raise AppointmentTermError(
                "APPOINTMENT_CHANGE_ALREADY_OPEN",
                "a change workflow is already open for this term",
            )
        attempt_no = (
            AppointmentChangeCase.objects.filter(
                tenant_id=self.tenant_id, source_term_id=term.id
            ).aggregate(value=Max("attempt_no"))["value"]
            or 0
        ) + 1
        return AppointmentChangeCase.objects.create(
            tenant_id=self.tenant_id,
            change_no=change_no,
            source_term_id=term.id,
            attempt_no=attempt_no,
            change_type=change_type,
            policy_version_id=term.policy_version_id,
            target_position_instance_id=target_position_instance_id,
            target_level_code=target_level_code,
            effective_date=effective_date,
            reason=reason,
            status=AppointmentChangeCase.Status.REVIEW_REQUIRED,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )

    @transaction.atomic
    def decide_change(
        self,
        change_id,
        *,
        outcome: str,
        decision_snapshot=None,
    ) -> ChangeDecision:
        change = (
            AppointmentChangeCase.objects.select_for_update()
            .filter(id=change_id, tenant_id=self.tenant_id)
            .first()
        )
        if change is None:
            raise AppointmentTermError("APPOINTMENT_CHANGE_NOT_FOUND", "change case not found")
        term = self._lock_term(change.source_term_id)
        if change.status != AppointmentChangeCase.Status.REVIEW_REQUIRED:
            raise AppointmentTermError(
                "APPOINTMENT_CHANGE_INVALID_STATE",
                f"change status {change.status} cannot be decided",
            )
        outcome = str(outcome or "").strip().upper()
        allowed = {
            AppointmentChangeCase.Status.APPROVED,
            AppointmentChangeCase.Status.REJECTED,
            AppointmentChangeCase.Status.CANCELLED,
            AppointmentChangeCase.Status.REAPPOINTMENT_REQUIRED,
        }
        if outcome not in allowed:
            raise AppointmentTermError("APPOINTMENT_CHANGE_OUTCOME_INVALID", "invalid change outcome")
        decision_snapshot = {} if decision_snapshot is None else decision_snapshot
        if not isinstance(decision_snapshot, dict):
            raise AppointmentTermError(
                "APPOINTMENT_CHANGE_DECISION_INVALID",
                "decision_snapshot must be an object",
            )
        change.status = outcome
        change.decision_snapshot_json = decision_snapshot
        change.decided_by = self.actor_user_id
        change.decided_at = timezone.now()
        change.updated_by = self.actor_user_id
        change.save(
            update_fields=[
                "status",
                "decision_snapshot_json",
                "decided_by",
                "decided_at",
                "updated_by",
                "updated_at",
            ]
        )
        if outcome == AppointmentChangeCase.Status.REAPPOINTMENT_REQUIRED:
            self._set_term_status(term, AppointmentTerm.Status.REAPPOINTMENT_REQUIRED)
        return ChangeDecision(change=change, term=term)
