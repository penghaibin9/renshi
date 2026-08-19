"""HR14 collective final-decision service.

The system records an authorized human decision; it never infers appointment
approval from ranking score or publicity completion. When HR13 title evidence
is part of the decision basis, callers use the trusted HR13 boundary rather
than supplying an arbitrary title snapshot.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from django.db import transaction
from django.utils import timezone

from hr_appointment.decision_models import AppointmentCollectiveDecision
from hr_appointment.models import AppointmentApplicationCase, AppointmentPublicityRecord
from hr_appointment.services.publicity_service import (
    AppointmentPublicityError,
    AppointmentPublicityService,
)


class AppointmentDecisionError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class AppointmentDecisionService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise AppointmentDecisionError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    @transaction.atomic
    def record_with_title_result(
        self,
        *,
        case_id,
        decision_no: str,
        outcome: str,
        authority_ref: str,
        title_result_id,
        as_of: date,
        decision_reason: str = "",
        additional_evidence=None,
    ):
        """Record a collective decision with provider-verified HR13 evidence."""

        if not isinstance(as_of, date):
            raise AppointmentDecisionError(
                "APPOINTMENT_TITLE_EVIDENCE_AS_OF_REQUIRED", "as_of must be a date"
            )
        case = (
            AppointmentApplicationCase.objects.select_for_update()
            .filter(id=case_id, tenant_id=self.tenant_id)
            .first()
        )
        if case is None:
            raise AppointmentDecisionError(
                "APPOINTMENT_CASE_NOT_FOUND", "appointment case not found"
            )

        from hr_title.public import (
            PROVIDER_VERSION,
            TitleEvidenceUnavailable,
            get_effective_title_evidence,
        )

        try:
            title_evidence = get_effective_title_evidence(
                tenant_id=self.tenant_id,
                person_id=case.person_id,
                result_id=title_result_id,
                as_of=as_of,
                source_version=PROVIDER_VERSION,
            )
        except TitleEvidenceUnavailable as exc:
            raise AppointmentDecisionError(exc.code, str(exc)) from exc

        if additional_evidence is None:
            evidence_snapshot = {}
        elif isinstance(additional_evidence, dict):
            evidence_snapshot = dict(additional_evidence)
        else:
            raise AppointmentDecisionError(
                "APPOINTMENT_DECISION_EVIDENCE_INVALID",
                "additional_evidence must be an object",
            )
        if "hr13TitleResult" in evidence_snapshot:
            raise AppointmentDecisionError(
                "APPOINTMENT_DECISION_RESERVED_EVIDENCE_KEY",
                "hr13TitleResult is reserved for provider-verified HR13 evidence",
            )
        evidence_snapshot["hr13TitleResult"] = {
            **title_evidence.snapshot(),
            "providerVersion": title_evidence.source_version,
            "asOf": as_of.isoformat(),
        }
        return self.record(
            case_id=case.id,
            decision_no=decision_no,
            outcome=outcome,
            authority_ref=authority_ref,
            decision_reason=decision_reason,
            evidence_snapshot=evidence_snapshot,
        )

    @transaction.atomic
    def record(
        self,
        *,
        case_id,
        decision_no: str,
        outcome: str,
        authority_ref: str,
        decision_reason: str = "",
        evidence_snapshot=None,
    ):
        decision_no = str(decision_no or "").strip()
        authority_ref = str(authority_ref or "").strip()
        decision_reason = str(decision_reason or "").strip()
        outcome = str(outcome or "").strip().upper()
        if not decision_no or len(decision_no) > 64:
            raise AppointmentDecisionError(
                "APPOINTMENT_DECISION_NO_INVALID",
                "decision_no is required and must be <= 64 characters",
            )
        if not authority_ref or len(authority_ref) > 200:
            raise AppointmentDecisionError(
                "APPOINTMENT_DECISION_AUTHORITY_REQUIRED",
                "authority_ref is required and must be <= 200 characters",
            )
        if outcome not in AppointmentCollectiveDecision.Outcome.values:
            raise AppointmentDecisionError(
                "APPOINTMENT_DECISION_OUTCOME_INVALID",
                "outcome must be APPROVED or REJECTED",
            )
        if evidence_snapshot is None:
            evidence_snapshot = {}
        if not isinstance(evidence_snapshot, dict):
            raise AppointmentDecisionError(
                "APPOINTMENT_DECISION_EVIDENCE_INVALID",
                "evidence_snapshot must be an object",
            )

        case = (
            AppointmentApplicationCase.objects.select_for_update()
            .filter(id=case_id, tenant_id=self.tenant_id)
            .first()
        )
        if case is None:
            raise AppointmentDecisionError(
                "APPOINTMENT_CASE_NOT_FOUND", "appointment case not found"
            )

        existing = (
            AppointmentCollectiveDecision.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, decision_no=decision_no)
            .first()
        )
        if existing is not None:
            same = (
                str(existing.application_case_id) == str(case.id)
                and existing.outcome == outcome
                and existing.authority_ref == authority_ref
                and existing.decision_reason == decision_reason
                and existing.evidence_snapshot_json == evidence_snapshot
            )
            if not same:
                raise AppointmentDecisionError(
                    "APPOINTMENT_DECISION_IDEMPOTENCY_CONFLICT",
                    "decision_no already belongs to a different collective decision payload",
                )
            return existing, False

        if case.status != AppointmentApplicationCase.Status.PUBLICITY:
            raise AppointmentDecisionError(
                "APPOINTMENT_DECISION_INVALID_CASE_STATE",
                f"case status {case.status} cannot receive a collective decision",
            )

        try:
            publicity = AppointmentPublicityService(
                self.tenant_id, actor_user_id=self.actor_user_id
            ).assert_ready_for_effect(case.id)
        except AppointmentPublicityError as exc:
            raise AppointmentDecisionError(exc.code, str(exc)) from exc

        conflicting = AppointmentCollectiveDecision.objects.select_for_update().filter(
            tenant_id=self.tenant_id,
            publicity_id=publicity.id,
        ).first()
        if conflicting is not None:
            raise AppointmentDecisionError(
                "APPOINTMENT_DECISION_ALREADY_RECORDED",
                "latest publicity already has a collective decision fact",
            )

        decision = AppointmentCollectiveDecision.objects.create(
            tenant_id=self.tenant_id,
            decision_no=decision_no,
            application_case_id=case.id,
            publicity=publicity,
            batch_no=case.batch_no,
            person_id=case.person_id,
            position_instance_id=case.position_instance_id,
            outcome=outcome,
            authority_ref=authority_ref,
            decision_reason=decision_reason,
            evidence_snapshot_json=evidence_snapshot,
            decided_at=timezone.now(),
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        if outcome == AppointmentCollectiveDecision.Outcome.REJECTED:
            case.status = AppointmentApplicationCase.Status.NOT_SELECTED
            case.updated_by = self.actor_user_id
            case.save(update_fields=["status", "updated_by", "updated_at"])
        return decision, True
