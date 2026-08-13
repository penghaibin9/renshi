"""HR18 formal reporting snapshot lifecycle.

A submission snapshot is immutable payload identity. Validation is fail-closed:
formal reporting requires a trusted COMPLETE AsOfEvidenceSnapshot matching the
same tenant, definition version and as-of date. Missing/partial/unavailable
history can never be normalized into a valid formal submission.
"""

from __future__ import annotations

from typing import Optional

from django.db import transaction
from django.utils import timezone

from hr_data.models import AsOfEvidenceSnapshot, SubmissionSnapshot


class SubmissionLifecycleError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class SubmissionLifecycleService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise SubmissionLifecycleError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = tenant_id
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

    def _require_asof_evidence(self, snapshot: SubmissionSnapshot) -> AsOfEvidenceSnapshot:
        scope = snapshot.scope_json if isinstance(snapshot.scope_json, dict) else {}
        evidence_id = scope.get("asOfEvidenceId")
        if not evidence_id:
            raise SubmissionLifecycleError(
                "SUBMISSION_ASOF_EVIDENCE_REQUIRED",
                "formal submission validation requires asOfEvidenceId",
            )
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
        if not evidence.evidence_hash or len(evidence.evidence_hash) != 64:
            raise SubmissionLifecycleError(
                "SUBMISSION_ASOF_EVIDENCE_HASH_INVALID",
                "complete as-of evidence requires a 64-character evidence hash",
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
        if not snapshot.payload_hash or len(snapshot.payload_hash) != 64:
            raise SubmissionLifecycleError(
                "SUBMISSION_PAYLOAD_HASH_INVALID",
                "validated submission requires a 64-character payload hash",
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
        snapshot = self._lock(submission_id)
        if snapshot.status != SubmissionSnapshot.Status.APPROVED:
            raise SubmissionLifecycleError(
                "SUBMISSION_INVALID_STATE",
                f"submission status {snapshot.status} cannot transition to SUBMITTED",
            )
        snapshot.status = SubmissionSnapshot.Status.SUBMITTED
        snapshot.submitted_at = timezone.now()
        snapshot.updated_by = self.actor_user_id
        snapshot.save(
            update_fields=["status", "submitted_at", "updated_by", "updated_at"]
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
        if not receipt_ref.strip():
            raise SubmissionLifecycleError(
                "SUBMISSION_RECEIPT_REQUIRED",
                "receipt_ref is required for an external submission result",
            )
        snapshot.status = (
            SubmissionSnapshot.Status.ACCEPTED if accepted else SubmissionSnapshot.Status.REJECTED
        )
        snapshot.receipt_ref = receipt_ref.strip()
        snapshot.updated_by = self.actor_user_id
        snapshot.save(
            update_fields=["status", "receipt_ref", "updated_by", "updated_at"]
        )
        return snapshot
