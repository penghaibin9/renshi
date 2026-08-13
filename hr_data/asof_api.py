"""Canonical HTTP authority for HR18 historical as-of evidence."""

from __future__ import annotations

from django.http import JsonResponse
from django.utils.dateparse import parse_date

from .api import HrDataAccessError, _error, _payload, resolve_request_tenant
from .services.asof_service import AsOfReconstructionError, AsOfReconstructionService

ASOF_PERMISSION = "hr.data.asof"


def _status(code: str) -> int:
    if code == "ASOF_DEFINITION_NOT_FOUND":
        return 404
    if code == "ASOF_EVIDENCE_IDEMPOTENCY_CONFLICT":
        return 409
    if code == "ASOF_PROVIDER_REGISTRY_INVALID":
        return 503
    return 400


def _serialize(evidence):
    return {
        "id": str(evidence.id),
        "evidenceNo": evidence.evidence_no,
        "definitionKind": evidence.definition_kind,
        "definitionCode": evidence.definition_code,
        "definitionVersion": evidence.definition_version,
        "asOfDate": evidence.as_of_date.isoformat(),
        "status": evidence.status,
        "sourceStatuses": evidence.source_statuses_json,
        "blockedDomains": evidence.blocked_domains_json,
        "providerVersions": evidence.provider_versions_json,
        "providerEvidenceHashes": evidence.provider_evidence_hashes_json,
        "evidenceHash": evidence.evidence_hash,
        "generatedAt": evidence.generated_at.isoformat() if evidence.generated_at else None,
    }


def reconstruct_evidence(request):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(
            request,
            required_permission=ASOF_PERMISSION,
        )
    except HrDataAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _payload(request)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
    as_of_date = parse_date(str(payload.get("asOfDate") or "").strip())
    if as_of_date is None:
        return _error("ASOF_DATE_INVALID", "asOfDate 必须是 YYYY-MM-DD", status=400)
    try:
        outcome = AsOfReconstructionService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).reconstruct(
            evidence_no=payload.get("evidenceNo", ""),
            definition_kind=payload.get("definitionKind", ""),
            definition_code=payload.get("definitionCode", ""),
            definition_version=payload.get("definitionVersion"),
            as_of_date=as_of_date,
        )
    except AsOfReconstructionError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))
    response = JsonResponse(
        {
            "data": {**_serialize(outcome.evidence), "created": outcome.created},
            "apiVersion": "1.0",
            "schemaVersion": "hr18.asof-evidence.1",
        },
        status=201 if outcome.created else 200,
    )
    response["Cache-Control"] = "no-store"
    return response
