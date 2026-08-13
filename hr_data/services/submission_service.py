"""HR18 formal reporting snapshot lifecycle.

A submission snapshot is immutable payload identity. Creation derives the
formal definition/version/as-of identity from a tenant-owned AsOfEvidenceSnapshot;
callers cannot self-assert those fields. Validation is fail-closed: formal
reporting requires the same evidence to be COMPLETE with a trusted hash.

APPROVED is not SUBMITTED. Formal dispatch must first be durably queued by the
async dispatch service; only the worker owning the matching dispatch_ref may
confirm DISPATCH_QUEUED -> SUBMITTED. External receipt then owns the final
ACCEPTED/REJECTED result.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from django.db import transaction
from django.utils import timezone

from hr_data.models import AsOfEvidenceSnapshot, SubmissionSnapshot


_HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class SubmissionLifecycleError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class SubmissionCreateResult:
    snapshot: SubmissionSnapshot
    created: bool


class SubmissionLifecycleService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise SubmissionLifecycleError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    def _lock(self, submission_id) -> SubmissionSnapshot:
        snapshot = (
            SubmissionSnapshot.objects.select_for_update()
            .filter(id=submission_id, tenant_id=self.tenant_id)
            .first()
        )
        if snapshot is None:
            raise SubmissionLifecycleError("SUBMISSION_NOT_FOUND", "submission snapshot not found")
        return snapshot

    def _lock_evidence(self, evidence_id) -> AsOfEvidenceSnapshot:
        evidence = (
            AsOfEvidenceSnapshot.objects.select_for_update()
            .filter(id=evidence_id, tenant_id=self.tenant_id)
            .first()
        )
        if evidence is None:
            raise SubmissionLifecycleError(
                "SUBMISSION_ASOF_EVIDENCE_NOT_FOUND",
                "as-of evidence does not exist inside the current tenant",
            )
        return evidence

    @transaction.atomic
    def create_draft(
        self,
        *,
        submission_no: str,
        as_of_evidence_id,
        payload_hash: str,
        scope: Optional[dict] = None,
    ) -> SubmissionCreateResult:
        submission_no = str(submission_no or "").strip()
        if not submission_no:
            raise SubmissionLifecycleError(
                "SUBMISSION_NO_REQUIRED", "submission_no is required"
            )
        payload_hash = str(payload_hash or "").strip().lower()
        if not _HASH_RE.fullmatch(payload_hash):
            raise SubmissionLifecycleError(
                "SUBMISSION_PAYLOAD_HASH_INVALID",
                "payload_hash must be a 64-character hexadecimal SHA-256 value",
            )
        if not as_of_evidence_id:
            raise SubmissionLifecycleError(
                "SUBMISSION_ASOF_EVIDENCE_REQUIRED",
                "as_of_evidence_id is required",
            )
        scope = {} if scope is None else scope
        if not isinstance(scope, dict):
            raise SubmissionLifecycleError(
                "SUBMISSION_SCOPE_INVALID", "scope must be an object"
            )
        if "asOfEvidenceId" in scope:
            raise SubmissionLifecycleError(
                "SUBMISSION_SCOPE_RESERVED_KEY",
                "scope must not override asOfEvidenceId",
            )

        evidence = self._lock_evidence(as_of_evidence_id)
        frozen_scope = dict(scope)
        frozen_scope["asOfEvidenceId"] = str(evidence.id)

        existing = (
            SubmissionSnapshot.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, submission_no=submission_no)
            .first()
        )
        if existing is not None:
            if (
                existing.definition_code != evidence.definition_code
                or existing.definition_version != evidence.definition_version
                or existing.as_of_date != evidence.as_of_date
                or existing.payload_hash.lower() != payload_hash
                or existing.scope_json != frozen_scope
            ):
                raise SubmissionLifecycleError(
                    "SUBMISSION_IDEMPOTENCY_CONFLICT",
                    "submission_no already belongs to a different immutable payload",
                )
            return SubmissionCreateResult(existing, False)

        snapshot = SubmissionSnapshot.objects.create(
            tenant_id=self.tenant_id,
            submission_no=submission_no,
            definition_code=evidence.definition_code,
            definition_version=evidence.definition_version,
            as_of_date=evidence.as_of_date,
            scope_json=frozen_scope,
            payload_hash=payload_hash,
            status=SubmissionSnapshot.Status.DRAFT,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        return SubmissionCreateResult(snapshot, True)

    def _require_asof_evidence(self, snapshot: SubmissionSnapshot) -> AsOfEvidenceSnapshot:
        scope = snapshot.scope_json if isinstance(snapshot.scope_json, dict) else {}
        evidence_id = scope.get("asOfEvidenceId")
        if not evidence_id:
            raise SubmissionLifecycleError(
                "SUBMISSION_ASOF_EVIDENCE_REQUIRED",
                "formal submission validation requires asOfEvidenceId",
            )
        evidence = self._lock_evidence(evidence_id)
        if (
            evidence.definition_code != snapshot.definition_code
            or evidence.definition_version != snapshot.definition_version
            or evidence.as_of_date != snapshot.as_of_date
        ):
            raise SubmissionLifecycleError(
                "SUBMISSION_ASOF_EVIDENCE_MISMATCH",
                "as-of evidence does not match submission definition/version/date",
            )
        if evidence.status != AsOfEvidenceSnapshot.Status.COMPLETE:
            raise SubmissionLifecycleError(
                "SUBMISSION_ASOF_INCOMPLETE",
                f"as-of reconstruction status {evidence.status} cannot be formally submitted",
            )
        if not _HASH_RE.fullmatch(str(evidence.evidence_hash or "")):
            raise SubmissionLifecycleError(
                "SUBMISSION_ASOF_EVIDENCE_HASH_INVALID",
                "complete as-of evidence requires a 64-character hexadecimal evidence hash",
            )
        return evidence

    def _transition(self, snapshot: SubmissionSnapshot, *, expected: str, target: str):
        if snapshot.status != expected:
            raise SubmissionLifecycleError(
                "SUBMISSION_INVALID_STATE",
                f"submission status {snapshot.status} cannot transition to {target}",
            )
        snapshot.status = target
        snapshot.updated_by = self.actor_user_id
        snapshot.save(update_fields=["status", "updated_by", "updated_at"])
        return snapshot

    @transaction.atomic
    def validate(self, submission_id) -> SubmissionSnapshot:
        snapshot = self._lock(submission_id)
        if not _HASH_RE.fullmatch(str(snapshot.payload_hash or "")):
            raise SubmissionLifecycleError(
                "SUBMISSION_PAYLOAD_HASH_INVALID",
                "validated submission requires a 64-character hexadecimal payload hash",
            )
        if not snapshot.definition_code or not snapshot.definition_version:
            raise SubmissionLifecycleError(
                "SUBMISSION_DEFINITION_REQUIRED",
                "definition code and version are required before validation",
            )
        self._require_asof_evidence(snapshot)
        return self._transition(
            snapshot,
            expected=SubmissionSnapshot.Status.DRAFT,
            target=SubmissionSnapshot.Status.VALIDATED,
        )

    @transaction.atomic
    def approve(self, submission_id) -> SubmissionSnapshot:
        snapshot = self._lock(submission_id)
        return self._transition(
            snapshot,
            expected=SubmissionSnapshot.Status.VALIDATED,
            target=SubmissionSnapshot.Status.APPROVED,
        )

    @transaction.atomic
    def submit(self, submission_id) -> SubmissionSnapshot:
        # Compatibility guard: old direct callers must not bypass the async
        # dispatch authority introduced for formal reporting.
        self._lock(submission_id)
        raise SubmissionLifecycleError(
            "SUBMISSION_ASYNC_DISPATCH_REQUIRED",
            "formal submission must be queued through the async dispatch authority",
        )

    @transaction.atomic
    def confirm_dispatched(self, submission_id, *, dispatch_ref: str) -> SubmissionSnapshot:
        snapshot = self._lock(submission_id)
        dispatch_ref = str(dispatch_ref or "").strip()
        if snapshot.status != SubmissionSnapshot.Status.DISPATCH_QUEUED:
            raise SubmissionLifecycleError(
                "SUBMISSION_INVALID_STATE",
                f"submission status {snapshot.status} cannot be confirmed as submitted",
            )
        if not dispatch_ref or dispatch_ref != snapshot.dispatch_ref:
            raise SubmissionLifecycleError(
                "SUBMISSION_DISPATCH_REF_MISMATCH",
                "dispatch confirmation must match the queued dispatch_ref",
            )
        snapshot.status = SubmissionSnapshot.Status.SUBMITTED
        snapshot.submitted_at = timezone.now()
        snapshot.dispatch_error = ""
        snapshot.updated_by = self.actor_user_id
        snapshot.save(
            update_fields=[
                "status",
                "submitted_at",
                "dispatch_error",
                "updated_by",
                "updated_at",
            ]
        )
        return snapshot

    @transaction.atomic
    def record_dispatch_failure(
        self,
        submission_id,
        *,
        dispatch_ref: str,
        error: str,
    ) -> SubmissionSnapshot:
        snapshot = self._lock(submission_id)
        dispatch_ref = str(dispatch_ref or "").strip()
        if snapshot.status != SubmissionSnapshot.Status.DISPATCH_QUEUED:
            raise SubmissionLifecycleError(
                "SUBMISSION_INVALID_STATE",
                f"submission status {snapshot.status} cannot record dispatch failure",
            )
        if not dispatch_ref or dispatch_ref != snapshot.dispatch_ref:
            raise SubmissionLifecycleError(
                "SUBMISSION_DISPATCH_REF_MISMATCH",
                "dispatch failure must match the queued dispatch_ref",
            )
        snapshot.status = SubmissionSnapshot.Status.DISPATCH_FAILED
        snapshot.dispatch_error = str(error or "dispatch failed")[:2000]
        snapshot.updated_by = self.actor_user_id
        snapshot.save(
            update_fields=["status", "dispatch_error", "updated_by", "updated_at"]
        )
        return snapshot

    @transaction.atomic
    def record_receipt(self, submission_id, *, accepted: bool, receipt_ref: str) -> SubmissionSnapshot:
        snapshot = self._lock(submission_id)
        if snapshot.status != SubmissionSnapshot.Status.SUBMITTED:
            raise SubmissionLifecycleError(
                "SUBMISSION_INVALID_STATE",
                f"submission status {snapshot.status} cannot receive a receipt",
            )
        receipt_ref = str(receipt_ref or "").strip()
        if not receipt_ref:
            raise SubmissionLifecycleError(
                "SUBMISSION_RECEIPT_REQUIRED",
                "receipt_ref is required for an external submission result",
            )
        snapshot.status = (
            SubmissionSnapshot.Status.ACCEPTED if accepted else SubmissionSnapshot.Status.REJECTED
        )
        snapshot.receipt_ref = receipt_ref
        snapshot.updated_by = self.actor_user_id
        snapshot.save(
            update_fields=["status", "receipt_ref", "updated_by", "updated_at"]
        )
        return snapshot
