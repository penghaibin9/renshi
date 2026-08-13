"""Canonical HTTP authority for HR14 application and eligibility workflow."""

from __future__ import annotations

import uuid

from django.http import JsonResponse

from hr_staff.models import HrAccountLink

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
        "APPOINTMENT_POPULATION_REQUIRED",
        "APPOINTMENT_PERSON_NOT_IN_FROZEN_POPULATION",
        "APPOINTMENT_POSITION_NOT_IN_FROZEN_SUPPLY",
        "APPOINTMENT_APPLICATION_LEVEL_MISMATCH",
    }:
        return 409
    if code == "APPOINTMENT_APPLICATION_SELF_ONLY":
        return 403
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


def _context(request, *, permission: str):
    tenant_id = resolve_request_tenant(request, required_permission=permission)
    return tenant_id, AppointmentApplicationService(
        tenant_id,
        actor_user_id=getattr(request.user, "id", None),
    )


def _resolve_applicant_person_id(request, tenant_id: int):
    """Resolve SELF scope from HR03 account authority; managers may act on behalf."""
    user = request.user
    if getattr(user, "is_superuser", False) or user.has_perm(MANAGE_PERMISSION):
        return None
    user_id = getattr(user, "id", None)
    if not user_id:
        raise HrAppointmentAccessError(
            "APPOINTMENT_SELF_IDENTITY_REQUIRED",
            "当前账号没有可用于岗位竞聘申报的 HR03 人员身份",
        )
    person_ids = list(
        HrAccountLink.objects.filter(
            tenant_id=tenant_id,
            staff_id__tenant_id=tenant_id,
            staff_id__person_id__tenant_id=tenant_id,
            auth_user_id=user_id,
            link_status=HrAccountLink.LinkStatus.ACTIVE,
        )
        .values_list("staff_id__person_id_id", flat=True)
        .distinct()[:2]
    )
    if not person_ids:
        raise HrAppointmentAccessError(
            "APPOINTMENT_SELF_IDENTITY_REQUIRED",
            "当前账号未绑定本校 ACTIVE HR03 人员身份",
        )
    if len(person_ids) != 1:
        raise HrAppointmentAccessError(
            "APPOINTMENT_SELF_IDENTITY_AMBIGUOUS",
            "当前账号绑定了多个 HR03 人员身份，禁止自动选择申报主体",
        )
    return person_ids[0]


def create_application(request):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id, service = _context(request, permission=APPLICATION_PERMISSION)
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
        actor_person_id = _resolve_applicant_person_id(request, tenant_id)
    except HrAppointmentAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    if actor_person_id is not None and str(actor_person_id) != str(person_id):
        return _error(
            "APPOINTMENT_APPLICATION_SELF_ONLY",
            "普通申报权限只能为当前账号绑定的本人创建岗位竞聘申请",
            status=403,
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
        tenant_id, service = _context(request, permission=permission)
    except HrAppointmentAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    kwargs = {}
    if permission == APPLICATION_PERMISSION and method_name in {"submit", "withdraw"}:
        try:
            kwargs["actor_person_id"] = _resolve_applicant_person_id(request, tenant_id)
        except HrAppointmentAccessError as exc:
            return _error(exc.code, exc.message, status=403)
    try:
        case = getattr(service, method_name)(case_id, **kwargs)
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
