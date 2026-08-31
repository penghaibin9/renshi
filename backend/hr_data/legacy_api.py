"""Tenant-scoped API for the evidence-gated HR18 legacy report takeover."""

import uuid

from django.http import JsonResponse
from django.utils import timezone

from .api import HrDataAccessError, _error, _payload, resolve_request_tenant
from .services.legacy_report_asset_service import (
    LegacyReportAssetInventoryService,
    LegacyReportTakeoverError,
    LegacyReportTakeoverService,
)


TAKEOVER_PERMISSION = "hr.data.legacy.takeover"


def _takeover_error(exc):
    if exc.code == "HR18_LEGACY_ASSET_NOT_FOUND":
        status = 404
    elif exc.code in {
        "HR18_LEGACY_IDEMPOTENCY_CONFLICT",
        "HR18_LEGACY_ASSET_VERSION_STALE",
        "HR18_LEGACY_CUTOVER_SEQUENCE_INVALID",
        "HR18_LEGACY_CUTOVER_EVIDENCE_UNAVAILABLE",
    }:
        status = 409
    elif exc.code in {
        "HR18_LEGACY_INVENTORY_TRUNCATED",
        "HR18_LEGACY_ASSET_EVIDENCE_REQUIRED",
    }:
        status = 422
    else:
        status = 400
    return _error(exc.code, str(exc), status=status)


def _service(request):
    tenant_id = resolve_request_tenant(
        request, required_permission=TAKEOVER_PERMISSION
    )
    return LegacyReportTakeoverService(
        tenant_id, actor_user_id=getattr(request.user, "id", None)
    )


def _json(request):
    try:
        return _payload(request)
    except ValueError:
        return None


def _step_response(outcome):
    step = outcome.value
    response = JsonResponse(
        {
            "data": {
                "id": str(step.id),
                "cutoverCode": step.cutover_code,
                "stepNo": step.step_no,
                "phase": step.phase,
                "assetCount": step.asset_count,
                "matchedCount": step.matched_count,
                "archivedCount": step.archived_count,
                "unavailableCount": step.unavailable_count,
                "evidenceHash": step.evidence_hash,
                "created": outcome.created,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr18.legacy-report-cutover.1",
        },
        status=201 if outcome.created else 200,
    )
    response["Cache-Control"] = "no-store"
    return response


def legacy_report_assets(request):
    if request.method != "GET":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request)
    except HrDataAccessError as exc:
        return _error(exc.code, exc.message, status=403)

    raw_limit = request.GET.get("limit", "200")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        return _error("INVALID_LIMIT", "limit 必须是整数", status=400)

    data = LegacyReportAssetInventoryService(tenant_id).snapshot(limit=limit)
    data.update(
        {
            "apiVersion": "1.0",
            "schemaVersion": "hr18.legacy-report-assets.1",
            "generatedAt": timezone.now().isoformat(),
        }
    )
    response = JsonResponse(data)
    response["Cache-Control"] = "no-store"
    return response


def inventory(request):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        service = _service(request)
    except HrDataAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    payload = _json(request)
    if payload is None:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
    try:
        outcome = service.inventory(
            cutover_code=payload.get("cutoverCode", ""),
            idempotency_key=payload.get("idempotencyKey", ""),
            limit=payload.get("limit", 5000),
        )
    except (TypeError, ValueError):
        return _error("HR18_LEGACY_LIMIT_INVALID", "limit 必须是整数", status=400)
    except LegacyReportTakeoverError as exc:
        return _takeover_error(exc)
    return _step_response(outcome)


def map_asset(request, asset_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        service = _service(request)
    except HrDataAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    payload = _json(request)
    if payload is None:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
    try:
        outcome = service.map_asset(
            asset_id,
            disposition=payload.get("disposition", ""),
            canonical_asset_ref=payload.get("canonicalAssetRef", ""),
            provider_key=payload.get("providerKey", ""),
            mapping=payload.get("mapping"),
            evidence_hash=payload.get("archiveEvidenceHash", ""),
            idempotency_key=payload.get("idempotencyKey", ""),
        )
    except LegacyReportTakeoverError as exc:
        return _takeover_error(exc)
    asset = outcome.value
    response = JsonResponse(
        {
            "data": {
                "id": str(asset.id),
                "legacyObjectId": str(asset.legacy_object_id),
                "versionNo": asset.version_no,
                "disposition": asset.disposition,
                "canonicalAssetRef": asset.canonical_asset_ref,
                "contentHash": asset.content_hash,
                "created": outcome.created,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr18.legacy-report-mapping.1",
        },
        status=201 if outcome.created else 200,
    )
    response["Cache-Control"] = "no-store"
    return response


def reconcile_asset(request, asset_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        uuid.UUID(str(asset_id))
        service = _service(request)
    except (TypeError, ValueError, AttributeError):
        return _error("HR18_LEGACY_ASSET_ID_INVALID", "asset id 必须是 UUID", status=400)
    except HrDataAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    payload = _json(request)
    if payload is None:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
    try:
        outcome = service.reconcile(
            asset_id,
            run_no=payload.get("runNo", ""),
            idempotency_key=payload.get("idempotencyKey", ""),
        )
    except LegacyReportTakeoverError as exc:
        return _takeover_error(exc)
    result = outcome.value
    response = JsonResponse(
        {
            "data": {
                "id": str(result.id),
                "runNo": result.run_no,
                "status": result.status,
                "legacyOutputHash": result.legacy_output_hash,
                "canonicalOutputHash": result.canonical_output_hash,
                "differences": result.differences_json,
                "evidenceHash": result.evidence_hash,
                "created": outcome.created,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr18.legacy-report-reconciliation.1",
        },
        status=201 if outcome.created else 200,
    )
    response["Cache-Control"] = "no-store"
    return response


def advance_cutover(request, cutover_code):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        service = _service(request)
    except HrDataAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    payload = _json(request)
    if payload is None:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
    try:
        outcome = service.advance(
            cutover_code=cutover_code,
            phase=payload.get("phase", ""),
            idempotency_key=payload.get("idempotencyKey", ""),
        )
    except LegacyReportTakeoverError as exc:
        return _takeover_error(exc)
    return _step_response(outcome)
