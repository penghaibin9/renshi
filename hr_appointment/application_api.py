"""Canonical HTTP authority for HR14 application and eligibility workflow."""

from __future__ import annotations

import uuid

from django.http import JsonResponse

from .api import HrAppointmentAccessError, _error, _payload, resolve_request_tenant
from .permissions import APPLICATION_PERMISSION, MANAGE_PERMISSION, REVIEW_PERMISSION
from .services.application_service import (
    AppointmentApplicationError,
    AppointmentApplicationInput,
    AppointmentApplicationService,
)


def _status(code: str) -> int:
    if code in {"APPOINTMENT_CASE_NOT_FOUND", "APPOINTMENT_BATCH_NOT_FOUND"}:
        return 404
    if code in {
        "APPOINTMENT_BATCH_NOT_OPEN",
        "APPOINTMENT_CASE_INVALID_STATE",
        "APPOINTMENT_APPLICATION_CORRECTION_WINDOW_CLOSED",
        "APPOINTMENT_ELIGIBILITY_REVIEW_NOT_OPEN",
        "APPOINTMENT_REVIEW_NOT_OPEN",
        "APPOINTMENT_POLICY_VERSION_MISMATCH",
        "APPOINTMENT_POSITION_NOT_IN_FROZEN_SUPPLY",
        "APPOINTMENT_APPLICATION_LEVEL_MISMATCH",
    }:
        return 409
    return 400


def _serialize(case):
    return {
        "id": str(case.id),
        "caseNo": case.case_no,
        "personId": str(case.person_id),
        "policyVersionId": str(case.policy_version_id),
        "positionInstanceId": case.position_instance_id,
        "batchNo": case.batch_no,
        "requestedLevelCode": case.requested_level_code,
        "status": case.status,
    }


def _service(request, *, permission: str):
    tenant_id = resolve_request_tenant(request, required_permission=permission)
    return AppointmentApplicationService(
        tenant_id,
        actor_user_id=getattr(request.user, "id", None),
    )


def create_application(request):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        service = _service(request, permission=APPLICATION_PERMISSION)
    except HrAppointmentAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _payload(request)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
    try:
        person_id = uuid.UUID(str(payload.get("personId", "")))
        policy_version_id = uuid.UUID(str(payload.get("policyVersionId", "")))
        position_instance_id = int(payload.get("positionInstanceId"))
        if position_instance_id <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return _error(
            "APPOINTMENT_APPLICATION_IDENTITY_INVALID",
            "personId/policyVersionId 必须是 UUID，positionInstanceId 必须是正整数",
            status=400,
        )
    try:
        case = service.create_draft(
            AppointmentApplicationInput(
                case_no=payload.get("caseNo", ""),
                person_id=person_id,
                policy_version_id=policy_version_id,
                position_instance_id=position_instance_id,
                batch_no=payload.get("batchNo", ""),
                requested_level_code=payload.get("requestedLevelCode", ""),
            )
        )
    except AppointmentApplicationError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))
    response = JsonResponse(
        {
            "data": _serialize(case),
            "apiVersion": "1.0",
            "schemaVersion": "hr14.application.1",
        },
        status=201,
    )
    response["Cache-Control"] = "no-store"
    return response


def _transition(request, case_id, method_name, *, permission: str):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        service = _service(request, permission=permission)
    except HrAppointmentAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        case = getattr(service, method_name)(case_id)
    except AppointmentApplicationError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))
    response = JsonResponse(
        {
            "data": _serialize(case),
            "apiVersion": "1.0",
            "schemaVersion": "hr14.application.1",
        }
    )
    response["Cache-Control"] = "no-store"
    return response


def submit_application(request, case_id):
    return _transition(
        request,
        case_id,
        "submit",
        permission=APPLICATION_PERMISSION,
    )


def return_application(request, case_id):
    return _transition(
        request,
        case_id,
        "return_for_correction",
        permission=MANAGE_PERMISSION,
    )


def pass_eligibility(request, case_id):
    return _transition(
        request,
        case_id,
        "pass_eligibility",
        permission=MANAGE_PERMISSION,
    )


def reject_eligibility(request, case_id):
    return _transition(
        request,
        case_id,
        "reject_eligibility",
        permission=MANAGE_PERMISSION,
    )


def withdraw_application(request, case_id):
    return _transition(
        request,
        case_id,
        "withdraw",
        permission=APPLICATION_PERMISSION,
    )


def start_review(request, case_id):
    return _transition(
        request,
        case_id,
        "start_review",
        permission=REVIEW_PERMISSION,
    )
