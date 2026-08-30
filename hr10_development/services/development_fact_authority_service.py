"""Append-only correction and revocation authority for formal HR10 facts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction

from hr10_development.models.development_fact import HrDevelopmentFact
from hr10_development.models.outbox import HrDevelopmentOutboxEvent


class DevelopmentFactAuthorityError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def development_fact_event_payload(fact: HrDevelopmentFact) -> dict:
    return {
        "factId": str(fact.id),
        "staffMasterId": str(fact.staff_master_id),
        "factType": fact.fact_type,
        "sourceCaseType": fact.source_case_type,
        "sourceCaseId": str(fact.source_case_id),
        "sourceRevisionNo": fact.source_revision_no,
        "recordKind": fact.record_kind,
        "supersedesFactId": (
            str(fact.supersedes_fact_id) if fact.supersedes_fact_id else None
        ),
        "reasonCode": fact.correction_reason,
        "evidenceRef": fact.correction_evidence_ref,
        "contentHash": fact.content_hash,
        "sealedAt": fact.sealed_at.isoformat(),
    }


class DevelopmentFactAuthorityService:
    """Create a successor; never rewrite or remove an already published fact."""

    CHANGE_FIELDS = frozenset(
        {
            "activity_type", "provider_org_id", "start_date", "end_date",
            "verified_hours", "verified_days", "verified_credits",
            "level_or_result", "verification_status", "evidence_package_hash",
            "valid_from", "valid_to",
        }
    )
    DATE_FIELDS = frozenset({"start_date", "end_date", "valid_from", "valid_to"})
    DECIMAL_FIELDS = frozenset({"verified_hours", "verified_credits"})

    def __init__(self, *, tenant_id: int, actor_user_id: int, correlation_id: str = ""):
        if not tenant_id:
            raise DevelopmentFactAuthorityError(
                "TENANT_CONTEXT_REQUIRED", "tenant_id is required"
            )
        if not actor_user_id:
            raise DevelopmentFactAuthorityError(
                "ACTOR_REQUIRED", "authenticated actor is required"
            )
        self.tenant_id = int(tenant_id)
        self.actor_user_id = int(actor_user_id)
        self.correlation_id = str(correlation_id or "")[:64]

    @staticmethod
    def _required_text(value, code: str, limit: int) -> str:
        value = str(value or "").strip()
        if not value:
            raise DevelopmentFactAuthorityError(code, "required value is missing")
        if len(value) > limit:
            raise DevelopmentFactAuthorityError(code, f"value exceeds {limit} characters")
        return value

    def _lock_head(self, fact_id: int) -> HrDevelopmentFact:
        fact = (
            HrDevelopmentFact.objects.select_for_update()
            .filter(pk=fact_id, tenant_id=self.tenant_id)
            .first()
        )
        if fact is None:
            raise DevelopmentFactAuthorityError(
                "DEVELOPMENT_FACT_NOT_FOUND", "fact not found inside tenant"
            )
        if HrDevelopmentFact.objects.filter(
            tenant_id=self.tenant_id, supersedes_fact_id=fact.id
        ).exists():
            raise DevelopmentFactAuthorityError(
                "DEVELOPMENT_FACT_ALREADY_SUPERSEDED", "only the chain head can change"
            )
        if fact.record_kind == HrDevelopmentFact.RecordKind.REVOCATION:
            raise DevelopmentFactAuthorityError(
                "DEVELOPMENT_FACT_ALREADY_REVOKED", "revoked fact is terminal"
            )
        if not fact.verify_content_hash():
            raise DevelopmentFactAuthorityError(
                "DEVELOPMENT_FACT_INTEGRITY_FAILED", "stored fact hash is invalid"
            )
        return fact

    def _normalize_changes(self, changes: dict) -> dict:
        if not isinstance(changes, dict) or not changes:
            raise DevelopmentFactAuthorityError(
                "DEVELOPMENT_FACT_CORRECTION_EMPTY", "at least one change is required"
            )
        unknown = sorted(set(changes) - self.CHANGE_FIELDS)
        if unknown:
            raise DevelopmentFactAuthorityError(
                "DEVELOPMENT_FACT_FIELD_FORBIDDEN",
                "unsupported correction fields: " + ",".join(unknown),
            )
        normalized = {}
        for field, value in changes.items():
            if field in self.DATE_FIELDS and value not in (None, ""):
                try:
                    value = value if isinstance(value, date) else date.fromisoformat(str(value))
                except ValueError as exc:
                    raise DevelopmentFactAuthorityError(
                        "DEVELOPMENT_FACT_DATE_INVALID", f"{field} must be ISO date"
                    ) from exc
            elif field in self.DECIMAL_FIELDS and value not in (None, ""):
                try:
                    value = Decimal(str(value))
                except InvalidOperation as exc:
                    raise DevelopmentFactAuthorityError(
                        "DEVELOPMENT_FACT_NUMBER_INVALID", f"{field} must be numeric"
                    ) from exc
            normalized[field] = None if value == "" else value
        return normalized

    @staticmethod
    def _snapshot(fact: HrDevelopmentFact) -> dict:
        fields = (
            "staff_master_id", "fact_type", "source_case_type", "source_case_id",
            "activity_type", "provider_org_id", "start_date", "end_date",
            "verified_hours", "verified_days", "verified_credits", "level_or_result",
            "verification_status", "evidence_package_hash", "generated_at",
            "valid_from", "valid_to",
        )
        return {field: getattr(fact, field) for field in fields}

    def _emit(self, fact: HrDevelopmentFact, event_type: str) -> None:
        HrDevelopmentOutboxEvent.objects.create(
            tenant_id=self.tenant_id,
            created_by_id=self.actor_user_id,
            updated_by_id=self.actor_user_id,
            event_type=event_type,
            aggregate_type="HrDevelopmentFact",
            aggregate_id=str(fact.id),
            aggregate_version=fact.source_revision_no + 1,
            correlation_id=self.correlation_id,
            payload_json=development_fact_event_payload(fact),
        )

    def _replay(self, idempotency_key: str, *, expected_kind: str, parent_id: int):
        existing = HrDevelopmentFact.objects.filter(
            tenant_id=self.tenant_id, idempotency_key=idempotency_key
        ).first()
        if existing is None:
            return None
        if existing.record_kind != expected_kind or existing.supersedes_fact_id != parent_id:
            raise DevelopmentFactAuthorityError(
                "DEVELOPMENT_FACT_IDEMPOTENCY_CONFLICT",
                "idempotency key belongs to another authority action",
            )
        return existing

    def _successor(
        self, *, current: HrDevelopmentFact, record_kind: str, reason_code: str,
        evidence_ref: str, idempotency_key: str, changes: dict,
    ) -> HrDevelopmentFact:
        replay = self._replay(
            idempotency_key, expected_kind=record_kind, parent_id=current.id
        )
        if replay is not None:
            return replay

        values = self._snapshot(current)
        values.update(changes)
        successor = HrDevelopmentFact(
            tenant_id=self.tenant_id,
            source_revision_no=current.source_revision_no + 1,
            supersedes_fact_id=current.id,
            record_kind=record_kind,
            correction_reason=reason_code,
            correction_evidence_ref=evidence_ref,
            idempotency_key=idempotency_key,
            sealed_by=self.actor_user_id,
            created_by_id=self.actor_user_id,
            updated_by_id=self.actor_user_id,
            **values,
        )
        try:
            successor.save(force_insert=True)
        except IntegrityError as exc:
            raise DevelopmentFactAuthorityError(
                "DEVELOPMENT_FACT_ALREADY_SUPERSEDED", "fact already has a successor"
            ) from exc
        event = (
            "hr.development.development_fact.corrected"
            if record_kind == HrDevelopmentFact.RecordKind.CORRECTION
            else "hr.development.development_fact.revoked"
        )
        self._emit(successor, event)
        return successor

    @transaction.atomic
    def correct(
        self, *, fact_id: int, reason_code: str, evidence_ref: str,
        idempotency_key: str, changes: dict,
    ) -> HrDevelopmentFact:
        reason_code = self._required_text(
            reason_code, "DEVELOPMENT_FACT_REASON_REQUIRED", 128
        )
        evidence_ref = self._required_text(
            evidence_ref, "DEVELOPMENT_FACT_EVIDENCE_REQUIRED", 256
        )
        idempotency_key = self._required_text(
            idempotency_key, "IDEMPOTENCY_KEY_REQUIRED", 128
        )
        current = self._lock_head(fact_id)
        changes = self._normalize_changes(changes)
        if all(getattr(current, field) == value for field, value in changes.items()):
            raise DevelopmentFactAuthorityError(
                "DEVELOPMENT_FACT_CORRECTION_NO_CHANGE", "correction changes nothing"
            )
        return self._successor(
            current=current,
            record_kind=HrDevelopmentFact.RecordKind.CORRECTION,
            reason_code=reason_code,
            evidence_ref=evidence_ref,
            idempotency_key=idempotency_key,
            changes=changes,
        )

    @transaction.atomic
    def revoke(
        self, *, fact_id: int, reason_code: str, evidence_ref: str,
        idempotency_key: str,
    ) -> HrDevelopmentFact:
        reason_code = self._required_text(
            reason_code, "DEVELOPMENT_FACT_REASON_REQUIRED", 128
        )
        evidence_ref = self._required_text(
            evidence_ref, "DEVELOPMENT_FACT_EVIDENCE_REQUIRED", 256
        )
        idempotency_key = self._required_text(
            idempotency_key, "IDEMPOTENCY_KEY_REQUIRED", 128
        )
        current = self._lock_head(fact_id)
        return self._successor(
            current=current,
            record_kind=HrDevelopmentFact.RecordKind.REVOCATION,
            reason_code=reason_code,
            evidence_ref=evidence_ref,
            idempotency_key=idempotency_key,
            changes={},
        )
