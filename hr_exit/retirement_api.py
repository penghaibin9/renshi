"""Canonical HTTP authority for HR16 retirement facts and pension progress."""

from __future__ import annotations

from django.http import JsonResponse
from django.utils.dateparse import parse_date

from .api import (
    EFFECT_PERMISSION,
    MANAGE_PERMISSION,
    HrExitAccessError,
    _error,
    _payload,
    resolve_request_tenant,
)
from .services.retirement_service import RetirementFactError, RetirementFactService


def _status(code: str) -> int:
    if code in {"EXIT_FACT_NOT_FOUND", "RETIREMENT_FACT_NOT_FOUND"}:
        return 404
    if code in {
        "RETIREMENT_EXIT_NOT_EFFECTIVE",
        "RETIREMENT_EXIT_TYPE_REQUIRED",
        "RETIREMENT_FACT_IDEMPOTENCY_CONFLICT",
        "RETIREMENT_FACT_ALREADY_EXISTS",
        "RETIREMENT_PENSION_STATUS_REGRESSION",
    }:
        return 409
    return 400


def _serialize(fact):
    return {
        "id": str(fact.id),
        "factNo": fact.fact_no,
        "personId": str(fact.person_id),
        "exitFactId": str(fact.exit_fact_id),
        "retirementType": fact.retirement_type,
        "statutoryDate": fact.statutory_date.isoformat() if fact.statutory_date else None,
        "effectiveDate": fact.effective_date.isoformat(),
        "pensionProcessingStatus": fact.pension_processing_status,
        "status": fact.status,
    }


def finalize_retirement(request, exit_fact_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(
            request, required_permission=EFFECT_PERMISSION
        )
    except HrExitAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _payload(request)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
    statutory_date = None
    if payload.get("statutoryDate"):
        try:
            statutory_date = parse_date(str(payload["statutoryDate"]))
        except ValueError:
            statutory_date = None
        if statutory_date is None:
            return _error(
                "RETIREMENT_STATUTORY_DATE_INVALID",
                "statutoryDate 必须是 YYYY-MM-DD",
                status=400,
            )
    try:
        result = RetirementFactService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).finalize(
            exit_fact_id=exit_fact_id,
            fact_no=payload.get("factNo", ""),
            retirement_type=payload.get("retirementType", ""),
            statutory_date=statutory_date,
        )
    except RetirementFactError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))
    response = JsonResponse(
        {
            "data": {**_serialize(result.fact), "created": result.created},
            "apiVersion": "1.0",
            "schemaVersion": "hr16.retirement-fact.1",
        },
        status=201 if result.created else 200,
    )
    response["Cache-Control"] = "no-store"
    return response


def set_pension_status(request, retirement_fact_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(
            request, required_permission=MANAGE_PERMISSION
        )
    except HrExitAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _payload(request)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
    try:
        fact = RetirementFactService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).set_pension_status(
            retirement_fact_id,
            status=payload.get("status", ""),
        )
    except RetirementFactError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))
    response = JsonResponse(
        {
            "data": _serialize(fact),
            "apiVersion": "1.0",
            "schemaVersion": "hr16.retirement-fact.1",
        }
    )
    response["Cache-Control"] = "no-store"
    return response
