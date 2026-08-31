"""Separated correction/revocation API for sealed HR14 appointment facts."""

from __future__ import annotations

from django.http import JsonResponse

from hr_appointment.api import (
    HrAppointmentAccessError,
    _date,
    _error,
    _payload,
    resolve_request_tenant,
)
from hr_appointment.permissions import FACT_CORRECT_PERMISSION, FACT_REVOKE_PERMISSION
from hr_appointment.services.fact_authority_service import (
    AppointmentFactAuthorityError,
    AppointmentFactAuthorityService,
    fact_evidence,
)


def _status(code: str) -> int:
    if code.endswith("NOT_FOUND"):
        return 404
    if code.endswith("REQUIRED") or code.endswith("INVALID"):
        return 400
    return 409


def _context(request, permission: str):
    try:
        return resolve_request_tenant(request, required_permission=permission), None
    except HrAppointmentAccessError as exc:
        return None, _error(exc.code, exc.message, status=403)


def _response(result):
    response = JsonResponse(
        {
            "data": fact_evidence(result.fact),
            "replayed": result.replayed,
            "apiVersion": "1.0",
            "schemaVersion": "hr14.appointment-fact-authority.1",
        },
        status=200 if result.replayed else 201,
    )
    response["Cache-Control"] = "no-store"
    return response


def correct_fact(request, fact_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    tenant_id, denied = _context(request, FACT_CORRECT_PERMISSION)
    if denied:
        return denied
    try:
        payload = _payload(request)
        effective_from = (
            _date(payload.get("effectiveFrom"), field="effectiveFrom")
            if "effectiveFrom" in payload
            else None
        )
        effective_to = (
            _date(payload.get("effectiveTo"), field="effectiveTo")
            if payload.get("effectiveTo")
            else None
        )
    except ValueError as exc:
        return _error("INVALID_REQUEST", str(exc), status=400)
    try:
        position_instance_id = payload.get("positionInstanceId")
        if position_instance_id is not None:
            position_instance_id = int(position_instance_id)
            if position_instance_id <= 0:
                raise ValueError
    except (TypeError, ValueError):
        return _error("POSITION_INSTANCE_ID_INVALID", status=400)
    try:
        result = AppointmentFactAuthorityService(
            tenant_id, getattr(request.user, "id", None)
        ).correct(
            fact_id,
            appointment_no=payload.get("appointmentNo", ""),
            idempotency_key=request.headers.get("Idempotency-Key", ""),
            reason=payload.get("reason", ""),
            authority_ref=payload.get("authorityRef", ""),
            evidence=payload.get("evidence", {}),
            position_instance_id=position_instance_id,
            level_code=payload.get("levelCode") if "levelCode" in payload else None,
            effective_from=effective_from,
            effective_to=effective_to,
        )
    except AppointmentFactAuthorityError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))
    return _response(result)


def revoke_fact(request, fact_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    tenant_id, denied = _context(request, FACT_REVOKE_PERMISSION)
    if denied:
        return denied
    try:
        payload = _payload(request)
    except ValueError:
        return _error("INVALID_JSON", status=400)
    try:
        result = AppointmentFactAuthorityService(
            tenant_id, getattr(request.user, "id", None)
        ).revoke(
            fact_id,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
            reason=payload.get("reason", ""),
            authority_ref=payload.get("authorityRef", ""),
            evidence=payload.get("evidence", {}),
        )
    except AppointmentFactAuthorityError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))
    return _response(result)
