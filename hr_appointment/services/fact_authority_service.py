"""Append-only authority service for sealed HR14 appointment facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from django.db import transaction

from horilla.hr_event_service import emit_registered_event
from hr_appointment.authority_registry import (
    EVENT_FACT_CORRECTED,
    EVENT_FACT_EFFECTIVE,
    EVENT_FACT_ENDED,
    EVENT_FACT_REVOKED,
)
from hr_appointment.models import PositionAppointmentFact
from hr_appointment.permissions import (
    FACT_CORRECT_PERMISSION,
    FACT_PUBLISH_PERMISSION,
    FACT_REVOKE_PERMISSION,
)


class AppointmentFactAuthorityError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class AppointmentFactAuthorityResult:
    fact: PositionAppointmentFact
    replayed: bool


def fact_evidence(fact: PositionAppointmentFact) -> dict:
    return {
        "factId": str(fact.id),
        "appointmentNo": fact.appointment_no,
        "factKind": fact.fact_kind,
        "status": fact.status,
        "supersedesFactId": (
            str(fact.supersedes_fact_id) if fact.supersedes_fact_id else None
        ),
        "idempotencyKey": fact.idempotency_key,
        "contentHash": fact.content_hash,
        "sealedAt": fact.sealed_at.isoformat() if fact.sealed_at else None,
        "publishedBy": fact.published_by,
        "authorityReceipt": dict(fact.authority_receipt_json or {}),
        "effectReceipt": dict(fact.effect_receipt_json or {}),
        "hashVerified": fact.verify_content_hash(),
    }


def emit_fact_event(*, fact: PositionAppointmentFact, event_name: str):
    """Write exactly one durable registered outbox row for one sealed fact."""
    from hr_staff.models import HrOutboxEvent

    correlation_id = f"hr14:{fact.id}"
    payload = {
        "factId": str(fact.id),
        "personId": str(fact.person_id),
        "positionInstanceId": fact.position_instance_id,
        "effectiveDate": fact.effective_from.isoformat(),
        "status": fact.status,
        "factKind": fact.fact_kind,
        "supersedesFactId": (
            str(fact.supersedes_fact_id) if fact.supersedes_fact_id else None
        ),
        "contentHash": fact.content_hash,
        "sealedAt": fact.sealed_at.isoformat(),
        "idempotencyKey": fact.idempotency_key,
    }
    existing = (
        HrOutboxEvent.objects.select_for_update()
        .filter(
            tenant_id=fact.tenant_id,
            event_type=event_name,
            correlation_id=correlation_id,
        )
        .first()
    )
    if existing is not None:
        expected = dict(payload)
        expected["eventVersion"] = 1
        if existing.payload_json != expected:
            raise AppointmentFactAuthorityError(
                "APPOINTMENT_FACT_OUTBOX_CONFLICT",
                "the fact already has a different durable outbox payload",
            )
        return existing
    return emit_registered_event(
        tenant_id=fact.tenant_id,
        event_name=event_name,
        payload=payload,
        correlation_id=correlation_id,
    )


class AppointmentFactAuthorityService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int]):
        if not tenant_id:
            raise AppointmentFactAuthorityError(
                "TENANT_CONTEXT_REQUIRED", "tenant_id is required"
            )
        if not actor_user_id:
            raise AppointmentFactAuthorityError(
                "APPOINTMENT_FACT_ACTOR_REQUIRED", "an authenticated actor is required"
            )
        self.tenant_id = int(tenant_id)
        self.actor_user_id = int(actor_user_id)

    @staticmethod
    def _key(value: str) -> str:
        value = str(value or "").strip()
        if not value or len(value) > 128:
            raise AppointmentFactAuthorityError(
                "APPOINTMENT_FACT_IDEMPOTENCY_KEY_INVALID",
                "Idempotency-Key is required and must be at most 128 characters",
            )
        return value

    @staticmethod
    def _reason(value: str) -> str:
        value = str(value or "").strip()
        if not value:
            raise AppointmentFactAuthorityError(
                "APPOINTMENT_FACT_REASON_REQUIRED", "an auditable reason is required"
            )
        return value

    @staticmethod
    def _authority_ref(value: str) -> str:
        value = str(value or "").strip()
        if not value:
            raise AppointmentFactAuthorityError(
                "APPOINTMENT_FACT_AUTHORITY_REF_REQUIRED",
                "an external authority reference is required",
            )
        return value

    def _replay(self, key: str, *, kind: str, source_id) -> Optional[PositionAppointmentFact]:
        fact = (
            PositionAppointmentFact.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, idempotency_key=key)
            .first()
        )
        if fact is None:
            return None
        if fact.fact_kind != kind or str(fact.supersedes_fact_id) != str(source_id):
            raise AppointmentFactAuthorityError(
                "APPOINTMENT_FACT_IDEMPOTENCY_CONFLICT",
                "Idempotency-Key already belongs to a different fact command",
            )
        if not fact.verify_content_hash():
            raise AppointmentFactAuthorityError(
                "APPOINTMENT_FACT_HASH_MISMATCH", "stored appointment fact hash is invalid"
            )
        return fact

    def _source(self, source_fact_id, *, allow_ended: bool = False) -> PositionAppointmentFact:
        source = (
            PositionAppointmentFact.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, id=source_fact_id)
            .first()
        )
        if source is None:
            raise AppointmentFactAuthorityError(
                "APPOINTMENT_FACT_NOT_FOUND", "source appointment fact not found"
            )
        allowed = {
            PositionAppointmentFact.Status.EFFECTIVE,
            PositionAppointmentFact.Status.REVISED,
        }
        if allow_ended:
            allowed.add(PositionAppointmentFact.Status.ENDED)
        if source.status not in allowed or not source.sealed_at:
            raise AppointmentFactAuthorityError(
                "APPOINTMENT_FACT_NOT_FORMAL", "only a sealed formal fact can be superseded"
            )
        if not source.verify_content_hash():
            raise AppointmentFactAuthorityError(
                "APPOINTMENT_FACT_HASH_MISMATCH", "stored appointment fact hash is invalid"
            )
        if PositionAppointmentFact.objects.select_for_update().filter(
            tenant_id=self.tenant_id, supersedes_fact_id=source.id
        ).exists():
            raise AppointmentFactAuthorityError(
                "APPOINTMENT_FACT_ALREADY_SUPERSEDED",
                "only the current fact-chain head can be superseded",
            )
        return source

    def _receipt(self, *, permission: str, authority_ref: str, evidence: dict) -> dict:
        if not isinstance(evidence, dict):
            raise AppointmentFactAuthorityError(
                "APPOINTMENT_FACT_EVIDENCE_INVALID", "evidence must be a JSON object"
            )
        return {
            "permissionCode": permission,
            "authorityRef": authority_ref,
            "actorUserId": self.actor_user_id,
            "evidence": dict(evidence),
        }

    @transaction.atomic
    def correct(
        self,
        source_fact_id,
        *,
        appointment_no: str,
        idempotency_key: str,
        reason: str,
        authority_ref: str,
        evidence: dict,
        position_instance_id: Optional[int] = None,
        level_code: Optional[str] = None,
        effective_from: Optional[date] = None,
        effective_to: Optional[date] = None,
    ) -> AppointmentFactAuthorityResult:
        key = self._key(idempotency_key)
        replay = self._replay(
            key, kind=PositionAppointmentFact.FactKind.CORRECTION, source_id=source_fact_id
        )
        if replay is not None:
            return AppointmentFactAuthorityResult(replay, True)
        source = self._source(source_fact_id, allow_ended=True)
        appointment_no = str(appointment_no or "").strip()
        if not appointment_no or len(appointment_no) > 64:
            raise AppointmentFactAuthorityError(
                "APPOINTMENT_NO_INVALID",
                "a new appointment number of at most 64 characters is required",
            )
        if position_instance_id is not None and (
            not isinstance(position_instance_id, int) or position_instance_id <= 0
        ):
            raise AppointmentFactAuthorityError(
                "POSITION_INSTANCE_ID_INVALID", "positionInstanceId must be positive"
            )
        if level_code is not None and len(str(level_code)) > 64:
            raise AppointmentFactAuthorityError(
                "APPOINTMENT_LEVEL_CODE_INVALID", "levelCode is too long"
            )
        if effective_from is not None and not isinstance(effective_from, date):
            raise AppointmentFactAuthorityError(
                "APPOINTMENT_EFFECTIVE_FROM_INVALID", "effectiveFrom must be a date"
            )
        if effective_to is not None and not isinstance(effective_to, date):
            raise AppointmentFactAuthorityError(
                "APPOINTMENT_EFFECTIVE_TO_INVALID", "effectiveTo must be a date"
            )
        start = effective_from or source.effective_from
        end = effective_to if effective_to is not None else source.effective_to
        if end is not None and end <= start:
            raise AppointmentFactAuthorityError(
                "APPOINTMENT_FACT_EFFECTIVE_RANGE_INVALID",
                "effectiveTo must be later than effectiveFrom",
            )
        authority_ref = self._authority_ref(authority_ref)
        fact = PositionAppointmentFact.objects.create(
            tenant_id=self.tenant_id,
            appointment_no=appointment_no,
            person_id=source.person_id,
            position_instance_id=position_instance_id or source.position_instance_id,
            application_case_id=source.application_case_id,
            reservation_id=source.reservation_id,
            level_code=source.level_code if level_code is None else str(level_code),
            effective_from=start,
            effective_to=end,
            supersedes_fact_id=source.id,
            fact_kind=PositionAppointmentFact.FactKind.CORRECTION,
            revision_reason=self._reason(reason),
            idempotency_key=key,
            effect_receipt_json={
                "sourceFactId": str(source.id),
                "sourceContentHash": source.content_hash,
                "correctionAuthorityRef": authority_ref,
            },
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        fact.seal(
            status=PositionAppointmentFact.Status.REVISED,
            actor_user_id=self.actor_user_id,
            authority_receipt=self._receipt(
                permission=FACT_CORRECT_PERMISSION,
                authority_ref=authority_ref,
                evidence=evidence,
            ),
        )
        emit_fact_event(fact=fact, event_name=EVENT_FACT_CORRECTED)
        return AppointmentFactAuthorityResult(fact, False)

    @transaction.atomic
    def revoke(
        self,
        source_fact_id,
        *,
        idempotency_key: str,
        reason: str,
        authority_ref: str,
        evidence: dict,
    ) -> AppointmentFactAuthorityResult:
        key = self._key(idempotency_key)
        replay = self._replay(
            key, kind=PositionAppointmentFact.FactKind.REVOCATION, source_id=source_fact_id
        )
        if replay is not None:
            return AppointmentFactAuthorityResult(replay, True)
        source = self._source(source_fact_id)
        authority_ref = self._authority_ref(authority_ref)
        fact = PositionAppointmentFact.objects.create(
            tenant_id=self.tenant_id,
            appointment_no=f"RVK-{source.id.hex[:20]}",
            person_id=source.person_id,
            position_instance_id=source.position_instance_id,
            application_case_id=source.application_case_id,
            reservation_id=source.reservation_id,
            level_code=source.level_code,
            effective_from=source.effective_from,
            effective_to=source.effective_to,
            supersedes_fact_id=source.id,
            fact_kind=PositionAppointmentFact.FactKind.REVOCATION,
            revision_reason=self._reason(reason),
            idempotency_key=key,
            effect_receipt_json={
                "sourceFactId": str(source.id),
                "sourceContentHash": source.content_hash,
                "revocationAuthorityRef": authority_ref,
            },
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        fact.seal(
            status=PositionAppointmentFact.Status.REVOKED,
            actor_user_id=self.actor_user_id,
            authority_receipt=self._receipt(
                permission=FACT_REVOKE_PERMISSION,
                authority_ref=authority_ref,
                evidence=evidence,
            ),
        )
        emit_fact_event(fact=fact, event_name=EVENT_FACT_REVOKED)
        return AppointmentFactAuthorityResult(fact, False)


def initial_publish_receipt(*, actor_user_id: int, authority_ref: str, evidence: dict) -> dict:
    return {
        "permissionCode": FACT_PUBLISH_PERMISSION,
        "authorityRef": str(authority_ref),
        "actorUserId": int(actor_user_id),
        "evidence": dict(evidence),
    }


__all__ = [
    "AppointmentFactAuthorityError",
    "AppointmentFactAuthorityResult",
    "AppointmentFactAuthorityService",
    "EVENT_FACT_EFFECTIVE",
    "EVENT_FACT_ENDED",
    "emit_fact_event",
    "fact_evidence",
    "initial_publish_receipt",
]
