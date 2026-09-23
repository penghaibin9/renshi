"""Tenant-scoped HTTP authority for HR18 asynchronous data exchange."""

from __future__ import annotations

import uuid
from datetime import datetime

from django.db.models import Count, Max, OuterRef, Q, Subquery
from django.http import JsonResponse

from .api import HrDataAccessError, _error, _payload, resolve_request_tenant
from .models import (
    ExchangeDatasetVersion,
    ExchangeDeadLetter,
    ExchangeJob,
    ExchangeTargetMappingVersion,
)
from .services.exchange_service import (
    ExchangeDefinitionService,
    ExchangeError,
    ExchangeJobService,
)
from .standards.china_education import classification_summary, standard_catalog

EXCHANGE_PERMISSION = "hr.data.exchange"


def _tenant(request):
    return resolve_request_tenant(request, required_permission=EXCHANGE_PERMISSION)


def _status(code):
    if code.endswith("NOT_FOUND") or code == "EXCHANGE_DEFINITION_NOT_FOUND":
        return 404
    if code in {
        "EXCHANGE_IDEMPOTENCY_CONFLICT",
        "EXCHANGE_TARGET_DATASET_MISMATCH",
        "EXCHANGE_JOB_NOT_CLAIMABLE",
        "EXCHANGE_RECEIPT_INVALID_STATE",
        "EXCHANGE_RECEIPT_CONFLICT",
        "EXCHANGE_RECONCILE_INVALID_STATE",
        "EXCHANGE_LEASE_LOST",
        "EXCHANGE_MANUAL_RETRY_INVALID_STATE",
        "EXCHANGE_DEAD_LETTER_ALREADY_RESOLVED",
        "EXCHANGE_JOB_NO_CONFLICT",
    }:
        return 409
    if code == "EXCHANGE_PROVIDER_UNAVAILABLE":
        return 503
    return 400


def _uuid(payload, key):
    try:
        return uuid.UUID(str(payload.get(key, "")))
    except (TypeError, ValueError) as exc:
        raise ExchangeError("EXCHANGE_ID_INVALID", f"{key} must be UUID") from exc


def _json(data, *, status=200, schema="hr18.exchange.1"):
    response = JsonResponse(
        {"data": data, "apiVersion": "1.0", "schemaVersion": schema}, status=status
    )
    response["Cache-Control"] = "no-store"
    return response


def _prepare(request):
    if request.method != "POST":
        return None, None, _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = _tenant(request)
    except HrDataAccessError as exc:
        return None, None, _error(exc.code, exc.message, status=403)
    try:
        payload = _payload(request)
    except ValueError:
        return None, None, _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
    return tenant_id, payload, None


def workbench(request):
    """Return tenant-scoped frozen definitions and operational job state."""
    if request.method != "GET":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = _tenant(request)
    except HrDataAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    datasets = ExchangeDatasetVersion.objects.filter(tenant_id=tenant_id).order_by(
        "dataset_code", "-version_no"
    )[:200]
    latest_target_job = ExchangeJob.objects.filter(
        tenant_id=tenant_id, target_mapping_version_id=OuterRef("pk")
    ).order_by("-created_at")
    latest_unresolved_failure = ExchangeDeadLetter.objects.filter(
        tenant_id=tenant_id,
        job__target_mapping_version_id=OuterRef("pk"),
        resolved_at__isnull=True,
    ).order_by("-failed_at")
    targets = (
        ExchangeTargetMappingVersion.objects.filter(tenant_id=tenant_id)
        .annotate(
            pending_count=Count(
                "exchange_jobs",
                filter=Q(exchange_jobs__status__in=[
                    ExchangeJob.Status.QUEUED,
                    ExchangeJob.Status.LEASED,
                    ExchangeJob.Status.RETRY_WAIT,
                ]),
                distinct=True,
            ),
            transmitted_count=Count(
                "exchange_jobs",
                filter=Q(exchange_jobs__status__in=[
                    ExchangeJob.Status.TRANSMITTED,
                    ExchangeJob.Status.ACKNOWLEDGED,
                    ExchangeJob.Status.RECONCILED,
                ]),
                distinct=True,
            ),
            reconciled_count=Count(
                "exchange_jobs",
                filter=Q(exchange_jobs__status=ExchangeJob.Status.RECONCILED),
                distinct=True,
            ),
            failure_count=Count(
                "exchange_jobs",
                filter=Q(exchange_jobs__status=ExchangeJob.Status.DEAD_LETTER),
                distinct=True,
            ),
            unresolved_failure_count=Count(
                "exchange_jobs",
                filter=Q(
                    exchange_jobs__status=ExchangeJob.Status.DEAD_LETTER,
                    exchange_jobs__dead_letter__resolved_at__isnull=True,
                ),
                distinct=True,
            ),
            last_transmitted_at=Max(
                "exchange_jobs__transmitted_at",
                filter=Q(
                    exchange_jobs__status__in=[
                        ExchangeJob.Status.TRANSMITTED,
                        ExchangeJob.Status.ACKNOWLEDGED,
                        ExchangeJob.Status.RECONCILED,
                    ]
                ),
            ),
            last_reconciled_at=Max(
                "exchange_jobs__updated_at",
                filter=Q(exchange_jobs__status=ExchangeJob.Status.RECONCILED),
            ),
            latest_job_status=Subquery(latest_target_job.values("status")[:1]),
            latest_job_no=Subquery(latest_target_job.values("job_no")[:1]),
            latest_error_code=Subquery(latest_target_job.values("last_error_code")[:1]),
            latest_unresolved_failure_reason=Subquery(
                latest_unresolved_failure.values("reason_code")[:1]
            ),
            latest_unresolved_failure_at=Subquery(
                latest_unresolved_failure.values("failed_at")[:1]
            ),
        )
        .order_by("target_code", "-version_no")[:200]
    )
    jobs = ExchangeJob.objects.filter(tenant_id=tenant_id).select_related(
        "dataset_version", "target_mapping_version"
    ).order_by("-created_at")[:200]
    return _json(
        {
            "datasets": [
                {
                    "id": str(row.id),
                    "datasetCode": row.dataset_code,
                    "versionNo": row.version_no,
                    "name": row.name,
                    "status": row.status,
                    "payloadHash": row.payload_hash,
                    "recordCount": row.record_count,
                    "frozenAt": row.frozen_at.isoformat(),
                    "classification": classification_summary(row.schema_json),
                }
                for row in datasets
            ],
            "targets": [
                {
                    "id": str(row.id),
                    "targetCode": row.target_code,
                    "versionNo": row.version_no,
                    "datasetCode": row.dataset_code,
                    "datasetVersion": row.dataset_version,
                    "transportKind": row.transport_kind,
                    "providerKey": row.provider_key,
                    "expectedReceipt": row.expected_receipt,
                    "status": row.status,
                    "mapping": row.mapping_json,
                    "contentHash": row.content_hash,
                    "syncHealth": {
                        "pendingCount": row.pending_count,
                        "transmittedCount": row.transmitted_count,
                        "reconciledCount": row.reconciled_count,
                        "failureCount": row.failure_count,
                        "unresolvedFailureCount": row.unresolved_failure_count,
                        "lastSuccessAt": (
                            row.last_reconciled_at.isoformat()
                            if row.expected_receipt and row.last_reconciled_at
                            else row.last_transmitted_at.isoformat()
                            if (not row.expected_receipt) and row.last_transmitted_at
                            else None
                        ),
                        "successSemantics": "RECONCILED" if row.expected_receipt else "TRANSMITTED",
                        "latestJobStatus": row.latest_job_status or None,
                        "latestJobNo": row.latest_job_no or None,
                        "latestErrorCode": row.latest_error_code or None,
                        "latestUnresolvedFailureReason": row.latest_unresolved_failure_reason or None,
                        "latestUnresolvedFailureAt": (
                            row.latest_unresolved_failure_at.isoformat()
                            if row.latest_unresolved_failure_at
                            else None
                        ),
                    },
                }
                for row in targets
            ],
            "jobs": [
                {
                    "id": str(row.id),
                    "jobNo": row.job_no,
                    "status": row.status,
                    "datasetCode": row.dataset_version.dataset_code,
                    "datasetVersion": row.dataset_version.version_no,
                    "targetCode": row.target_mapping_version.target_code,
                    "targetVersion": row.target_mapping_version.version_no,
                    "snapshotHash": row.snapshot_hash,
                    "attemptCount": row.attempt_count,
                    "maxAttempts": row.max_attempts,
                    "dispatchRef": row.dispatch_ref or None,
                    "lastErrorCode": row.last_error_code or None,
                    "createdAt": row.created_at.isoformat(),
                    "retryOfJobId": str(row.retry_of_job_id) if row.retry_of_job_id else None,
                    "manualRetryReason": row.manual_retry_reason or None,
                    "manualRetryBy": row.manual_retry_by,
                }
                for row in jobs
            ],
            "standardCatalog": standard_catalog(),
        },
        schema="hr18.exchange-workbench.1",
    )


def create_dataset(request):
    tenant_id, payload, error = _prepare(request)
    if error:
        return error
    frozen_at = None
    if payload.get("frozenAt"):
        try:
            frozen_at = datetime.fromisoformat(str(payload["frozenAt"]).replace("Z", "+00:00"))
        except ValueError:
            return _error("EXCHANGE_FROZEN_AT_INVALID", status=400)
    try:
        outcome = ExchangeDefinitionService(
            tenant_id, getattr(request.user, "id", None)
        ).create_dataset_version(
            dataset_code=payload.get("datasetCode"),
            name=payload.get("name"),
            schema=payload.get("schema"),
            source_snapshot=payload.get("sourceSnapshot"),
            payload_ref=payload.get("payloadRef"),
            payload_hash=payload.get("payloadHash"),
            record_count=payload.get("recordCount"),
            frozen_at=frozen_at,
        )
    except ExchangeError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))
    value = outcome.value
    return _json(
        {
            "id": str(value.id),
            "datasetCode": value.dataset_code,
            "versionNo": value.version_no,
            "status": value.status,
            "payloadHash": value.payload_hash,
            "recordCount": value.record_count,
            "created": outcome.created,
        },
        status=201 if outcome.created else 200,
        schema="hr18.exchange-dataset.1",
    )


def create_target_mapping(request):
    tenant_id, payload, error = _prepare(request)
    if error:
        return error
    try:
        outcome = ExchangeDefinitionService(
            tenant_id, getattr(request.user, "id", None)
        ).create_target_mapping_version(
            target_code=payload.get("targetCode"),
            dataset_code=payload.get("datasetCode"),
            dataset_version=payload.get("datasetVersion"),
            transport_kind=payload.get("transportKind"),
            provider_key=payload.get("providerKey"),
            mapping=payload.get("mapping"),
            expected_receipt=payload.get("expectedReceipt", True),
        )
    except ExchangeError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))
    value = outcome.value
    return _json(
        {
            "id": str(value.id),
            "targetCode": value.target_code,
            "versionNo": value.version_no,
            "datasetCode": value.dataset_code,
            "datasetVersion": value.dataset_version,
            "created": outcome.created,
        },
        status=201 if outcome.created else 200,
        schema="hr18.exchange-target.1",
    )


def queue_job(request):
    tenant_id, payload, error = _prepare(request)
    if error:
        return error
    try:
        outcome = ExchangeJobService(
            tenant_id, getattr(request.user, "id", None)
        ).queue(
            job_no=payload.get("jobNo"),
            dataset_version_id=_uuid(payload, "datasetVersionId"),
            target_mapping_version_id=_uuid(payload, "targetMappingVersionId"),
            idempotency_key=payload.get("idempotencyKey"),
            max_attempts=payload.get("maxAttempts", 5),
        )
    except ExchangeError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))
    value = outcome.value
    return _json(
        {
            "id": str(value.id),
            "jobNo": value.job_no,
            "status": value.status,
            "snapshotHash": value.snapshot_hash,
            "created": outcome.created,
        },
        status=202 if outcome.created else 200,
        schema="hr18.exchange-job.1",
    )


def retry_job(request, job_id):
    tenant_id, payload, error = _prepare(request)
    if error:
        return error
    try:
        outcome = ExchangeJobService(
            tenant_id, getattr(request.user, "id", None)
        ).requeue_dead_letter(
            job_id,
            new_job_no=payload.get("newJobNo"),
            idempotency_key=payload.get("idempotencyKey"),
            reason=payload.get("reason"),
            max_attempts=payload.get("maxAttempts"),
        )
    except ExchangeError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))
    value = outcome.value
    return _json(
        {
            "id": str(value.id),
            "jobNo": value.job_no,
            "status": value.status,
            "retryOfJobId": str(value.retry_of_job_id),
            "created": outcome.created,
        },
        status=202 if outcome.created else 200,
        schema="hr18.exchange-manual-retry.1",
    )


def retry_batch(request):
    tenant_id, payload, error = _prepare(request)
    if error:
        return error
    items = payload.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= 100:
        return _error(
            "EXCHANGE_RETRY_BATCH_INVALID",
            "items must contain 1..100 retry requests",
            status=400,
        )
    service = ExchangeJobService(tenant_id, getattr(request.user, "id", None))
    results = []
    success_count = 0
    for item in items:
        if not isinstance(item, dict):
            results.append({"ok": False, "code": "EXCHANGE_RETRY_ITEM_INVALID"})
            continue
        source_id = item.get("jobId")
        try:
            source_uuid = uuid.UUID(str(source_id or ""))
            outcome = service.requeue_dead_letter(
                source_uuid,
                new_job_no=item.get("newJobNo"),
                idempotency_key=item.get("idempotencyKey"),
                reason=item.get("reason"),
                max_attempts=item.get("maxAttempts"),
            )
        except (TypeError, ValueError):
            results.append({
                "jobId": str(source_id or ""),
                "ok": False,
                "code": "EXCHANGE_ID_INVALID",
            })
            continue
        except ExchangeError as exc:
            results.append({
                "jobId": str(source_id or ""),
                "ok": False,
                "code": exc.code,
                "message": str(exc),
            })
            continue
        success_count += 1
        results.append({
            "jobId": str(source_uuid),
            "ok": True,
            "successorJobId": str(outcome.value.id),
            "successorJobNo": outcome.value.job_no,
            "created": outcome.created,
        })
    return _json(
        {
            "requestedCount": len(items),
            "successCount": success_count,
            "failureCount": len(items) - success_count,
            "partial": success_count != len(items),
            "results": results,
        },
        status=200,
        schema="hr18.exchange-manual-retry-batch.1",
    )


def record_receipt(request, job_id):
    tenant_id, payload, error = _prepare(request)
    if error:
        return error
    try:
        outcome = ExchangeJobService(
            tenant_id, getattr(request.user, "id", None)
        ).record_receipt(
            job_id,
            receipt_ref=payload.get("receiptRef"),
            accepted=payload.get("accepted"),
            received_payload_hash=payload.get("receivedPayloadHash", ""),
            received_record_count=payload.get("receivedRecordCount"),
            receipt_evidence=payload.get("receiptEvidence"),
        )
    except ExchangeError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))
    value = outcome.value
    return _json(
        {
            "id": str(value.id),
            "jobId": str(value.job_id),
            "receiptRef": value.receipt_ref,
            "accepted": value.accepted,
            "created": outcome.created,
        },
        status=201 if outcome.created else 200,
        schema="hr18.exchange-receipt.1",
    )


def reconcile_job(request, job_id):
    tenant_id, _payload_value, error = _prepare(request)
    if error:
        return error
    try:
        outcome = ExchangeJobService(
            tenant_id, getattr(request.user, "id", None)
        ).reconcile(job_id)
    except ExchangeError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))
    value = outcome.value
    return _json(
        {
            "id": str(value.id),
            "jobId": str(value.job_id),
            "status": value.status,
            "differences": value.differences_json,
            "created": outcome.created,
        },
        status=201 if outcome.created else 200,
        schema="hr18.exchange-reconciliation.1",
    )


def dead_letters(request):
    if request.method != "GET":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = _tenant(request)
    except HrDataAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    rows = ExchangeDeadLetter.objects.filter(
        tenant_id=tenant_id, resolved_at__isnull=True
    ).order_by("failed_at")[:200]
    return _json(
        [
            {
                "id": str(row.id),
                "jobId": str(row.job_id),
                "reasonCode": row.reason_code,
                "finalAttemptNo": row.final_attempt_no,
                "snapshotHash": row.snapshot_hash,
                "failedAt": row.failed_at.isoformat(),
            }
            for row in rows
        ],
        schema="hr18.exchange-dead-letter.1",
    )

