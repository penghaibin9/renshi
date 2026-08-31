"""Canonical apply-effect endpoints for approved HR14 term governance decisions."""

from __future__ import annotations

from django.http import JsonResponse
from django.utils.dateparse import parse_date

from .api import HrAppointmentAccessError, _error, _payload, resolve_request_tenant
from .services.term_effect_service import (
    AppointmentTermEffectError,
    AppointmentTermEffectService,
)

TERM_PERMISSION = "hr.appointment.term"


def _date(value, field: str, *, required=False):
    if value in (None, "") and not required:
        return None
    parsed = parse_date(str(value or "").strip())
    if parsed is None:
        raise ValueError(field)
    return parsed


def _service(request):
    tenant_id = resolve_request_tenant(request, required_permission=TERM_PERMISSION)
    return AppointmentTermEffectService(
        tenant_id,
        actor_user_id=getattr(request.user, "id", None),
    )


def _service_error(exc: AppointmentTermEffectError):
    if exc.code in {
        "APPOINTMENT_RENEWAL_NOT_FOUND",
        "APPOINTMENT_CHANGE_NOT_FOUND",
        "APPOINTMENT_TERM_NOT_FOUND",
        "APPOINTMENT_FACT_NOT_FOUND",
        "APPOINTMENT_STAFF_NOT_FOUND",
        "APPOINTMENT_RESERVATION_NOT_FOUND",
    }:
        status = 404
    elif exc.code in {
        "APPOINTMENT_RENEWAL_NOT_APPROVED",
        "APPOINTMENT_RENEWAL_TERM_STATE_INVALID",
        "APPOINTMENT_REAPPOINTMENT_REQUIRED",
        "APPOINTMENT_CHANGE_NOT_APPROVED",
        "APPOINTMENT_CHANGE_TERM_STATE_INVALID",
        "APPOINTMENT_CHANGE_OUTSIDE_TERM",
        "APPOINTMENT_CORRECTION_EFFECT_AUTHORITY_REQUIRED",
        "APPOINTMENT_PRIMARY_ASSIGNMENT_REQUIRED",
        "APPOINTMENT_PRIMARY_ASSIGNMENT_MISMATCH",
        "APPOINTMENT_POSITION_NOT_ACTIVE",
        "APPOINTMENT_TRANSFER_RESERVATION_REQUIRED",
        "APPOINTMENT_RESERVATION_INVALID_STATE",
        "APPOINTMENT_RESERVATION_EXPIRED",
        "APPOINTMENT_RESERVATION_POSITION_MISMATCH",
        "APPOINTMENT_RESERVATION_SOURCE_MISMATCH",
        "APPOINTMENT_FACT_ALREADY_SUPERSEDED",
        "APPOINTMENT_TERM_ALREADY_SUPERSEDED",
        "APPOINTMENT_SOURCE_FACT_ALREADY_ENDED",
        "APPOINTMENT_TERM_EFFECT_IDEMPOTENCY_CONFLICT",
        "APPOINTMENT_RENEWAL_APPLIED_INCOMPLETE",
        "APPOINTMENT_CHANGE_APPLIED_INCOMPLETE",
    }:
        status = 409
    else:
        status = 400
    return _error(exc.code, str(exc), status=status)


def _success(result, *, schema: str):
    response = JsonResponse(
        {
            "data": {
                "applied": True,
                "successorFactId": str(result.fact.id),
                "appointmentNo": result.fact.appointment_no,
                "appointmentStatus": result.fact.status,
                "successorTermId": str(result.term.id) if result.term else None,
                "successorTermNo": result.term.term_no if result.term else None,
                "termStatus": result.term.status if result.term else None,
                "effectReceipt": result.fact.effect_receipt_json,
            },
            "apiVersion": "1.0",
            "schemaVersion": schema,
        }
    )
    response["Cache-Control"] = "no-store"
    return response


def _provider_failure(result, *, schema: str):
    response = JsonResponse(
        {
            "error": {
                "code": "APPOINTMENT_TERM_EFFECT_FAILED",
                "message": result.error,
                "retryable": True,
            },
            "data": {
                "applied": False,
                "pendingFactId": str(result.fact.id),
                "appointmentNo": result.fact.appointment_no,
                "appointmentStatus": result.fact.status,
            },
            "apiVersion": "1.0",
            "schemaVersion": schema,
        },
        status=503,
    )
    response["Cache-Control"] = "no-store"
    return response


def apply_renewal_effect(request, renewal_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        service = _service(request)
        payload = _payload(request)
        renewal_due_at = _date(payload.get("renewalDueAt"), "renewalDueAt")
    except HrAppointmentAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    except ValueError as exc:
        if str(exc) == "INVALID_JSON":
            return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
        return _error("INVALID_DATE", f"{exc} 必须是 YYYY-MM-DD", status=400)
    try:
        result = service.apply_renewal(
            renewal_id,
            appointment_no=payload.get("appointmentNo", ""),
            successor_term_no=payload.get("successorTermNo", ""),
            renewal_due_at=renewal_due_at,
        )
    except AppointmentTermEffectError as exc:
        return _service_error(exc)
    if not result.applied:
        return _provider_failure(result, schema="hr14.renewal-effect.1")
    return _success(result, schema="hr14.renewal-effect.1")


def apply_change_effect(request, change_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        service = _service(request)
        payload = _payload(request)
        renewal_due_at = _date(payload.get("renewalDueAt"), "renewalDueAt")
    except HrAppointmentAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    except ValueError as exc:
        if str(exc) == "INVALID_JSON":
            return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
        return _error("INVALID_DATE", f"{exc} 必须是 YYYY-MM-DD", status=400)
    try:
        result = service.apply_change(
            change_id,
            appointment_no=payload.get("appointmentNo", ""),
            successor_term_no=payload.get("successorTermNo", ""),
            reservation_id=payload.get("reservationId"),
            renewal_due_at=renewal_due_at,
        )
    except AppointmentTermEffectError as exc:
        return _service_error(exc)
    if not result.applied:
        return _provider_failure(result, schema="hr14.term-change-effect.1")
    return _success(result, schema="hr14.term-change-effect.1")
