"""Durable HR18 dataset exchange and reconciliation authority.

Database transactions only claim or finalize work.  The provider call is made
between those transactions so a slow external target never holds row locks.
Every provider call receives a stable attempt idempotency key and a frozen
dataset manifest.  A stale worker cannot finalize a newer lease.
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
    ExchangeAttempt,
    ExchangeDatasetVersion,
    ExchangeDeadLetter,
    ExchangeJob,
    ExchangeReceipt,
    ExchangeReconciliation,
    ExchangeTargetMappingVersion,
)

_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")


class ExchangeError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class VersionOutcome:
    value: object
    created: bool


@dataclass(frozen=True)
class DispatchOutcome:
    job: ExchangeJob
    transmitted: bool
    retry_scheduled: bool
    dead_lettered: bool


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _code(value, label: str) -> str:
    normalized = str(value or "").strip().upper()
    if not _CODE.fullmatch(normalized):
        raise ExchangeError(f"EXCHANGE_{label}_INVALID", f"{label.lower()} is invalid")
    return normalized


def _sha256(value, label: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _HASH.fullmatch(normalized):
        raise ExchangeError(f"EXCHANGE_{label}_INVALID", f"{label.lower()} must be sha256")
    return normalized


class ExchangeDefinitionService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise ExchangeError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    @transaction.atomic
    def create_dataset_version(
        self,
        *,
        dataset_code,
        name,
        schema,
        source_snapshot,
        payload_ref,
        payload_hash,
        record_count,
        frozen_at=None,
    ) -> VersionOutcome:
        dataset_code = _code(dataset_code, "DATASET_CODE")
        name = str(name or "").strip()
        if not name:
            raise ExchangeError("EXCHANGE_DATASET_NAME_REQUIRED", "name is required")
        if not isinstance(schema, dict) or not schema:
            raise ExchangeError("EXCHANGE_SCHEMA_INVALID", "schema must be a non-empty object")
        if not isinstance(source_snapshot, dict) or not source_snapshot:
            raise ExchangeError(
                "EXCHANGE_SOURCE_SNAPSHOT_INVALID",
                "source_snapshot must contain immutable source receipts",
            )
        payload_ref = str(payload_ref or "").strip()
        if not payload_ref or len(payload_ref) > 255:
            raise ExchangeError("EXCHANGE_PAYLOAD_REF_INVALID", "payload_ref is invalid")
        payload_hash = _sha256(payload_hash, "PAYLOAD_HASH")
        if isinstance(record_count, bool) or not isinstance(record_count, int) or record_count < 0:
            raise ExchangeError("EXCHANGE_RECORD_COUNT_INVALID", "record_count is invalid")
        frozen_at = frozen_at or timezone.now()
        content = {
            "name": name,
            "schema": schema,
            "sourceSnapshot": source_snapshot,
            "payloadRef": payload_ref,
            "payloadHash": payload_hash,
            "recordCount": record_count,
            "frozenAt": frozen_at.isoformat(),
        }
        content_hash = _digest(content)
        existing = ExchangeDatasetVersion.objects.filter(
            tenant_id=self.tenant_id,
            dataset_code=dataset_code,
            content_hash=content_hash,
        ).first()
        if existing:
            return VersionOutcome(existing, False)
        previous = (
            ExchangeDatasetVersion.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, dataset_code=dataset_code)
            .order_by("-version_no")
            .first()
        )
        value = ExchangeDatasetVersion.objects.create(
            tenant_id=self.tenant_id,
            dataset_code=dataset_code,
            version_no=(previous.version_no + 1 if previous else 1),
            status="FROZEN",
            name=name,
            schema_json=schema,
            source_snapshot_json=source_snapshot,
            payload_ref=payload_ref,
            payload_hash=payload_hash,
            record_count=record_count,
            frozen_at=frozen_at,
            content_hash=content_hash,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        return VersionOutcome(value, True)

    @transaction.atomic
    def create_target_mapping_version(
        self,
        *,
        target_code,
        dataset_code,
        dataset_version,
        transport_kind,
        provider_key,
        mapping,
        expected_receipt=True,
    ) -> VersionOutcome:
        target_code = _code(target_code, "TARGET_CODE")
        dataset_code = _code(dataset_code, "DATASET_CODE")
        if isinstance(dataset_version, bool) or not isinstance(dataset_version, int) or dataset_version < 1:
            raise ExchangeError("EXCHANGE_DATASET_VERSION_INVALID", "dataset_version is invalid")
        dataset = ExchangeDatasetVersion.objects.select_for_update().filter(
            tenant_id=self.tenant_id,
            dataset_code=dataset_code,
            version_no=dataset_version,
            status="FROZEN",
        ).first()
        if dataset is None:
            raise ExchangeError("EXCHANGE_DATASET_NOT_FOUND", "frozen dataset not found")
        transport_kind = _code(transport_kind, "TRANSPORT_KIND")
        provider_key = _code(provider_key, "PROVIDER_KEY")
        if not isinstance(mapping, dict) or not mapping:
            raise ExchangeError("EXCHANGE_MAPPING_INVALID", "mapping must be a non-empty object")
        # Provider credentials/endpoints belong in settings or a secret store.
        forbidden = {"password", "secret", "token", "credential", "api_key", "endpoint"}
        if forbidden.intersection({str(key).lower() for key in mapping}):
            raise ExchangeError(
                "EXCHANGE_MAPPING_SECRET_FORBIDDEN",
                "target mapping cannot contain credentials or endpoints",
            )
        content = {
            "datasetCode": dataset_code,
            "datasetVersion": dataset_version,
            "transportKind": transport_kind,
            "providerKey": provider_key,
            "mapping": mapping,
            "expectedReceipt": bool(expected_receipt),
        }
        content_hash = _digest(content)
        existing = ExchangeTargetMappingVersion.objects.filter(
            tenant_id=self.tenant_id,
            target_code=target_code,
            content_hash=content_hash,
        ).first()
        if existing:
            return VersionOutcome(existing, False)
        previous = (
            ExchangeTargetMappingVersion.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, target_code=target_code)
            .order_by("-version_no")
            .first()
        )
        value = ExchangeTargetMappingVersion.objects.create(
            tenant_id=self.tenant_id,
            target_code=target_code,
            version_no=(previous.version_no + 1 if previous else 1),
            status="ACTIVE",
            dataset_code=dataset_code,
            dataset_version=dataset_version,
            transport_kind=transport_kind,
            provider_key=provider_key,
            mapping_json=mapping,
            expected_receipt=bool(expected_receipt),
            content_hash=content_hash,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        return VersionOutcome(value, True)


class ExchangeJobService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise ExchangeError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    @transaction.atomic
    def queue(
        self,
        *,
        job_no,
        dataset_version_id,
        target_mapping_version_id,
        idempotency_key,
        max_attempts=5,
    ) -> VersionOutcome:
        job_no = _code(job_no, "JOB_NO")
        idempotency_key = str(idempotency_key or "").strip()
        if not idempotency_key or len(idempotency_key) > 128:
            raise ExchangeError("EXCHANGE_IDEMPOTENCY_KEY_INVALID", "idempotency_key is invalid")
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 20:
            raise ExchangeError("EXCHANGE_MAX_ATTEMPTS_INVALID", "max_attempts must be 1..20")
        existing = ExchangeJob.objects.filter(
            tenant_id=self.tenant_id, idempotency_key=idempotency_key
        ).first()
        if existing:
            if (
                str(existing.dataset_version_id) != str(dataset_version_id)
                or str(existing.target_mapping_version_id) != str(target_mapping_version_id)
            ):
                raise ExchangeError(
                    "EXCHANGE_IDEMPOTENCY_CONFLICT",
                    "idempotency_key already identifies different work",
                )
            return VersionOutcome(existing, False)
        # The frozen dataset row is the queue serialization point. It closes
        # the check/create race for identical idempotency keys without a
        # database-specific advisory lock.
        dataset = ExchangeDatasetVersion.objects.select_for_update().filter(
            tenant_id=self.tenant_id, id=dataset_version_id, status="FROZEN"
        ).first()
        target = ExchangeTargetMappingVersion.objects.filter(
            tenant_id=self.tenant_id, id=target_mapping_version_id, status="ACTIVE"
        ).first()
        if dataset is None or target is None:
            raise ExchangeError("EXCHANGE_DEFINITION_NOT_FOUND", "dataset or target mapping not found")
        concurrent = ExchangeJob.objects.filter(
            tenant_id=self.tenant_id, idempotency_key=idempotency_key
        ).first()
        if concurrent:
            if (
                str(concurrent.dataset_version_id) != str(dataset_version_id)
                or str(concurrent.target_mapping_version_id)
                != str(target_mapping_version_id)
            ):
                raise ExchangeError(
                    "EXCHANGE_IDEMPOTENCY_CONFLICT",
                    "idempotency_key already identifies different work",
                )
            return VersionOutcome(concurrent, False)
        if (
            target.dataset_code != dataset.dataset_code
            or target.dataset_version != dataset.version_no
        ):
            raise ExchangeError(
                "EXCHANGE_TARGET_DATASET_MISMATCH",
                "target mapping does not belong to the frozen dataset version",
            )
        value = ExchangeJob.objects.create(
            tenant_id=self.tenant_id,
            job_no=job_no,
            dataset_version_id=dataset.id,
            target_mapping_version_id=target.id,
            snapshot_hash=dataset.payload_hash,
            idempotency_key=idempotency_key,
            max_attempts=max_attempts,
            status=ExchangeJob.Status.QUEUED,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        return VersionOutcome(value, True)

    def _load_provider(self, provider_key: str):
        registry = getattr(settings, "HR18_EXCHANGE_PROVIDERS", {})
        if not isinstance(registry, Mapping):
            raise ExchangeError(
                "EXCHANGE_PROVIDER_REGISTRY_INVALID",
                "HR18_EXCHANGE_PROVIDERS must be a mapping",
            )
        provider_path = str(registry.get(provider_key) or "").strip()
        if not provider_path:
            raise ExchangeError(
                "EXCHANGE_PROVIDER_UNAVAILABLE",
                f"exchange provider {provider_key} is unavailable",
            )
        try:
            return import_string(provider_path)
        except Exception as exc:
            raise ExchangeError(
                "EXCHANGE_PROVIDER_UNAVAILABLE",
                f"exchange provider cannot be loaded: {type(exc).__name__}",
            ) from exc

    @transaction.atomic
    def _claim(self, job_id, *, lease_seconds: int = 300):
        now = timezone.now()
        job = (
            ExchangeJob.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, id=job_id)
            .first()
        )
        if job is None:
            raise ExchangeError("EXCHANGE_JOB_NOT_FOUND", "exchange job not found")
        eligible = job.status in {ExchangeJob.Status.QUEUED, ExchangeJob.Status.RETRY_WAIT}
        expired_lease = (
            job.status == ExchangeJob.Status.LEASED
            and job.lease_expires_at is not None
            and job.lease_expires_at <= now
        )
        if not eligible and not expired_lease:
            raise ExchangeError("EXCHANGE_JOB_NOT_CLAIMABLE", f"job status {job.status} is not claimable")
        if job.next_attempt_at and job.next_attempt_at > now:
            raise ExchangeError("EXCHANGE_RETRY_NOT_DUE", "retry is not due")
        lease_token = uuid.uuid4()
        job.status = ExchangeJob.Status.LEASED
        job.lease_token = lease_token
        job.lease_expires_at = now + timedelta(seconds=lease_seconds)
        job.attempt_count += 1
        job.updated_by = self.actor_user_id
        job.save(
            update_fields=[
                "status",
                "lease_token",
                "lease_expires_at",
                "attempt_count",
                "updated_by",
                "updated_at",
            ]
        )
        return job, lease_token, now

    def dispatch(self, job_id) -> DispatchOutcome:
        # Provider configuration is resolved before leasing; missing credentials
        # leave the job queued and explicitly report UNAVAILABLE.
        job = ExchangeJob.objects.filter(tenant_id=self.tenant_id, id=job_id).first()
        if job is None:
            raise ExchangeError("EXCHANGE_JOB_NOT_FOUND", "exchange job not found")
        target = ExchangeTargetMappingVersion.objects.filter(
            tenant_id=self.tenant_id, id=job.target_mapping_version_id
        ).first()
        dataset = ExchangeDatasetVersion.objects.filter(
            tenant_id=self.tenant_id, id=job.dataset_version_id
        ).first()
        if target is None or dataset is None:
            raise ExchangeError("EXCHANGE_DEFINITION_NOT_FOUND", "exchange definition not found")
        provider = self._load_provider(target.provider_key)
        job, lease_token, started_at = self._claim(job_id)
        attempt_key = f"{job.idempotency_key}:{job.attempt_count}"

        # External call deliberately occurs outside any atomic block.
        try:
            response = provider(
                tenant_id=self.tenant_id,
                job=job,
                dataset=dataset,
                target_mapping=target,
                idempotency_key=attempt_key,
                actor_user_id=self.actor_user_id,
            )
            if not isinstance(response, Mapping) or response.get("transmitted") is not True:
                raise ExchangeError(
                    "EXCHANGE_PROVIDER_CONTRACT_INVALID",
                    "provider must return transmitted=true",
                )
            dispatch_ref = str(response.get("dispatchRef") or "").strip()
            if not dispatch_ref or len(dispatch_ref) > 255:
                raise ExchangeError("EXCHANGE_DISPATCH_REF_INVALID", "dispatchRef is invalid")
            provider_version = str(response.get("providerVersion") or "")[:64]
            response_hash = _digest(
                {
                    "dispatchRef": dispatch_ref,
                    "providerVersion": provider_version,
                    "payloadHash": job.snapshot_hash,
                }
            )
        except Exception as exc:
            error_code = exc.code if isinstance(exc, ExchangeError) else f"PROVIDER_{type(exc).__name__.upper()}"
            return self._record_failure(
                job.id,
                lease_token=lease_token,
                attempt_key=attempt_key,
                started_at=started_at,
                error_code=error_code,
            )
        return self._record_success(
            job.id,
            lease_token=lease_token,
            attempt_key=attempt_key,
            started_at=started_at,
            dispatch_ref=dispatch_ref,
            provider_version=provider_version,
            response_hash=response_hash,
        )

    @transaction.atomic
    def _leased(self, job_id, lease_token):
        job = (
            ExchangeJob.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, id=job_id)
            .first()
        )
        if (
            job is None
            or job.status != ExchangeJob.Status.LEASED
            or job.lease_token != lease_token
        ):
            raise ExchangeError(
                "EXCHANGE_LEASE_LOST", "worker lease is no longer current"
            )
        return job

    @transaction.atomic
    def _record_success(
        self,
        job_id,
        *,
        lease_token,
        attempt_key,
        started_at,
        dispatch_ref,
        provider_version,
        response_hash,
    ) -> DispatchOutcome:
        job = self._leased(job_id, lease_token)
        now = timezone.now()
        ExchangeAttempt.objects.create(
            tenant_id=self.tenant_id,
            job_id=job.id,
            attempt_no=job.attempt_count,
            idempotency_key=attempt_key,
            provider_version=provider_version,
            status=ExchangeAttempt.Status.TRANSMITTED,
            dispatch_ref=dispatch_ref,
            response_hash=response_hash,
            started_at=started_at,
            finished_at=now,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        job.status = ExchangeJob.Status.TRANSMITTED
        job.dispatch_ref = dispatch_ref
        job.transmitted_at = now
        job.lease_token = None
        job.lease_expires_at = None
        job.next_attempt_at = None
        job.last_error_code = ""
        job.updated_by = self.actor_user_id
        job.save(update_fields=[
            "status", "dispatch_ref", "transmitted_at", "lease_token",
            "lease_expires_at", "next_attempt_at", "last_error_code",
            "updated_by", "updated_at",
        ])
        return DispatchOutcome(job, True, False, False)

    @transaction.atomic
    def _record_failure(
        self, job_id, *, lease_token, attempt_key, started_at, error_code
    ) -> DispatchOutcome:
        job = self._leased(job_id, lease_token)
        now = timezone.now()
        terminal = job.attempt_count >= job.max_attempts
        attempt_status = (
            ExchangeAttempt.Status.TERMINAL_FAILURE
            if terminal
            else ExchangeAttempt.Status.RETRYABLE_FAILURE
        )
        ExchangeAttempt.objects.create(
            tenant_id=self.tenant_id,
            job_id=job.id,
            attempt_no=job.attempt_count,
            idempotency_key=attempt_key,
            status=attempt_status,
            error_code=str(error_code)[:64],
            started_at=started_at,
            finished_at=now,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        job.status = ExchangeJob.Status.DEAD_LETTER if terminal else ExchangeJob.Status.RETRY_WAIT
        job.next_attempt_at = None if terminal else now + timedelta(minutes=min(60, 2 ** (job.attempt_count - 1)))
        job.lease_token = None
        job.lease_expires_at = None
        job.last_error_code = str(error_code)[:64]
        job.updated_by = self.actor_user_id
        job.save(update_fields=[
            "status", "next_attempt_at", "lease_token", "lease_expires_at",
            "last_error_code", "updated_by", "updated_at",
        ])
        if terminal:
            ExchangeDeadLetter.objects.get_or_create(
                tenant_id=self.tenant_id,
                job_id=job.id,
                defaults={
                    "reason_code": job.last_error_code,
                    "final_attempt_no": job.attempt_count,
                    "snapshot_hash": job.snapshot_hash,
                    "failed_at": now,
                    "created_by": self.actor_user_id,
                    "updated_by": self.actor_user_id,
                },
            )
        return DispatchOutcome(job, False, not terminal, terminal)

    @transaction.atomic
    def record_receipt(
        self,
        job_id,
        *,
        receipt_ref,
        accepted,
        received_payload_hash="",
        received_record_count=None,
        receipt_evidence=None,
    ) -> VersionOutcome:
        job = (
            ExchangeJob.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, id=job_id)
            .first()
        )
        if job is None:
            raise ExchangeError("EXCHANGE_JOB_NOT_FOUND", "exchange job not found")
        if job.status not in {ExchangeJob.Status.TRANSMITTED, ExchangeJob.Status.ACKNOWLEDGED}:
            raise ExchangeError("EXCHANGE_RECEIPT_INVALID_STATE", "job is not awaiting a receipt")
        receipt_ref = str(receipt_ref or "").strip()
        if not receipt_ref or len(receipt_ref) > 255:
            raise ExchangeError("EXCHANGE_RECEIPT_REF_INVALID", "receipt_ref is invalid")
        if not isinstance(accepted, bool):
            raise ExchangeError("EXCHANGE_RECEIPT_ACCEPTED_INVALID", "accepted must be boolean")
        if received_payload_hash:
            received_payload_hash = _sha256(received_payload_hash, "RECEIVED_PAYLOAD_HASH")
        if received_record_count is not None and (
            isinstance(received_record_count, bool)
            or not isinstance(received_record_count, int)
            or received_record_count < 0
        ):
            raise ExchangeError("EXCHANGE_RECEIPT_COUNT_INVALID", "received_record_count is invalid")
        evidence_hash = _digest(receipt_evidence or {})
        existing = ExchangeReceipt.objects.filter(
            tenant_id=self.tenant_id, job_id=job.id
        ).first()
        if existing:
            same = (
                existing.receipt_ref == receipt_ref
                and existing.accepted == accepted
                and existing.received_payload_hash == received_payload_hash
                and existing.received_record_count == received_record_count
                and existing.receipt_hash == evidence_hash
            )
            if not same:
                raise ExchangeError("EXCHANGE_RECEIPT_CONFLICT", "job already has a different receipt")
            return VersionOutcome(existing, False)
        receipt = ExchangeReceipt.objects.create(
            tenant_id=self.tenant_id,
            job_id=job.id,
            receipt_ref=receipt_ref,
            accepted=accepted,
            received_payload_hash=received_payload_hash,
            received_record_count=received_record_count,
            receipt_hash=evidence_hash,
            received_at=timezone.now(),
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        job.status = ExchangeJob.Status.ACKNOWLEDGED
        job.updated_by = self.actor_user_id
        job.save(update_fields=["status", "updated_by", "updated_at"])
        return VersionOutcome(receipt, True)

    @transaction.atomic
    def reconcile(self, job_id) -> VersionOutcome:
        job = (
            ExchangeJob.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, id=job_id)
            .first()
        )
        if job is None:
            raise ExchangeError("EXCHANGE_JOB_NOT_FOUND", "exchange job not found")
        existing = ExchangeReconciliation.objects.filter(
            tenant_id=self.tenant_id, job_id=job.id
        ).first()
        if existing:
            return VersionOutcome(existing, False)
        if job.status != ExchangeJob.Status.ACKNOWLEDGED:
            raise ExchangeError("EXCHANGE_RECONCILE_INVALID_STATE", "job is not acknowledged")
        receipt = ExchangeReceipt.objects.filter(
            tenant_id=self.tenant_id, job_id=job.id
        ).first()
        dataset = ExchangeDatasetVersion.objects.filter(
            tenant_id=self.tenant_id, id=job.dataset_version_id
        ).first()
        if receipt is None or dataset is None:
            raise ExchangeError("EXCHANGE_RECONCILE_EVIDENCE_MISSING", "receipt or dataset is missing")
        differences = {}
        if not receipt.received_payload_hash:
            differences["payloadHash"] = {
                "expected": dataset.payload_hash,
                "received": None,
            }
        elif receipt.received_payload_hash != dataset.payload_hash:
            differences["payloadHash"] = {
                "expected": dataset.payload_hash,
                "received": receipt.received_payload_hash,
            }
        if receipt.received_record_count is None:
            differences["recordCount"] = {
                "expected": dataset.record_count,
                "received": None,
            }
        elif receipt.received_record_count != dataset.record_count:
            differences["recordCount"] = {
                "expected": dataset.record_count,
                "received": receipt.received_record_count,
            }
        status = ExchangeReconciliation.Status.MATCHED
        if not receipt.accepted:
            status = ExchangeReconciliation.Status.REJECTED
            differences["accepted"] = {"expected": True, "received": False}
        elif differences:
            status = ExchangeReconciliation.Status.MISMATCH
        reconciliation = ExchangeReconciliation.objects.create(
            tenant_id=self.tenant_id,
            job_id=job.id,
            receipt_id=receipt.id,
            expected_payload_hash=dataset.payload_hash,
            received_payload_hash=receipt.received_payload_hash,
            expected_record_count=dataset.record_count,
            received_record_count=receipt.received_record_count,
            status=status,
            differences_json=differences,
            reconciled_at=timezone.now(),
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        if status == ExchangeReconciliation.Status.MATCHED:
            job.status = ExchangeJob.Status.RECONCILED
        else:
            job.status = ExchangeJob.Status.DEAD_LETTER
            ExchangeDeadLetter.objects.get_or_create(
                tenant_id=self.tenant_id,
                job_id=job.id,
                defaults={
                    "reason_code": f"RECONCILIATION_{status}",
                    "final_attempt_no": job.attempt_count,
                    "snapshot_hash": job.snapshot_hash,
                    "failed_at": timezone.now(),
                    "created_by": self.actor_user_id,
                    "updated_by": self.actor_user_id,
                },
            )
        job.updated_by = self.actor_user_id
        job.save(update_fields=["status", "updated_by", "updated_at"])
        return VersionOutcome(reconciliation, True)
