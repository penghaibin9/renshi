"""Append-only correction and revocation chain for the HR16 ExitFact authority."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from django.db import IntegrityError, transaction
from django.utils import timezone

from horilla.hr_event_service import emit_registered_event
from hr_exit.archive_registry import EVENT_EXIT_FACT_REVISED, EVENT_EXIT_FACT_REVOKED
from hr_exit.models import ExitCase, ExitFact


class ExitFactCorrectionError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def exit_fact_event_payload(fact: ExitFact) -> dict:
    """Stable evidence envelope shared by publish/correct/revoke outbox events."""

    return {
        "factId": str(fact.id),
        "factNo": fact.fact_no,
        "personId": str(fact.person_id),
        "employmentRelationshipId": str(fact.employment_relationship_id),
        "sourceCaseId": str(fact.source_case_id),
        "exitType": fact.exit_type,
        "employmentEndDate": fact.employment_end_date.isoformat(),
        "lastWorkingDate": (
            fact.last_working_date.isoformat() if fact.last_working_date else None
        ),
        "accessEndAt": fact.access_end_at.isoformat() if fact.access_end_at else None,
        "status": fact.status,
        "supersedesFactId": (
            str(fact.supersedes_fact_id) if fact.supersedes_fact_id else None
        ),
        "changeReason": fact.change_reason,
        "evidenceRef": fact.evidence_ref,
        "contentHash": fact.content_hash,
        "sealedAt": fact.sealed_at.isoformat(),
    }


class ExitFactCorrectionService:
    """Create successors without rewriting the HR03 effect or old HR16 rows."""

    _CHANGE_FIELDS = frozenset(
        {"exit_type", "employment_end_date", "last_working_date", "access_end_at"}
    )

    def __init__(
        self,
        tenant_id: int,
        actor_user_id: Optional[int] = None,
        correlation_id: str = "",
    ):
        if not tenant_id:
            raise ExitFactCorrectionError(
                "TENANT_CONTEXT_REQUIRED", "tenant_id is required"
            )
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id
        self.correlation_id = str(correlation_id or "")

    @staticmethod
    def _normalize_text(value, *, code: str, limit: int) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ExitFactCorrectionError(code, f"{code.lower()} is required")
        if len(normalized) > limit:
            raise ExitFactCorrectionError(code, f"value exceeds {limit} characters")
        return normalized

    def _lock_fact(self, fact_id) -> ExitFact:
        fact = (
            ExitFact.objects.select_for_update()
            .filter(id=fact_id, tenant_id=self.tenant_id)
            .first()
        )
        if fact is None:
            raise ExitFactCorrectionError(
                "EXIT_FACT_NOT_FOUND", "exit fact not found inside tenant"
            )
        if fact.status == ExitFact.Status.EFFECT_PENDING:
            raise ExitFactCorrectionError(
                "EXIT_FACT_NOT_FORMAL", "pending facts must complete the existing exit saga"
            )
        if fact.status == ExitFact.Status.REVOKED:
            raise ExitFactCorrectionError(
                "EXIT_FACT_REVOKED", "a revoked fact cannot be corrected or revoked again"
            )
        return fact

    @staticmethod
    def _payload_matches(existing: ExitFact, expected: dict) -> bool:
        return all(getattr(existing, field) == value for field, value in expected.items())

    def _find_exact_replay(self, fact_no: str, expected: dict) -> ExitFact | None:
        existing = (
            ExitFact.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, fact_no=fact_no)
            .first()
        )
        if existing is None:
            return None
        if not self._payload_matches(existing, expected):
            raise ExitFactCorrectionError(
                "EXIT_FACT_IDEMPOTENCY_CONFLICT",
                "fact_no already belongs to a different formal exit payload",
            )
        return existing

    def _require_chain_head(self, fact: ExitFact) -> None:
        if ExitFact.objects.filter(
            tenant_id=self.tenant_id, supersedes_fact_id=fact.id
        ).exists():
            raise ExitFactCorrectionError(
                "EXIT_FACT_ALREADY_SUPERSEDED", "exit fact already has a successor"
            )

    @staticmethod
    def _validate_snapshot(values: dict) -> None:
        if values["exit_type"] not in ExitCase.ExitType.values:
            raise ExitFactCorrectionError(
                "EXIT_FACT_EXIT_TYPE_INVALID", "unsupported exit_type"
            )
        if not isinstance(values["employment_end_date"], date):
            raise ExitFactCorrectionError(
                "EXIT_FACT_EMPLOYMENT_END_DATE_INVALID", "employment_end_date is required"
            )
        last_working = values["last_working_date"]
        if last_working is not None and not isinstance(last_working, date):
            raise ExitFactCorrectionError(
                "EXIT_FACT_LAST_WORKING_DATE_INVALID", "last_working_date must be a date"
            )
        if last_working is not None and last_working > values["employment_end_date"]:
            raise ExitFactCorrectionError(
                "EXIT_FACT_DATE_RANGE_INVALID",
                "last_working_date cannot be later than employment_end_date",
            )
        access_end = values["access_end_at"]
        if access_end is not None and not isinstance(access_end, datetime):
            raise ExitFactCorrectionError(
                "EXIT_FACT_ACCESS_END_INVALID", "access_end_at must be a datetime"
            )

    def _create_successor(
        self,
        *,
        current: ExitFact,
        fact_no: str,
        status: str,
        reason_code: str,
        evidence_ref: str,
        snapshot: dict,
        event_name: str,
    ) -> ExitFact:
        expected = {
            "person_id": current.person_id,
            "employment_relationship_id": current.employment_relationship_id,
            "source_case_id": current.source_case_id,
            "exit_type": snapshot["exit_type"],
            "employment_end_date": snapshot["employment_end_date"],
            "last_working_date": snapshot["last_working_date"],
            "access_end_at": snapshot["access_end_at"],
            "status": status,
            "effect_receipt_json": current.effect_receipt_json,
            "last_effect_error": "",
            "supersedes_fact_id": current.id,
            "change_reason": reason_code,
            "evidence_ref": evidence_ref,
        }
        replay = self._find_exact_replay(fact_no, expected)
        if replay is not None:
            return replay
        self._require_chain_head(current)

        successor = ExitFact(
            tenant_id=self.tenant_id,
            fact_no=fact_no,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
            sealed_at=timezone.now(),
            **expected,
        )
        successor.content_hash = successor.calculate_content_hash()
        try:
            successor.save(force_insert=True)
        except IntegrityError as exc:
            raise ExitFactCorrectionError(
                "EXIT_FACT_ALREADY_SUPERSEDED", "exit fact already has a successor"
            ) from exc
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=event_name,
            payload=exit_fact_event_payload(successor),
            correlation_id=self.correlation_id,
        )
        return successor

    @transaction.atomic
    def correct(
        self,
        *,
        fact_id,
        fact_no: str,
        reason_code: str,
        evidence_ref: str,
        changes: dict,
    ) -> ExitFact:
        fact_no = self._normalize_text(
            fact_no, code="EXIT_FACT_NO_REQUIRED", limit=64
        )
        reason_code = self._normalize_text(
            reason_code, code="EXIT_FACT_CHANGE_REASON_REQUIRED", limit=128
        )
        evidence_ref = self._normalize_text(
            evidence_ref, code="EXIT_FACT_EVIDENCE_REQUIRED", limit=256
        )
        if not isinstance(changes, dict) or not changes:
            raise ExitFactCorrectionError(
                "EXIT_FACT_CORRECTION_EMPTY", "at least one correction field is required"
            )
        unknown = sorted(set(changes) - self._CHANGE_FIELDS)
        if unknown:
            raise ExitFactCorrectionError(
                "EXIT_FACT_CORRECTION_FIELD_INVALID",
                "unsupported correction fields: " + ",".join(unknown),
            )

        current = self._lock_fact(fact_id)
        snapshot = {
            field: changes.get(field, getattr(current, field))
            for field in self._CHANGE_FIELDS
        }
        self._validate_snapshot(snapshot)
        if all(getattr(current, field) == snapshot[field] for field in self._CHANGE_FIELDS):
            raise ExitFactCorrectionError(
                "EXIT_FACT_CORRECTION_NO_CHANGE", "correction must change the formal snapshot"
            )
        return self._create_successor(
            current=current,
            fact_no=fact_no,
            status=ExitFact.Status.REVISED,
            reason_code=reason_code,
            evidence_ref=evidence_ref,
            snapshot=snapshot,
            event_name=EVENT_EXIT_FACT_REVISED,
        )

    @transaction.atomic
    def revoke(
        self,
        *,
        fact_id,
        fact_no: str,
        reason_code: str,
        evidence_ref: str,
    ) -> ExitFact:
        fact_no = self._normalize_text(
            fact_no, code="EXIT_FACT_NO_REQUIRED", limit=64
        )
        reason_code = self._normalize_text(
            reason_code, code="EXIT_FACT_CHANGE_REASON_REQUIRED", limit=128
        )
        evidence_ref = self._normalize_text(
            evidence_ref, code="EXIT_FACT_EVIDENCE_REQUIRED", limit=256
        )
        current = self._lock_fact(fact_id)
        snapshot = {
            field: getattr(current, field) for field in self._CHANGE_FIELDS
        }
        return self._create_successor(
            current=current,
            fact_no=fact_no,
            status=ExitFact.Status.REVOKED,
            reason_code=reason_code,
            evidence_ref=evidence_ref,
            snapshot=snapshot,
            event_name=EVENT_EXIT_FACT_REVOKED,
        )
