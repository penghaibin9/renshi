"""Authority-only correction and void flows for signed HR07 versions.

Neither operation edits or deletes signed content.  A correction appends a new
signed/effective version and seals the old version as VOID; a void appends an
authority receipt and removes the invalid version from the current projection.
"""

from __future__ import annotations

import hashlib
import json

from django.db import transaction
from django.utils import timezone

from horilla.hr_event_service import emit_registered_event
from hr_contracts.events import EVENT_AGREEMENT_CORRECTED, EVENT_AGREEMENT_VOIDED
from hr_contracts.models import (
    HrContractAgreement,
    HrContractVersion,
    HrContractVersionAction,
)
from hr_contracts.services.agreement_service import AgreementService, ContractServiceError
from hr_contracts.services.document_binding import (
    ContractDocumentBindingError,
    bind_signed_document_reference,
)


def _request_hash(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


class ContractVersionActionService:
    def __init__(self, tenant_id: int, actor_user_id: int | None = None):
        if not tenant_id:
            raise ContractServiceError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    @staticmethod
    def _required(value, code: str, message: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ContractServiceError(code, message)
        return normalized

    def _existing(self, *, idempotency_key: str, expected_hash: str):
        item = (
            HrContractVersionAction.objects.select_related("successor_version")
            .filter(tenant_id=self.tenant_id, idempotency_key=idempotency_key)
            .first()
        )
        if item is None:
            return None
        if item.request_hash != expected_hash:
            raise ContractServiceError(
                "CONTRACT_IDEMPOTENCY_CONFLICT",
                "idempotency key already belongs to another version action",
            )
        return item

    def _locked_authority(self, *, agreement_id, source_version_id):
        agreement = (
            HrContractAgreement.objects.select_for_update()
            .filter(id=agreement_id, tenant_id=self.tenant_id)
            .first()
        )
        if agreement is None:
            raise ContractServiceError("CONTRACT_NOT_FOUND", "agreement not found inside tenant")
        source = (
            HrContractVersion.objects.select_for_update()
            .filter(
                id=source_version_id,
                tenant_id=self.tenant_id,
                agreement_id=agreement.id,
            )
            .first()
        )
        if source is None:
            raise ContractServiceError(
                "CONTRACT_VERSION_NOT_FOUND", "contract version not found inside tenant/agreement"
            )
        if source.version_no != agreement.current_version_no:
            raise ContractServiceError(
                "CONTRACT_VERSION_CONFLICT", "only the current formal version may be corrected or voided"
            )
        if source.status not in {
            HrContractVersion.Status.SIGNED,
            HrContractVersion.Status.EFFECTIVE,
        }:
            raise ContractServiceError(
                "CONTRACT_VERSION_INVALID_STATE",
                f"version status {source.status} cannot be corrected or voided",
            )
        return agreement, source

    @transaction.atomic
    def correct(
        self,
        *,
        agreement_id,
        source_version_id,
        content_snapshot: dict,
        signed_at,
        signed_document_ref: str,
        reason: str,
        evidence_ref: str,
        authority_ref: str,
        idempotency_key: str,
    ) -> HrContractVersionAction:
        if not isinstance(content_snapshot, dict) or not content_snapshot:
            raise ContractServiceError(
                "CONTRACT_CONTENT_REQUIRED", "corrected signed content snapshot is required"
            )
        signed_document_ref = self._required(
            signed_document_ref,
            "CONTRACT_SIGNED_DOCUMENT_REQUIRED",
            "corrected signed document reference is required",
        )
        reason = self._required(reason, "CONTRACT_CORRECTION_REASON_REQUIRED", "correction reason is required")
        evidence_ref = self._required(
            evidence_ref, "CONTRACT_CORRECTION_EVIDENCE_REQUIRED", "correction evidence is required"
        )
        authority_ref = self._required(
            authority_ref, "CONTRACT_CORRECTION_AUTHORITY_REQUIRED", "correction authority is required"
        )
        idempotency_key = self._required(
            idempotency_key, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required"
        )
        payload = {
            "kind": HrContractVersionAction.Kind.CORRECTION,
            "agreementId": str(agreement_id),
            "sourceVersionId": str(source_version_id),
            "contentSnapshot": content_snapshot,
            "signedAt": signed_at,
            "signedDocumentRef": signed_document_ref,
            "reason": reason,
            "evidenceRef": evidence_ref,
            "authorityRef": authority_ref,
        }
        digest = _request_hash(payload)
        existing = self._existing(idempotency_key=idempotency_key, expected_hash=digest)
        if existing is not None:
            return existing

        agreement, source = self._locked_authority(
            agreement_id=agreement_id, source_version_id=source_version_id
        )
        # Re-check behind the agreement lock so concurrent retries cannot branch.
        existing = self._existing(idempotency_key=idempotency_key, expected_hash=digest)
        if existing is not None:
            return existing

        next_no = source.version_no + 1
        successor = HrContractVersion.objects.create(
            tenant_id=self.tenant_id,
            agreement=agreement,
            version_no=next_no,
            version_type=HrContractVersion.VersionType.CORRECTION,
            effective_from=source.effective_from,
            effective_to=source.effective_to,
            signed_at=signed_at,
            signed_document_ref=signed_document_ref,
            content_snapshot_json=content_snapshot,
            content_hash=AgreementService._content_hash(content_snapshot),
            status=source.status,
            supersedes_version_id=source.id,
            source_business_type="CORRECTION",
            source_business_id=idempotency_key,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        try:
            bind_signed_document_reference(
                tenant_id=self.tenant_id,
                agreement_id=agreement.id,
                version=successor,
                signed_document_ref=signed_document_ref,
                actor_id=self.actor_user_id,
            )
        except ContractDocumentBindingError as exc:
            raise ContractServiceError(
                "CONTRACT_SIGNED_DOCUMENT_INVALID", str(exc)
            ) from exc
        source.status = HrContractVersion.Status.VOID
        source.updated_by = self.actor_user_id
        source.save(update_fields=["status", "updated_by", "updated_at"])

        agreement.current_version_no = next_no
        agreement.status = (
            HrContractAgreement.Status.ACTIVE
            if successor.status == HrContractVersion.Status.EFFECTIVE
            else HrContractAgreement.Status.SIGNED_WAITING_EFFECTIVE
        )
        agreement.updated_by = self.actor_user_id
        agreement.save(update_fields=["current_version_no", "status", "updated_by", "updated_at"])

        action = HrContractVersionAction.objects.create(
            tenant_id=self.tenant_id,
            agreement=agreement,
            source_version=source,
            successor_version=successor,
            kind=HrContractVersionAction.Kind.CORRECTION,
            reason=reason,
            evidence_ref=evidence_ref,
            authority_ref=authority_ref,
            authority_receipt_json={
                "actorUserId": self.actor_user_id,
                "sourceContentHash": source.content_hash,
                "successorContentHash": successor.content_hash,
            },
            idempotency_key=idempotency_key,
            request_hash=digest,
            sealed_at=timezone.now(),
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=EVENT_AGREEMENT_CORRECTED,
            correlation_id=str(action.id),
            payload={
                "agreementId": str(agreement.id),
                "sourceVersionId": str(source.id),
                "successorVersionId": str(successor.id),
                "successorVersionNo": successor.version_no,
                "sourceContentHash": source.content_hash,
                "successorContentHash": successor.content_hash,
                "authorityActionId": str(action.id),
            },
        )
        return action

    @transaction.atomic
    def void(
        self,
        *,
        agreement_id,
        source_version_id,
        reason: str,
        evidence_ref: str,
        authority_ref: str,
        idempotency_key: str,
    ) -> HrContractVersionAction:
        reason = self._required(reason, "CONTRACT_VOID_REASON_REQUIRED", "void reason is required")
        evidence_ref = self._required(
            evidence_ref, "CONTRACT_VOID_EVIDENCE_REQUIRED", "void evidence is required"
        )
        authority_ref = self._required(
            authority_ref, "CONTRACT_VOID_AUTHORITY_REQUIRED", "void authority is required"
        )
        idempotency_key = self._required(
            idempotency_key, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required"
        )
        payload = {
            "kind": HrContractVersionAction.Kind.VOID,
            "agreementId": str(agreement_id),
            "sourceVersionId": str(source_version_id),
            "reason": reason,
            "evidenceRef": evidence_ref,
            "authorityRef": authority_ref,
        }
        digest = _request_hash(payload)
        existing = self._existing(idempotency_key=idempotency_key, expected_hash=digest)
        if existing is not None:
            return existing

        agreement, source = self._locked_authority(
            agreement_id=agreement_id, source_version_id=source_version_id
        )
        existing = self._existing(idempotency_key=idempotency_key, expected_hash=digest)
        if existing is not None:
            return existing

        source.status = HrContractVersion.Status.VOID
        source.updated_by = self.actor_user_id
        source.save(update_fields=["status", "updated_by", "updated_at"])
        agreement.status = HrContractAgreement.Status.ARCHIVED
        agreement.current_version_no = 0
        agreement.updated_by = self.actor_user_id
        agreement.save(update_fields=["status", "current_version_no", "updated_by", "updated_at"])

        action = HrContractVersionAction.objects.create(
            tenant_id=self.tenant_id,
            agreement=agreement,
            source_version=source,
            kind=HrContractVersionAction.Kind.VOID,
            reason=reason,
            evidence_ref=evidence_ref,
            authority_ref=authority_ref,
            authority_receipt_json={
                "actorUserId": self.actor_user_id,
                "sourceContentHash": source.content_hash,
            },
            idempotency_key=idempotency_key,
            request_hash=digest,
            sealed_at=timezone.now(),
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=EVENT_AGREEMENT_VOIDED,
            correlation_id=str(action.id),
            payload={
                "agreementId": str(agreement.id),
                "sourceVersionId": str(source.id),
                "sourceContentHash": source.content_hash,
                "authorityActionId": str(action.id),
            },
        )
        return action
