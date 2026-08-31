"""Canonical HTTP governance for HR18 data-quality findings."""

from __future__ import annotations

from django.http import JsonResponse

from .api import HrDataAccessError, _error, _payload, resolve_request_tenant
from .services.quality_finding_service import (
    DataQualityFindingError,
    DataQualityFindingService,
)

QUALITY_PERMISSION = "hr.data.quality"


def _status(code: str) -> int:
    if code in {"QUALITY_FINDING_NOT_FOUND", "QUALITY_FINDING_RUN_NOT_FOUND"}:
        return 404
    if code in {
        "QUALITY_FINDING_INVALID_STATE",
        "QUALITY_HISTORICAL_FINDING_IMMUTABLE",
        "QUALITY_VERIFICATION_RUN_REUSE_FORBIDDEN",
        "QUALITY_FIX_VERIFICATION_INCOMPLETE",
        "QUALITY_FINDING_STILL_PRESENT",
        "QUALITY_FINDING_IDENTITY_CHANGED",
        "QUALITY_RUN_IDEMPOTENCY_CONFLICT",
    }:
        return 409
    if code in {"QUALITY_PROVIDER_REGISTRY_INVALID"}:
        return 503
    return 400


def _service(request):
    tenant_id = resolve_request_tenant(
        request,
        required_permission=QUALITY_PERMISSION,
    )
    return DataQualityFindingService(
        tenant_id,
        actor_user_id=getattr(request.user, "id", None),
    )


def _serialize(finding):
    return {
        "id": str(finding.id),
        "findingNo": finding.finding_no,
        "qualityRunId": str(finding.quality_run_id) if finding.quality_run_id else None,
        "ruleCode": finding.rule_code,
        "ruleVersion": finding.rule_version,
        "sourceDomain": finding.source_domain,
        "sourceObjectRef": finding.source_object_ref,
        "fingerprint": finding.finding_fingerprint,
        "severity": finding.severity,
        "details": finding.details_json,
        "status": finding.status,
        "detectedAt": finding.detected_at.isoformat(),
        "resolvedAt": finding.resolved_at.isoformat() if finding.resolved_at else None,
    }


def acknowledge(request, finding_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        service = _service(request)
    except HrDataAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        finding = service.acknowledge(finding_id)
    except DataQualityFindingError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))
    response = JsonResponse(
        {
            "data": _serialize(finding),
            "apiVersion": "1.0",
            "schemaVersion": "hr18.quality-finding-governance.1",
        }
    )
    response["Cache-Control"] = "no-store"
    return response


def verify_fixed(request, finding_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        service = _service(request)
    except HrDataAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _payload(request)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
    try:
        outcome = service.verify_fixed(
            finding_id,
            verification_run_no=payload.get("verificationRunNo", ""),
        )
    except DataQualityFindingError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))
    response = JsonResponse(
        {
            "data": {
                **_serialize(outcome.finding),
                "changed": outcome.changed,
                "verificationRunId": (
                    str(outcome.verification_run.id)
                    if outcome.verification_run is not None
                    else None
                ),
                "verificationRunNo": (
                    outcome.verification_run.run_no
                    if outcome.verification_run is not None
                    else None
                ),
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr18.quality-finding-verification.1",
        }
    )
    response["Cache-Control"] = "no-store"
    return response
