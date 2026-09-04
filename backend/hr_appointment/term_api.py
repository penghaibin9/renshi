"""Canonical API endpoints for HR14 appointment-term governance."""

from __future__ import annotations

from decimal import Decimal

from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_date

from .api import HrAppointmentAccessError, _error, _payload, resolve_request_tenant
from .services.term_service import AppointmentTermError, AppointmentTermService

TERM_PERMISSION = "hr.appointment.term"


def _date(value, field: str, *, required=True):
    if value in (None, "") and not required:
        return None
    parsed = parse_date(str(value or "").strip())
    if parsed is None:
        raise ValueError(field)
    return parsed


def _response(data, *, status=200, schema: str):
    response = JsonResponse(
        {"data": data, "apiVersion": "1.0", "schemaVersion": schema},
        status=status,
    )
    response["Cache-Control"] = "no-store"
    return response


def _service(request):
    tenant_id = resolve_request_tenant(request, required_permission=TERM_PERMISSION)
    return AppointmentTermService(
        tenant_id,
        actor_user_id=getattr(request.user, "id", None),
    )


def _service_error(exc: AppointmentTermError):
    if exc.code in {
        "APPOINTMENT_FACT_NOT_FOUND",
        "APPOINTMENT_CASE_NOT_FOUND",
        "APPOINTMENT_TERM_NOT_FOUND",
        "APPOINTMENT_RENEWAL_NOT_FOUND",
        "APPOINTMENT_CHANGE_NOT_FOUND",
    }:
        status = 404
    elif exc.code in {
        "APPOINTMENT_FACT_NOT_EFFECTIVE",
        "APPOINTMENT_TERM_IDEMPOTENCY_CONFLICT",
        "APPOINTMENT_TERM_INVALID_STATE",
        "APPOINTMENT_TERM_NOT_DUE",
        "APPOINTMENT_RENEWAL_INVALID_TERM_STATE",
        "APPOINTMENT_RENEWAL_OVERLAP",
        "ASSESSMENT_REQUIRED_UNAVAILABLE",
        "APPOINTMENT_RENEWAL_IDEMPOTENCY_CONFLICT",
        "APPOINTMENT_RENEWAL_ALREADY_OPEN",
        "APPOINTMENT_RENEWAL_INVALID_STATE",
        "APPOINTMENT_CHANGE_INVALID_TERM_STATE",
        "APPOINTMENT_CHANGE_IDEMPOTENCY_CONFLICT",
        "APPOINTMENT_CHANGE_ALREADY_OPEN",
        "APPOINTMENT_CHANGE_INVALID_STATE",
    }:
        status = 409
    else:
        status = 400
    return _error(exc.code, str(exc), status=status)


def register_term(request, fact_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        service = _service(request)
        payload = _payload(request)
        effective_to = _date(payload.get("effectiveTo"), "effectiveTo", required=False)
        renewal_due_at = _date(payload.get("renewalDueAt"), "renewalDueAt", required=False)
    except HrAppointmentAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    except ValueError as exc:
        if str(exc) == "INVALID_JSON":
            return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
        return _error("INVALID_DATE", f"{exc} 必须是 YYYY-MM-DD", status=400)
    try:
        term = service.register_from_effective_fact(
            appointment_fact_id=fact_id,
            term_no=payload.get("termNo", ""),
            effective_to=effective_to,
            renewal_due_at=renewal_due_at,
        )
    except AppointmentTermError as exc:
        return _service_error(exc)
    return _response(
        {
            "id": str(term.id),
            "termNo": term.term_no,
            "appointmentFactId": str(term.appointment_fact_id),
            "effectiveFrom": term.effective_from.isoformat(),
            "effectiveTo": term.effective_to.isoformat() if term.effective_to else None,
            "renewalDueAt": term.renewal_due_at.isoformat() if term.renewal_due_at else None,
            "status": term.status,
        },
        status=201,
        schema="hr14.term.1",
    )


def mark_expiring(request, term_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        service = _service(request)
    except HrAppointmentAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        term = service.mark_expiring(term_id)
    except AppointmentTermError as exc:
        return _service_error(exc)
    return _response(
        {"id": str(term.id), "termNo": term.term_no, "status": term.status, "version": term.version},
        schema="hr14.term-status.1",
    )


def mark_expired(request, term_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        service = _service(request)
        payload = _payload(request)
        as_of = _date(payload.get("asOf"), "asOf", required=False)
    except HrAppointmentAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    except ValueError as exc:
        if str(exc) == "INVALID_JSON":
            return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
        return _error("INVALID_DATE", f"{exc} 必须是 YYYY-MM-DD", status=400)
    try:
        term = service.mark_expired(term_id, as_of=as_of or timezone.localdate())
    except AppointmentTermError as exc:
        return _service_error(exc)
    return _response(
        {"id": str(term.id), "termNo": term.term_no, "status": term.status, "version": term.version},
        schema="hr14.term-status.1",
    )


def open_renewal(request, term_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        service = _service(request)
        payload = _payload(request)
        proposed_from = _date(payload.get("proposedEffectiveFrom"), "proposedEffectiveFrom")
        proposed_to = _date(payload.get("proposedEffectiveTo"), "proposedEffectiveTo", required=False)
    except HrAppointmentAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    except ValueError as exc:
        if str(exc) == "INVALID_JSON":
            return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
        return _error("INVALID_DATE", f"{exc} 必须是 YYYY-MM-DD", status=400)
    try:
        renewal = service.open_renewal(
            term_id=term_id,
            renewal_no=payload.get("renewalNo", ""),
            route=payload.get("route", ""),
            proposed_effective_from=proposed_from,
            proposed_effective_to=proposed_to,
            proposed_level_code=payload.get("proposedLevelCode", ""),
            hr12_term_result_ref=payload.get("hr12TermResultRef", ""),
        )
    except AppointmentTermError as exc:
        return _service_error(exc)
    return _response(
        {
            "id": str(renewal.id),
            "renewalNo": renewal.renewal_no,
            "sourceTermId": str(renewal.source_term_id),
            "attemptNo": renewal.attempt_no,
            "route": renewal.route,
            "status": renewal.status,
        },
        status=201,
        schema="hr14.renewal-case.1",
    )


def decide_renewal(request, renewal_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        service = _service(request)
        payload = _payload(request)
    except HrAppointmentAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
    try:
        outcome = service.decide_renewal(
            renewal_id,
            outcome=payload.get("outcome", ""),
            decision_snapshot=payload.get("decisionSnapshot"),
        )
    except AppointmentTermError as exc:
        return _service_error(exc)
    return _response(
        {
            "id": str(outcome.renewal.id),
            "renewalNo": outcome.renewal.renewal_no,
            "status": outcome.renewal.status,
            "termStatus": outcome.term.status,
            "termEffectApplied": False,
        },
        schema="hr14.renewal-decision.1",
    )


def open_change(request, term_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        service = _service(request)
        payload = _payload(request)
        effective_date = _date(payload.get("effectiveDate"), "effectiveDate")
    except HrAppointmentAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    except ValueError as exc:
        if str(exc) == "INVALID_JSON":
            return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
        return _error("INVALID_DATE", f"{exc} 必须是 YYYY-MM-DD", status=400)
    try:
        change = service.open_change(
            term_id=term_id,
            change_no=payload.get("changeNo", ""),
            change_type=payload.get("changeType", ""),
            effective_date=effective_date,
            target_position_instance_id=payload.get("targetPositionInstanceId"),
            target_level_code=payload.get("targetLevelCode", ""),
            reason=payload.get("reason", ""),
        )
    except AppointmentTermError as exc:
        return _service_error(exc)
    return _response(
        {
            "id": str(change.id),
            "changeNo": change.change_no,
            "sourceTermId": str(change.source_term_id),
            "attemptNo": change.attempt_no,
            "changeType": change.change_type,
            "status": change.status,
        },
        status=201,
        schema="hr14.term-change.1",
    )


def decide_change(request, change_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        service = _service(request)
        payload = _payload(request)
    except HrAppointmentAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
    try:
        outcome = service.decide_change(
            change_id,
            outcome=payload.get("outcome", ""),
            decision_snapshot=payload.get("decisionSnapshot"),
        )
    except AppointmentTermError as exc:
        return _service_error(exc)
    return _response(
        {
            "id": str(outcome.change.id),
            "changeNo": outcome.change.change_no,
            "status": outcome.change.status,
            "termStatus": outcome.term.status,
            "termEffectApplied": False,
        },
        schema="hr14.term-change-decision.1",
    )


def reserve_change_position(request, change_id):
    """Hold the exact HR02 target position for an HR14 transfer change."""
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        service = _service(request)
    except HrAppointmentAccessError as exc:
        return _error(exc.code, exc.message, status=403)

    from hr_appointment.term_models import AppointmentChangeCase
    from hr_structure.scope import Hr02Scope
    from hr_structure.services.position import PositionService, PositionServiceError

    change = AppointmentChangeCase.objects.filter(
        id=change_id,
        tenant_id=service.tenant_id,
        change_type=AppointmentChangeCase.ChangeType.TRANSFER,
        status=AppointmentChangeCase.Status.APPROVED,
    ).first()
    if change is None or not change.target_position_instance_id:
        return _error(
            "APPOINTMENT_TRANSFER_NOT_RESERVABLE",
            "只有已批准且目标岗位完整的转岗案件可以预占",
            status=409,
        )
    try:
        reservation = PositionService(
            Hr02Scope("SCHOOL", tenant_id=service.tenant_id),
            actor=str(getattr(request.user, "id", "") or ""),
        ).reserve(
            source_domain="HR14",
            source_business_type="TERM_CHANGE",
            source_business_id=str(change.id),
            position_id=change.target_position_instance_id,
            count=1,
            fte=Decimal("1.00"),
            idempotency_key=f"hr14:term-change:{service.tenant_id}:{change.id}:{change.target_position_instance_id}",
        )
    except PositionServiceError as exc:
        return _error(exc.code, str(exc), status=409)
    return _response(
        {
            "reservationId": reservation.id,
            "status": reservation.status,
            "positionInstanceId": reservation.position_id_id,
        },
        status=201,
        schema="hr14.term-change-reservation.1",
    )
