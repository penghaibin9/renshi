"""Trusted, durable dispatch boundary for HR18 formal submissions.

HTTP only appends a database job. Workers claim a lease, call the configured
adapter outside transactions, then atomically persist the verified adapter
result, submission transition and append-only audit event. Every retry gets
the same idempotency key; the external platform must enforce that key for
end-to-end exactly-once delivery.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string

from hr_data.models import (
    SubmissionDispatchAttempt,
    SubmissionDispatchEvent,
    SubmissionDispatchJob,
    SubmissionSnapshot,
    SubmissionTrustedReceipt,
)

SCHEMA_VERSION = "hr18.submission.1"
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_LEASE_SECONDS = 300
RETRY_BASE_SECONDS = 60
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class SubmissionDispatchError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class SubmissionDispatchResult:
    snapshot: SubmissionSnapshot
    queued: bool
    dispatch_ref: str
    error: str = ""


@dataclass(frozen=True)
class SubmissionWorkerResult:
    job: SubmissionDispatchJob
    submitted: bool
    retry_scheduled: bool
    dead: bool


def _canonical(value) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _digest(value) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


class SubmissionDispatchService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise SubmissionDispatchError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    @staticmethod
    def _provider_path() -> str:
        return str(getattr(settings, "HR18_SUBMISSION_DISPATCH_PROVIDER", "") or "").strip()

    @staticmethod
    def _provider_key() -> str:
        key = str(
            getattr(settings, "HR18_SUBMISSION_DISPATCH_PROVIDER_KEY", "DEFAULT")
            or ""
        ).strip().upper()
        if not key or len(key) > 64:
            raise SubmissionDispatchError(
                "SUBMISSION_PROVIDER_KEY_INVALID", "submission provider key is invalid"
            )
        return key

    def _load_provider(self):
        path = self._provider_path()
        if not path:
            raise SubmissionDispatchError(
                "SUBMISSION_DISPATCH_UNAVAILABLE",
                "no trusted HR18 submission dispatch adapter is registered",
            )
        try:
            provider = import_string(path)
            return provider() if isinstance(provider, type) else provider
        except Exception as exc:
            raise SubmissionDispatchError(
                "SUBMISSION_DISPATCH_UNAVAILABLE",
                f"submission dispatch adapter cannot be loaded: {type(exc).__name__}",
            ) from exc

    def _snapshot(self, submission_id, *, lock=False):
        manager = SubmissionSnapshot.objects.select_for_update() if lock else SubmissionSnapshot.objects
        snapshot = manager.filter(id=submission_id, tenant_id=self.tenant_id).first()
        if snapshot is None:
            raise SubmissionDispatchError("SUBMISSION_NOT_FOUND", "submission snapshot not found")
        return snapshot

    @staticmethod
    def _manifest(snapshot: SubmissionSnapshot) -> dict:
        return {
            "tenantId": int(snapshot.tenant_id),
            "submissionId": str(snapshot.id),
            "submissionNo": snapshot.submission_no,
            "schemaVersion": SCHEMA_VERSION,
            "definitionKind": snapshot.definition_kind,
            "definitionCode": snapshot.definition_code,
            "definitionVersion": int(snapshot.definition_version),
            "asOfDate": snapshot.as_of_date.isoformat(),
            "scope": snapshot.scope_json,
            "payloadHash": snapshot.payload_hash.lower(),
        }

    @staticmethod
    def _job_identity(snapshot: SubmissionSnapshot, provider_key: str) -> dict:
        manifest = SubmissionDispatchService._manifest(snapshot)
        return {
            "providerKey": provider_key,
            "tenantId": manifest["tenantId"],
            "submissionId": manifest["submissionId"],
            "schemaVersion": manifest["schemaVersion"],
            "definitionVersion": manifest["definitionVersion"],
            "payloadHash": manifest["payloadHash"],
        }

    @staticmethod
    def _event(*, job, event_type, event_key, actor_user_id=None):
        payload = {
            "tenantId": int(job.tenant_id),
            "submissionId": str(job.submission_id),
            "jobId": str(job.id),
            "eventType": event_type,
            "eventKey": event_key,
            "payloadHash": job.payload_hash,
        }
        return SubmissionDispatchEvent.objects.create(
            tenant_id=job.tenant_id,
            submission_id=job.submission_id,
            job_id=job.id,
            event_type=event_type,
            event_key=event_key,
            event_hash=_digest(payload),
            occurred_at=timezone.now(),
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )

    @transaction.atomic
    def queue(self, submission_id) -> SubmissionDispatchResult:
        snapshot = self._snapshot(submission_id, lock=True)
        existing = (
            SubmissionDispatchJob.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, submission_id=snapshot.id)
            .first()
        )
        if existing is not None:
            self._assert_frozen_identity(existing, snapshot)
            return SubmissionDispatchResult(
                snapshot=snapshot,
                queued=False,
                dispatch_ref=snapshot.dispatch_ref or f"job:{existing.id}",
                error=(
                    snapshot.dispatch_error or "submission dispatch exhausted retries"
                    if existing.status
                    in {
                        SubmissionDispatchJob.Status.RETRY_WAIT,
                        SubmissionDispatchJob.Status.DEAD,
                    }
                    else ""
                ),
            )
        # Configuration is resolved before creating any new authority state.
        self._load_provider()
        provider_key = self._provider_key()
        identity = self._job_identity(snapshot, provider_key)
        request_hash = _digest(identity)
        idempotency_key = f"hr18:{self.tenant_id}:{snapshot.id}:{snapshot.payload_hash.lower()}"
        if snapshot.status not in {
            SubmissionSnapshot.Status.APPROVED,
            SubmissionSnapshot.Status.DISPATCH_FAILED,
        }:
            raise SubmissionDispatchError(
                "SUBMISSION_INVALID_STATE",
                f"submission status {snapshot.status} cannot be queued for dispatch",
            )
        job_id = uuid.uuid4()
        job = SubmissionDispatchJob.objects.create(
            id=job_id,
            tenant_id=self.tenant_id,
            submission=snapshot,
            provider_key=provider_key,
            schema_version=SCHEMA_VERSION,
            definition_version=snapshot.definition_version,
            payload_hash=snapshot.payload_hash.lower(),
            request_hash=request_hash,
            idempotency_key=idempotency_key,
            max_attempts=DEFAULT_MAX_ATTEMPTS,
            status=SubmissionDispatchJob.Status.QUEUED,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        local_ref = f"job:{job.id}"
        snapshot.status = SubmissionSnapshot.Status.DISPATCH_QUEUED
        snapshot.dispatch_ref = local_ref
        snapshot.dispatch_requested_at = timezone.now()
        snapshot.dispatch_error = ""
        snapshot.updated_by = self.actor_user_id
        snapshot.save(
            update_fields=[
                "status", "dispatch_ref", "dispatch_requested_at", "dispatch_error",
                "updated_by", "updated_at",
            ]
        )
        self._event(
            job=job,
            event_type="hr.data.submission.queued",
            event_key=f"submission:{snapshot.id}:queued",
            actor_user_id=self.actor_user_id,
        )
        return SubmissionDispatchResult(snapshot=snapshot, queued=True, dispatch_ref=local_ref)

    def _assert_frozen_identity(self, job, snapshot):
        identity = self._job_identity(snapshot, job.provider_key)
        if (
            snapshot.tenant_id != self.tenant_id
            or job.submission_id != snapshot.id
            or job.schema_version != SCHEMA_VERSION
            or job.definition_version != snapshot.definition_version
            or job.payload_hash != snapshot.payload_hash.lower()
            or job.request_hash != _digest(identity)
        ):
            raise SubmissionDispatchError(
                "SUBMISSION_DISPATCH_IDENTITY_MISMATCH",
                "dispatch job no longer matches the frozen submission identity",
            )

    @transaction.atomic
    def _claim(self, job_id, *, lease_seconds=DEFAULT_LEASE_SECONDS):
        now = timezone.now()
        job = (
            SubmissionDispatchJob.objects.select_for_update()
            .select_related("submission")
            .filter(id=job_id, tenant_id=self.tenant_id)
            .first()
        )
        if job is None:
            raise SubmissionDispatchError("SUBMISSION_DISPATCH_JOB_NOT_FOUND", "job not found")
        eligible = job.status in {
            SubmissionDispatchJob.Status.QUEUED,
            SubmissionDispatchJob.Status.RETRY_WAIT,
        }
        expired = (
            job.status == SubmissionDispatchJob.Status.LEASED
            and job.lease_expires_at is not None
            and job.lease_expires_at <= now
        )
        if not eligible and not expired:
            raise SubmissionDispatchError(
                "SUBMISSION_DISPATCH_NOT_CLAIMABLE", f"job status {job.status} is not claimable"
            )
        if job.next_attempt_at and job.next_attempt_at > now:
            raise SubmissionDispatchError("SUBMISSION_DISPATCH_RETRY_NOT_DUE", "retry is not due")
        self._assert_frozen_identity(job, job.submission)
        if job.submission.status == SubmissionSnapshot.Status.DISPATCH_FAILED:
            job.submission.status = SubmissionSnapshot.Status.DISPATCH_QUEUED
            job.submission.dispatch_error = ""
            job.submission.dispatch_requested_at = now
            job.submission.updated_by = self.actor_user_id
            job.submission.save(
                update_fields=[
                    "status", "dispatch_error", "dispatch_requested_at", "updated_by", "updated_at",
                ]
            )
        if job.submission.status != SubmissionSnapshot.Status.DISPATCH_QUEUED:
            raise SubmissionDispatchError(
                "SUBMISSION_DISPATCH_STATE_MISMATCH",
                "submission is not queued for this dispatch job",
            )
        lease_token = uuid.uuid4()
        job.status = SubmissionDispatchJob.Status.LEASED
        job.lease_token = lease_token
        job.lease_expires_at = now + timedelta(seconds=lease_seconds)
        job.attempt_count += 1
        job.updated_by = self.actor_user_id
        job.save(
            update_fields=[
                "status", "lease_token", "lease_expires_at", "attempt_count",
                "updated_by", "updated_at",
            ]
        )
        return job, lease_token, now, self._manifest(job.submission)

    @staticmethod
    def _dispatch_callable(provider):
        method = getattr(provider, "dispatch", None)
        if callable(method):
            return method
        if callable(provider):
            return provider
        raise SubmissionDispatchError(
            "SUBMISSION_DISPATCH_CONTRACT_INVALID", "adapter has no dispatch method"
        )

    def _verified_dispatch(self, response, *, job):
        if not isinstance(response, Mapping) or response.get("dispatched") is not True:
            raise SubmissionDispatchError(
                "SUBMISSION_DISPATCH_CONTRACT_INVALID",
                "trusted adapter must return dispatched=true",
            )
        expected = {
            "tenantId": self.tenant_id,
            "submissionId": str(job.submission_id),
            "schemaVersion": job.schema_version,
            "definitionVersion": job.definition_version,
            "payloadHash": job.payload_hash,
        }
        for field, value in expected.items():
            candidate = response.get(field)
            if field in {"tenantId", "definitionVersion"}:
                try:
                    candidate = int(candidate)
                except (TypeError, ValueError):
                    candidate = None
            else:
                candidate = str(candidate or "")
            if candidate != value:
                raise SubmissionDispatchError(
                    "SUBMISSION_DISPATCH_RECEIPT_MISMATCH",
                    f"adapter dispatch receipt has mismatched {field}",
                )
        dispatch_ref = str(response.get("dispatchRef") or "").strip()
        if not dispatch_ref or len(dispatch_ref) > 255:
            raise SubmissionDispatchError(
                "SUBMISSION_DISPATCH_REF_INVALID", "adapter dispatchRef is invalid"
            )
        provider_version = str(response.get("providerVersion") or "").strip()
        if not provider_version or len(provider_version) > 64:
            raise SubmissionDispatchError(
                "SUBMISSION_PROVIDER_VERSION_INVALID", "adapter providerVersion is invalid"
            )
        response_hash = _digest(
            {**expected, "dispatchRef": dispatch_ref, "providerVersion": provider_version}
        )
        return dispatch_ref, provider_version, response_hash

    def dispatch(self, job_id) -> SubmissionWorkerResult:
        provider = self._load_provider()  # unknown provider leaves job unleased
        job, lease_token, started_at, manifest = self._claim(job_id)
        try:
            response = self._dispatch_callable(provider)(
                tenant_id=self.tenant_id,
                submission_manifest=manifest,
                idempotency_key=job.idempotency_key,
                actor_user_id=self.actor_user_id,
            )
            dispatch_ref, provider_version, response_hash = self._verified_dispatch(
                response, job=job
            )
        except Exception as exc:
            code = exc.code if isinstance(exc, SubmissionDispatchError) else f"PROVIDER_{type(exc).__name__.upper()}"
            return self._record_failure(
                job.id, lease_token=lease_token, started_at=started_at, error_code=code
            )
        return self._record_success(
            job.id,
            lease_token=lease_token,
            started_at=started_at,
            dispatch_ref=dispatch_ref,
            provider_version=provider_version,
            response_hash=response_hash,
        )

    @transaction.atomic
    def _leased(self, job_id, lease_token):
        job = (
            SubmissionDispatchJob.objects.select_for_update()
            .select_related("submission")
            .filter(id=job_id, tenant_id=self.tenant_id)
            .first()
        )
        if job is None or job.status != SubmissionDispatchJob.Status.LEASED or job.lease_token != lease_token:
            raise SubmissionDispatchError(
                "SUBMISSION_DISPATCH_LEASE_LOST", "worker lease is no longer current"
            )
        self._assert_frozen_identity(job, job.submission)
        return job

    @transaction.atomic
    def _record_success(
        self, job_id, *, lease_token, started_at, dispatch_ref, provider_version, response_hash
    ):
        job = self._leased(job_id, lease_token)
        now = timezone.now()
        SubmissionDispatchAttempt.objects.create(
            tenant_id=self.tenant_id,
            job=job,
            attempt_no=job.attempt_count,
            idempotency_key=job.idempotency_key,
            status=SubmissionDispatchAttempt.Status.DISPATCHED,
            provider_version=provider_version,
            dispatch_ref=dispatch_ref,
            response_hash=response_hash,
            started_at=started_at,
            finished_at=now,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        job.status = SubmissionDispatchJob.Status.SUBMITTED
        job.dispatch_ref = dispatch_ref
        job.provider_version = provider_version
        job.submitted_at = now
        job.lease_token = None
        job.lease_expires_at = None
        job.next_attempt_at = None
        job.last_error_code = ""
        job.updated_by = self.actor_user_id
        job.save(
            update_fields=[
                "status", "dispatch_ref", "provider_version", "submitted_at", "lease_token",
                "lease_expires_at", "next_attempt_at", "last_error_code", "updated_by", "updated_at",
            ]
        )
        snapshot = job.submission
        snapshot.status = SubmissionSnapshot.Status.SUBMITTED
        snapshot.submitted_at = now
        snapshot.dispatch_error = ""
        snapshot.updated_by = self.actor_user_id
        snapshot.save(
            update_fields=["status", "submitted_at", "dispatch_error", "updated_by", "updated_at"]
        )
        self._event(
            job=job,
            event_type="hr.data.submission.submitted",
            event_key=f"submission:{snapshot.id}:submitted",
            actor_user_id=self.actor_user_id,
        )
        return SubmissionWorkerResult(job, True, False, False)

    @transaction.atomic
    def _record_failure(self, job_id, *, lease_token, started_at, error_code):
        job = self._leased(job_id, lease_token)
        now = timezone.now()
        terminal = job.attempt_count >= job.max_attempts
        SubmissionDispatchAttempt.objects.create(
            tenant_id=self.tenant_id,
            job=job,
            attempt_no=job.attempt_count,
            idempotency_key=job.idempotency_key,
            status=(
                SubmissionDispatchAttempt.Status.TERMINAL_FAILURE
                if terminal else SubmissionDispatchAttempt.Status.RETRYABLE_FAILURE
            ),
            error_code=str(error_code or "SUBMISSION_DISPATCH_FAILED")[:64],
            started_at=started_at,
            finished_at=now,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        job.status = SubmissionDispatchJob.Status.DEAD if terminal else SubmissionDispatchJob.Status.RETRY_WAIT
        job.next_attempt_at = None if terminal else now + timedelta(
            seconds=RETRY_BASE_SECONDS * (2 ** (job.attempt_count - 1))
        )
        job.lease_token = None
        job.lease_expires_at = None
        job.last_error_code = str(error_code or "SUBMISSION_DISPATCH_FAILED")[:64]
        job.completed_at = now if terminal else None
        job.updated_by = self.actor_user_id
        job.save(
            update_fields=[
                "status", "next_attempt_at", "lease_token", "lease_expires_at",
                "last_error_code", "completed_at", "updated_by", "updated_at",
            ]
        )
        snapshot = job.submission
        snapshot.status = SubmissionSnapshot.Status.DISPATCH_FAILED
        snapshot.dispatch_error = "submission dispatch failed"
        snapshot.updated_by = self.actor_user_id
        snapshot.save(update_fields=["status", "dispatch_error", "updated_by", "updated_at"])
        suffix = "dead" if terminal else f"retry:{job.attempt_count}"
        self._event(
            job=job,
            event_type=(
                "hr.data.submission.dispatch_dead"
                if terminal else "hr.data.submission.dispatch_retry_scheduled"
            ),
            event_key=f"submission:{snapshot.id}:{suffix}",
            actor_user_id=self.actor_user_id,
        )
        return SubmissionWorkerResult(job, False, not terminal, terminal)

    def _verify_receipt(self, provider, *, submission_manifest, receipt_payload):
        verifier = getattr(provider, "verify_receipt", None)
        if not callable(verifier):
            raise SubmissionDispatchError(
                "SUBMISSION_RECEIPT_VERIFIER_UNAVAILABLE",
                "configured adapter cannot verify signed receipts",
            )
        try:
            verified = verifier(
                tenant_id=self.tenant_id,
                submission_manifest=submission_manifest,
                receipt_payload=receipt_payload,
            )
        except Exception as exc:
            raise SubmissionDispatchError(
                "SUBMISSION_RECEIPT_VERIFICATION_FAILED",
                f"receipt verification failed: {type(exc).__name__}",
            ) from exc
        if not isinstance(verified, Mapping) or verified.get("verified") is not True:
            raise SubmissionDispatchError(
                "SUBMISSION_RECEIPT_UNTRUSTED", "adapter did not verify the receipt"
            )
        return verified

    def record_verified_receipt(self, submission_id, *, receipt_payload) -> SubmissionSnapshot:
        if not isinstance(receipt_payload, Mapping) or not receipt_payload:
            raise SubmissionDispatchError(
                "SUBMISSION_RECEIPT_PAYLOAD_INVALID", "providerReceipt must be an object"
            )
        provider = self._load_provider()
        snapshot = self._snapshot(submission_id)
        job = SubmissionDispatchJob.objects.filter(
            tenant_id=self.tenant_id, submission_id=snapshot.id
        ).first()
        if job is None:
            raise SubmissionDispatchError(
                "SUBMISSION_DISPATCH_JOB_NOT_FOUND", "dispatch job not found"
            )
        self._assert_frozen_identity(job, snapshot)
        verified = self._verify_receipt(
            provider,
            submission_manifest=self._manifest(snapshot),
            receipt_payload=receipt_payload,
        )
        return self._apply_verified_receipt(job.id, verified=verified)

    @transaction.atomic
    def _apply_verified_receipt(self, job_id, *, verified) -> SubmissionSnapshot:
        job = (
            SubmissionDispatchJob.objects.select_for_update()
            .select_related("submission")
            .filter(id=job_id, tenant_id=self.tenant_id)
            .first()
        )
        if job is None:
            raise SubmissionDispatchError("SUBMISSION_DISPATCH_JOB_NOT_FOUND", "job not found")
        snapshot = job.submission
        self._assert_frozen_identity(job, snapshot)
        expected = {
            "tenantId": self.tenant_id,
            "submissionId": str(snapshot.id),
            "schemaVersion": job.schema_version,
            "definitionVersion": job.definition_version,
            "payloadHash": job.payload_hash,
            "dispatchRef": job.dispatch_ref,
        }
        for field, value in expected.items():
            candidate = verified.get(field)
            if field in {"tenantId", "definitionVersion"}:
                try:
                    candidate = int(candidate)
                except (TypeError, ValueError):
                    candidate = None
            else:
                candidate = str(candidate or "")
            if candidate != value:
                raise SubmissionDispatchError(
                    "SUBMISSION_RECEIPT_BINDING_MISMATCH",
                    f"trusted receipt has mismatched {field}",
                )
        accepted = verified.get("accepted")
        if not isinstance(accepted, bool):
            raise SubmissionDispatchError(
                "SUBMISSION_RECEIPT_OUTCOME_INVALID", "verified accepted must be boolean"
            )
        receipt_ref = str(verified.get("receiptRef") or "").strip()
        provider_version = str(verified.get("providerVersion") or "").strip()
        receipt_hash = str(verified.get("receiptHash") or "").strip().lower()
        signature_key_id = str(verified.get("signatureKeyId") or "").strip()
        if not receipt_ref or len(receipt_ref) > 255:
            raise SubmissionDispatchError("SUBMISSION_RECEIPT_INVALID", "receiptRef is invalid")
        if not provider_version or len(provider_version) > 64:
            raise SubmissionDispatchError(
                "SUBMISSION_PROVIDER_VERSION_INVALID", "providerVersion is invalid"
            )
        if not _HASH_RE.fullmatch(receipt_hash) or not signature_key_id:
            raise SubmissionDispatchError(
                "SUBMISSION_RECEIPT_SIGNATURE_EVIDENCE_INVALID",
                "verified receipt requires receiptHash and signatureKeyId",
            )
        existing = SubmissionTrustedReceipt.objects.filter(
            tenant_id=self.tenant_id, submission_id=snapshot.id
        ).first()
        outcome = (
            SubmissionTrustedReceipt.Outcome.ACCEPTED
            if accepted else SubmissionTrustedReceipt.Outcome.REJECTED
        )
        if existing is not None:
            if (
                existing.receipt_hash != receipt_hash
                or existing.receipt_ref != receipt_ref
                or existing.outcome != outcome
            ):
                raise SubmissionDispatchError(
                    "SUBMISSION_RECEIPT_IDEMPOTENCY_CONFLICT",
                    "submission already has a different trusted receipt",
                )
            return snapshot
        if (
            job.status != SubmissionDispatchJob.Status.SUBMITTED
            or snapshot.status != SubmissionSnapshot.Status.SUBMITTED
        ):
            raise SubmissionDispatchError(
                "SUBMISSION_INVALID_STATE",
                "only a provider-confirmed submitted job can receive a receipt",
            )
        now = timezone.now()
        SubmissionTrustedReceipt.objects.create(
            tenant_id=self.tenant_id,
            submission=snapshot,
            job=job,
            provider_key=job.provider_key,
            provider_version=provider_version,
            schema_version=job.schema_version,
            definition_version=job.definition_version,
            payload_hash=job.payload_hash,
            dispatch_ref=job.dispatch_ref,
            receipt_ref=receipt_ref,
            outcome=outcome,
            receipt_hash=receipt_hash,
            signature_key_id=signature_key_id[:128],
            received_at=now,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        job.status = SubmissionDispatchJob.Status.ACCEPTED if accepted else SubmissionDispatchJob.Status.REJECTED
        job.completed_at = now
        job.updated_by = self.actor_user_id
        job.save(update_fields=["status", "completed_at", "updated_by", "updated_at"])
        snapshot.status = SubmissionSnapshot.Status.ACCEPTED if accepted else SubmissionSnapshot.Status.REJECTED
        snapshot.receipt_ref = receipt_ref
        snapshot.updated_by = self.actor_user_id
        snapshot.save(update_fields=["status", "receipt_ref", "updated_by", "updated_at"])
        self._event(
            job=job,
            event_type=("hr.data.submission.accepted" if accepted else "hr.data.submission.rejected"),
            event_key=f"submission:{snapshot.id}:receipt:{receipt_hash}",
            actor_user_id=self.actor_user_id,
        )
        if accepted and snapshot.parent_submission_id:
            parent = (
                SubmissionSnapshot.objects.select_for_update()
                .filter(id=snapshot.parent_submission_id, tenant_id=self.tenant_id)
                .first()
            )
            if parent is None or parent.status not in {
                SubmissionSnapshot.Status.ACCEPTED,
                SubmissionSnapshot.Status.REJECTED,
            }:
                raise SubmissionDispatchError(
                    "SUBMISSION_CORRECTION_PARENT_INVALID_STATE",
                    "correction parent cannot be superseded",
                )
            parent.status = SubmissionSnapshot.Status.CORRECTED
            parent.updated_by = self.actor_user_id
            parent.save(update_fields=["status", "updated_by", "updated_at"])
            self._event(
                job=job,
                event_type="hr.data.submission.corrected",
                event_key=f"submission:{parent.id}:corrected-by:{snapshot.id}",
                actor_user_id=self.actor_user_id,
            )
        return snapshot
