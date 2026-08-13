"""Canonical HTTP surface for HR14 appointment-capacity preparation."""

from django.http import JsonResponse

from .api import (
    EFFECT_PERMISSION,
    HrAppointmentAccessError,
    _datetime,
    _error,
    _payload,
    resolve_request_tenant,
)
from .services.capacity_service import AppointmentCapacityError, AppointmentCapacityService


def _capacity_status(code: str) -> int:
    if code in {
        "APPOINTMENT_CASE_NOT_FOUND",
        "APPOINTMENT_QUOTA_NOT_FOUND",
        "HR02_POSITION_NOT_FOUND",
    }:
        return 404
    if code in {
        "APPOINTMENT_CASE_NOT_RESERVABLE",
        "APPOINTMENT_QUOTA_BATCH_MISMATCH",
        "APPOINTMENT_QUOTA_POLICY_MISMATCH",
        "APPOINTMENT_QUOTA_LEVEL_MISMATCH",
        "APPOINTMENT_QUOTA_EXHAUSTED",
        "APPOINTMENT_QUOTA_ALREADY_CONSUMED",
        "APPOINTMENT_QUOTA_RESERVATION_CONFLICT",
        "APPOINTMENT_CAPACITY_RECEIPT_CONFLICT",
        "HR02_POSITION_NOT_ACTIVE",
        "HR02_POSITION_CAPACITY_EXCEEDED",
        "HR02_POSITION_RESERVATION_CONFLICT",
    }:
        return 409
    return 400


def prepare_capacity(request, case_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request, required_permission=EFFECT_PERMISSION)
    except HrAppointmentAccessError as exc:
        return _error(exc.code, exc.message, status=403)

    try:
        payload = _payload(request)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)

    quota_pool_id = payload.get("quotaPoolId")
    if not quota_pool_id:
        return _error("APPOINTMENT_QUOTA_POOL_REQUIRED", "quotaPoolId 不能为空", status=400)

    expires_at = None
    if payload.get("expiresAt"):
        try:
            expires_at = _datetime(payload.get("expiresAt"), field="expiresAt")
        except ValueError:
            return _error(
                "INVALID_DATETIME",
                "expiresAt 必须是 ISO-8601 时间",
                status=400,
            )

    try:
        hold = AppointmentCapacityService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).prepare(
            case_id=case_id,
            quota_pool_id=quota_pool_id,
            expires_at=expires_at,
        )
    except AppointmentCapacityError as exc:
        return _error(exc.code, str(exc), status=_capacity_status(exc.code))

    quota = hold.quota_reservation
    position = hold.position_reservation
    response = JsonResponse(
        {
            "data": {
                "applicationCaseId": str(case_id),
                "quotaReservationId": str(quota.id),
                "quotaStatus": quota.status,
                "hr02ReservationId": position.id,
                "hr02ReservationStatus": position.status,
                "expiresAt": position.expires_at.isoformat(),
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr14.appointment-capacity.1",
        },
        status=200,
    )
    response["Cache-Control"] = "no-store"
    return response
