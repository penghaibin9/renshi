"""Append-only authority for HR09 school final decisions."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date

from django.db import transaction
from django.utils import timezone

from horilla.hr_event_service import emit_registered_event
from hr_qualification.constants import (
    ApplicationStatus,
    FinalDecisionType,
    RecognitionLevel,
    RecognitionStatus,
)
from hr_qualification.events import (
    EVENT_FINAL_DECISION_CORRECTED,
    EVENT_FINAL_DECISION_REVOKED,
)
from hr_qualification.models import (
    HrDoubleTeacherFinalDecision,
    HrDoubleTeacherFinalDecisionAmendment,
    HrDoubleTeacherRecognition,
)


FINAL_DECISION_CORRECT_PERMISSION = (
    "hr.qualification.review.final_decision.correct"
)
FINAL_DECISION_REVOKE_PERMISSION = (
    "hr.qualification.review.final_decision.revoke"
)


class FinalDecisionAuthorityError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class FinalDecisionAuthorityResult:
    amendment: HrDoubleTeacherFinalDecisionAmendment
    replayed: bool


def final_decision_evidence(decision: HrDoubleTeacherFinalDecision) -> dict:
    return {
        "decisionId": str(decision.id),
        "applicationId": str(decision.application_id_id),
        "decision": decision.decision,
        "recognizedLevel": decision.recognized_level,
        "effectiveFrom": (
            decision.effective_from.isoformat() if decision.effective_from else None
        ),
        "effectiveTo": (
            decision.effective_to.isoformat() if decision.effective_to else None
        ),
        "contentHash": decision.content_hash,
        "sealedAt": decision.sealed_at.isoformat() if decision.sealed_at else None,
        "publishedBy": decision.published_by,
        "authorityReceipt": dict(decision.authority_receipt_json or {}),
        "hashVerified": decision.verify_content_hash(),
    }


def amendment_evidence(amendment: HrDoubleTeacherFinalDecisionAmendment) -> dict:
    return {
        "amendmentId": str(amendment.id),
        "sourceDecisionId": str(amendment.source_decision_id_id),
        "supersedesAmendmentId": (
            str(amendment.supersedes_amendment_id_id)
            if amendment.supersedes_amendment_id_id
            else None
        ),
        "kind": amendment.kind,
        "replacement": dict(amendment.replacement_payload_json or {}),
        "effectReceipt": dict(amendment.effect_receipt_json or {}),
        "reason": amendment.reason,
        "authorityRef": amendment.authority_ref,
        "idempotencyKey": amendment.idempotency_key,
        "contentHash": amendment.content_hash,
        "sealedAt": amendment.sealed_at.isoformat(),
        "publishedBy": amendment.published_by,
        "hashVerified": amendment.verify_content_hash(),
    }


class FinalDecisionAuthorityService:
    def __init__(self, tenant_id: int, actor_user_id: int | None):
        if not tenant_id:
            raise FinalDecisionAuthorityError(
                "TENANT_CONTEXT_REQUIRED", "tenant_id is required"
            )
        if not actor_user_id:
            raise FinalDecisionAuthorityError(
                "FINAL_DECISION_ACTOR_REQUIRED",
                "an authenticated actor is required",
            )
        self.tenant_id = int(tenant_id)
        self.actor_user_id = int(actor_user_id)

    @staticmethod
    def seal_initial(
        decision: HrDoubleTeacherFinalDecision,
        *,
        actor_user_id: int | None,
    ) -> HrDoubleTeacherFinalDecision:
        decision.seal(
            actor_user_id=actor_user_id,
            authority_receipt={
                "permissionCode": "hr.qualification.review.finalize",
                "authorityRef": (
                    decision.meeting_ref
                    or decision.decision_authority
                    or "HR09-REVIEW-SERVICE"
                ),
                "actorUserId": int(actor_user_id or 0),
                "actorType": "USER" if actor_user_id else "SYSTEM",
            },
        )
        return decision

    @staticmethod
    def _required(value, code: str, limit: int = 200) -> str:
        value = str(value or "").strip()
        if not value:
            raise FinalDecisionAuthorityError(code, f"{code.lower()} is required")
        if len(value) > limit:
            raise FinalDecisionAuthorityError(code, "value is too long")
        return value

    @staticmethod
    def _date(value, field: str) -> date | None:
        if value in (None, ""):
            return None
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value))
        except (TypeError, ValueError) as exc:
            raise FinalDecisionAuthorityError(
                "FINAL_DECISION_INVALID_DATE", f"{field} must be YYYY-MM-DD"
            ) from exc

    def _source(self, decision_id) -> HrDoubleTeacherFinalDecision:
        source = (
            HrDoubleTeacherFinalDecision.objects.select_for_update()
            .select_related("application_id__batch_id__rule_pack_version_id")
            .filter(
                id=decision_id,
                application_id__tenant_id=self.tenant_id,
            )
            .first()
        )
        if source is None:
            raise FinalDecisionAuthorityError(
                "FINAL_DECISION_NOT_FOUND", "final decision not found in tenant"
            )
        if not source.verify_content_hash():
            raise FinalDecisionAuthorityError(
                "FINAL_DECISION_HASH_MISMATCH",
                "stored final decision seal is invalid",
            )
        return source

    def _replay(
        self,
        *,
        key: str,
        kind: str,
        decision_id,
        command_hash: str,
        reason: str,
        authority_ref: str,
        replacement: dict,
        evidence: dict,
    ) -> HrDoubleTeacherFinalDecisionAmendment | None:
        row = (
            HrDoubleTeacherFinalDecisionAmendment.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, idempotency_key=key)
            .first()
        )
        if row is None:
            return None
        if row.kind != kind or str(row.source_decision_id_id) != str(decision_id):
            raise FinalDecisionAuthorityError(
                "FINAL_DECISION_IDEMPOTENCY_CONFLICT",
                "Idempotency-Key belongs to a different command",
            )
        stored_command_hash = str(
            (row.authority_receipt_json or {}).get("commandHash", "")
        )
        if stored_command_hash:
            command_matches = stored_command_hash == command_hash
        else:
            # Rows written by migration 0006 predate commandHash. Preserve exact
            # replay compatibility while still rejecting changed known fields.
            stored_replacement = dict(row.replacement_payload_json or {})
            replacement_matches = all(
                stored_replacement.get(field)
                == (
                    value.isoformat()
                    if hasattr(value, "isoformat")
                    else value
                )
                for field, value in replacement.items()
            )
            command_matches = (
                row.reason == reason
                and row.authority_ref == authority_ref
                and dict((row.authority_receipt_json or {}).get("evidence", {}))
                == evidence
                and replacement_matches
            )
        if not command_matches:
            raise FinalDecisionAuthorityError(
                "FINAL_DECISION_IDEMPOTENCY_CONFLICT",
                "Idempotency-Key was replayed with different command content",
            )
        if not row.verify_content_hash():
            raise FinalDecisionAuthorityError(
                "FINAL_DECISION_AMENDMENT_HASH_MISMATCH",
                "stored amendment seal is invalid",
            )
        return row

    @staticmethod
    def _command_hash(
        *,
        decision_id,
        kind: str,
        reason: str,
        authority_ref: str,
        replacement: dict,
        evidence: dict,
    ) -> str:
        """Bind an idempotency key to the complete caller command."""
        payload = {
            "decisionId": str(decision_id),
            "kind": kind,
            "reason": reason,
            "authorityRef": authority_ref,
            "replacement": replacement,
            "evidence": evidence,
        }
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _head(source: HrDoubleTeacherFinalDecision):
        return (
            HrDoubleTeacherFinalDecisionAmendment.objects.select_for_update()
            .filter(source_decision_id=source)
            .order_by("-created_at", "-id")
            .first()
        )

    @staticmethod
    def _normalized_replacement(source, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise FinalDecisionAuthorityError(
                "FINAL_DECISION_REPLACEMENT_INVALID",
                "replacement must be a JSON object",
            )
        allowed = {
            "decision",
            "recognizedLevel",
            "effectiveFrom",
            "effectiveTo",
            "decisionAuthority",
            "meetingRef",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise FinalDecisionAuthorityError(
                "FINAL_DECISION_REPLACEMENT_FIELD_FORBIDDEN",
                f"unsupported replacement fields: {', '.join(unknown)}",
            )
        result = {
            "decision": payload.get("decision", source.decision),
            "recognizedLevel": payload.get(
                "recognizedLevel", source.recognized_level
            ),
            "effectiveFrom": payload.get(
                "effectiveFrom",
                source.effective_from.isoformat() if source.effective_from else None,
            ),
            "effectiveTo": payload.get(
                "effectiveTo",
                source.effective_to.isoformat() if source.effective_to else None,
            ),
            "decisionAuthority": payload.get(
                "decisionAuthority", source.decision_authority
            ),
            "meetingRef": payload.get("meetingRef", source.meeting_ref),
        }
        if result["decision"] not in FinalDecisionType.values:
            raise FinalDecisionAuthorityError(
                "FINAL_DECISION_INVALID", "replacement decision is invalid"
            )
        if result["decision"] == FinalDecisionType.RECOGNIZE:
            if result["recognizedLevel"] not in RecognitionLevel.values:
                raise FinalDecisionAuthorityError(
                    "RECOGNIZED_LEVEL_INVALID",
                    "recognizedLevel is required for recognition",
                )
            if not result["effectiveFrom"]:
                raise FinalDecisionAuthorityError(
                    "FINAL_DECISION_EFFECTIVE_FROM_REQUIRED",
                    "effectiveFrom is required for recognition",
                )
        else:
            result["recognizedLevel"] = None
            result["effectiveFrom"] = None
            result["effectiveTo"] = None
        for field in ("effectiveFrom", "effectiveTo"):
            parsed = FinalDecisionAuthorityService._date(result[field], field)
            result[field] = parsed.isoformat() if parsed else None
        return result

    def _apply_effect(self, source, *, kind: str, replacement: dict) -> dict:
        recognition = (
            HrDoubleTeacherRecognition.objects.select_for_update()
            .filter(application_id=source.application_id)
            .exclude(
                status__in=[
                    RecognitionStatus.REVOKED,
                    RecognitionStatus.EXPIRED,
                    RecognitionStatus.SUPERSEDED,
                    RecognitionStatus.INVALID,
                ]
            )
            .order_by("-created_at", "-id")
            .first()
        )
        app = source.application_id
        if kind == HrDoubleTeacherFinalDecisionAmendment.Kind.REVOCATION or (
            replacement.get("decision") == FinalDecisionType.NOT_RECOGNIZE
        ):
            if recognition is not None:
                recognition.status = RecognitionStatus.REVOKED
                recognition.effective_to = recognition.effective_to or timezone.localdate()
                recognition.version += 1
                recognition.save(
                    update_fields=["status", "effective_to", "version", "updated_at"]
                )
            app.status = ApplicationStatus.NOT_RECOGNIZED
            app.version += 1
            app.save(update_fields=["status", "version", "updated_at"])
            return {
                "effect": "RECOGNITION_REVOKED",
                "recognitionId": str(recognition.id) if recognition else None,
            }

        effective_from = self._date(replacement["effectiveFrom"], "effectiveFrom")
        same = (
            recognition is not None
            and recognition.level == replacement["recognizedLevel"]
            and recognition.effective_from == effective_from
        )
        if same:
            successor = recognition
            effect = "RECOGNITION_UNCHANGED"
        else:
            if recognition is not None:
                recognition.status = RecognitionStatus.SUPERSEDED
                recognition.effective_to = effective_from
                recognition.version += 1
                recognition.save(
                    update_fields=["status", "effective_to", "version", "updated_at"]
                )
            successor = HrDoubleTeacherRecognition.objects.create(
                tenant_id=self.tenant_id,
                person_id=app.person_id,
                staff_master_id=app.staff_master_id,
                external_engagement_id=app.external_engagement_id,
                recognition_no=f"DT-C-{self.tenant_id}-{uuid.uuid4().hex[:10].upper()}",
                level=replacement["recognizedLevel"],
                rule_pack_version_id=app.batch_id.rule_pack_version_id,
                batch_id=app.batch_id,
                application_id=app,
                effective_from=effective_from,
                effective_to=self._date(replacement["effectiveTo"], "effectiveTo"),
                status=RecognitionStatus.PENDING_EFFECTIVE,
                recognition_authority=replacement["decisionAuthority"],
            )
            effect = "RECOGNITION_SUCCESSOR_CREATED"
        app.status = ApplicationStatus.RECOGNIZED
        app.version += 1
        app.save(update_fields=["status", "version", "updated_at"])
        return {
            "effect": effect,
            "recognitionId": str(successor.id),
            "supersededRecognitionId": (
                str(recognition.id) if recognition is not None and not same else None
            ),
        }

    def _append(
        self,
        decision_id,
        *,
        kind: str,
        idempotency_key: str,
        reason: str,
        authority_ref: str,
        replacement: dict,
        evidence: dict,
    ) -> FinalDecisionAuthorityResult:
        key = self._required(
            idempotency_key, "FINAL_DECISION_IDEMPOTENCY_KEY_REQUIRED", 128
        )
        reason = self._required(reason, "FINAL_DECISION_REASON_REQUIRED", 2000)
        authority_ref = self._required(
            authority_ref, "FINAL_DECISION_AUTHORITY_REF_REQUIRED", 200
        )
        if not isinstance(replacement, dict):
            raise FinalDecisionAuthorityError(
                "FINAL_DECISION_REPLACEMENT_INVALID",
                "replacement must be a JSON object",
            )
        if not isinstance(evidence, dict):
            raise FinalDecisionAuthorityError(
                "FINAL_DECISION_EVIDENCE_INVALID", "evidence must be a JSON object"
            )
        command_hash = self._command_hash(
            decision_id=decision_id,
            kind=kind,
            reason=reason,
            authority_ref=authority_ref,
            replacement=replacement,
            evidence=evidence,
        )
        replay = self._replay(
            key=key,
            kind=kind,
            decision_id=decision_id,
            command_hash=command_hash,
            reason=reason,
            authority_ref=authority_ref,
            replacement=replacement,
            evidence=evidence,
        )
        if replay is not None:
            return FinalDecisionAuthorityResult(replay, True)
        source = self._source(decision_id)
        # Two workers may both miss the key before either locks the source
        # decision.  Re-read after the source row lock so the waiter observes
        # the winner and returns a replay instead of hitting the unique key
        # after applying effects.
        replay = self._replay(
            key=key,
            kind=kind,
            decision_id=decision_id,
            command_hash=command_hash,
            reason=reason,
            authority_ref=authority_ref,
            replacement=replacement,
            evidence=evidence,
        )
        if replay is not None:
            return FinalDecisionAuthorityResult(replay, True)
        head = self._head(source)
        if head is not None:
            if not head.verify_content_hash():
                raise FinalDecisionAuthorityError(
                    "FINAL_DECISION_AMENDMENT_HASH_MISMATCH",
                    "current amendment head is invalid",
                )
            if head.kind == HrDoubleTeacherFinalDecisionAmendment.Kind.REVOCATION:
                raise FinalDecisionAuthorityError(
                    "FINAL_DECISION_ALREADY_REVOKED",
                    "a revoked decision cannot be amended",
                )
        normalized = (
            self._normalized_replacement(source, replacement)
            if kind == HrDoubleTeacherFinalDecisionAmendment.Kind.CORRECTION
            else {
                "decision": FinalDecisionType.NOT_RECOGNIZE,
                "recognizedLevel": None,
                "effectiveFrom": None,
                "effectiveTo": None,
                "decisionAuthority": source.decision_authority,
                "meetingRef": source.meeting_ref,
            }
        )
        effect_receipt = self._apply_effect(
            source, kind=kind, replacement=normalized
        )
        permission = (
            FINAL_DECISION_CORRECT_PERMISSION
            if kind == HrDoubleTeacherFinalDecisionAmendment.Kind.CORRECTION
            else FINAL_DECISION_REVOKE_PERMISSION
        )
        amendment = HrDoubleTeacherFinalDecisionAmendment(
            tenant_id=self.tenant_id,
            source_decision_id=source,
            supersedes_amendment_id=head,
            kind=kind,
            replacement_payload_json=normalized,
            effect_receipt_json=effect_receipt,
            reason=reason,
            authority_ref=authority_ref,
            authority_receipt_json={
                "permissionCode": permission,
                "authorityRef": authority_ref,
                "actorUserId": self.actor_user_id,
                "evidence": dict(evidence),
                "commandHash": command_hash,
                "sourceDecisionHash": source.content_hash,
                "priorAmendmentHash": head.content_hash if head else None,
            },
            idempotency_key=key,
            sealed_at=timezone.now(),
            published_by=self.actor_user_id,
        ).seal()
        event_name = (
            EVENT_FINAL_DECISION_CORRECTED
            if kind == HrDoubleTeacherFinalDecisionAmendment.Kind.CORRECTION
            else EVENT_FINAL_DECISION_REVOKED
        )
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=event_name,
            correlation_id=f"hr09-final-decision:{amendment.id}",
            payload={
                "decisionId": str(source.id),
                "amendmentId": str(amendment.id),
                "kind": amendment.kind,
                "contentHash": amendment.content_hash,
                "sealedAt": amendment.sealed_at.isoformat(),
                "replacement": normalized,
                "effectReceipt": effect_receipt,
            },
        )
        return FinalDecisionAuthorityResult(amendment, False)

    @transaction.atomic
    def correct(
        self,
        decision_id,
        *,
        idempotency_key: str,
        reason: str,
        authority_ref: str,
        replacement: dict,
        evidence: dict,
    ) -> FinalDecisionAuthorityResult:
        return self._append(
            decision_id,
            kind=HrDoubleTeacherFinalDecisionAmendment.Kind.CORRECTION,
            idempotency_key=idempotency_key,
            reason=reason,
            authority_ref=authority_ref,
            replacement=replacement,
            evidence=evidence,
        )

    @transaction.atomic
    def revoke(
        self,
        decision_id,
        *,
        idempotency_key: str,
        reason: str,
        authority_ref: str,
        evidence: dict,
    ) -> FinalDecisionAuthorityResult:
        return self._append(
            decision_id,
            kind=HrDoubleTeacherFinalDecisionAmendment.Kind.REVOCATION,
            idempotency_key=idempotency_key,
            reason=reason,
            authority_ref=authority_ref,
            replacement={},
            evidence=evidence,
        )
