"""Canonical evidence API for append-only HR16 ExitFact corrections."""

from __future__ import annotations

from django.http import JsonResponse

from hr_exit.api import (
    HrExitAccessError,
    _error,
    _optional_date,
    _optional_datetime,
    _payload,
    resolve_request_tenant,
)
from hr_exit.archive_registry import PERM_EXIT_FACT_CORRECT, PERM_EXIT_FACT_REVOKE
from hr_exit.services.fact_correction_service import (
    ExitFactCorrectionError,
    ExitFactCorrectionService,
)


_IDENTITY_KEYS = {"personId", "employmentRelationshipId", "sourceCaseId"}


def serialize_exit_fact(fact) -> dict:
    return {
        "id": str(fact.id),
        "factNo": fact.fact_no,
        "personId": str(fact.person_id),
        "employmentRelationshipId": str(fact.employment_relationship_id),
        "sourceCaseId": str(fact.source_case_id),
        "exitType": fact.exit_type,
        "employmentEndDate": fact.employment_end_date.isoformat(),
        "lastWorkingDate": (
            fact.last_working_date.isoformat() if fact.last_working_date else None
        ),
        "accessEndAt": fact.access_end_at.isoformat() if fact.access_end_at else None,
        "status": fact.status,
        "effectReceipt": fact.effect_receipt_json or {},
        "supersedesFactId": (
            str(fact.supersedes_fact_id) if fact.supersedes_fact_id else None
        ),
        "changeReason": fact.change_reason,
        "evidenceRef": fact.evidence_ref,
        "contentHash": fact.content_hash,
        "sealedAt": fact.sealed_at.isoformat(),
    }


def _service(request, permission: str) -> ExitFactCorrectionService:
    tenant_id = resolve_request_tenant(request, required_permission=permission)
    return ExitFactCorrectionService(
        tenant_id,
        actor_user_id=getattr(request.user, "id", None),
        correlation_id=request.headers.get("X-Correlation-ID", ""),
    )


def _status(code: str) -> int:
    if code == "EXIT_FACT_NOT_FOUND":
        return 404
    if code in {
        "EXIT_FACT_NOT_FORMAL",
        "EXIT_FACT_REVOKED",
        "EXIT_FACT_ALREADY_SUPERSEDED",
        "EXIT_FACT_IDEMPOTENCY_CONFLICT",
        "EXIT_FACT_CORRECTION_NO_CHANGE",
        "EXIT_FACT_DATE_RANGE_INVALID",
    }:
        return 409
    return 400


def correct_exit_fact(request, fact_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        service = _service(request, PERM_EXIT_FACT_CORRECT)
        body = _payload(request)
    except HrExitAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)

    forbidden = sorted(_IDENTITY_KEYS.intersection(body))
    if forbidden:
        return _error(
            "EXIT_FACT_IDENTITY_IMMUTABLE",
            "身份字段只能继承原事实: " + ", ".join(forbidden),
            status=409,
        )

    changes = {}
    try:
        if "exitType" in body:
            changes["exit_type"] = str(body.get("exitType") or "").strip().upper()
        if "employmentEndDate" in body:
            changes["employment_end_date"] = _optional_date(
                body.get("employmentEndDate"), field="employmentEndDate"
            )
        if "lastWorkingDate" in body:
            changes["last_working_date"] = _optional_date(
                body.get("lastWorkingDate"), field="lastWorkingDate"
            )
        if "accessEndAt" in body:
            changes["access_end_at"] = _optional_datetime(
                body.get("accessEndAt"), field="accessEndAt"
            )
    except ValueError as exc:
        return _error("INVALID_FIELD", f"字段格式错误: {exc}", status=400)

    try:
        fact = service.correct(
            fact_id=fact_id,
            fact_no=body.get("factNo", ""),
            reason_code=body.get("reasonCode", ""),
            evidence_ref=body.get("evidenceRef", ""),
            changes=changes,
        )
    except ExitFactCorrectionError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))
    response = JsonResponse(
        {
            "data": serialize_exit_fact(fact),
            "apiVersion": "1.0",
            "schemaVersion": "hr16.exit-fact-evidence.2",
        },
        status=201,
    )
    response["Cache-Control"] = "no-store"
    return response


def revoke_exit_fact(request, fact_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        service = _service(request, PERM_EXIT_FACT_REVOKE)
        body = _payload(request)
    except HrExitAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
    try:
        fact = service.revoke(
            fact_id=fact_id,
            fact_no=body.get("factNo", ""),
            reason_code=body.get("reasonCode", ""),
            evidence_ref=body.get("evidenceRef", ""),
        )
    except ExitFactCorrectionError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))
    response = JsonResponse(
        {
            "data": serialize_exit_fact(fact),
            "apiVersion": "1.0",
            "schemaVersion": "hr16.exit-fact-evidence.2",
        },
        status=201,
    )
    response["Cache-Control"] = "no-store"
    return response
