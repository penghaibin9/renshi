"""Canonical amendment surface for draft/returned HR16 exit cases."""

from .api import (
    MANAGE_PERMISSION,
    HrExitAccessError,
    _case_data,
    _case_status,
    _error,
    _optional_date,
    _optional_datetime,
    _payload,
    resolve_request_tenant,
)
from .services.case_service import ExitCaseError, ExitCasePatch, ExitCaseService
from django.http import JsonResponse


_IMMUTABLE_INPUT_KEYS = {
    "caseNo",
    "personId",
    "employmentRelationshipId",
    "exitType",
}


def amend_case(request, case_id):
    if request.method != "PATCH":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request, required_permission=MANAGE_PERMISSION)
    except HrExitAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _payload(request)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)

    immutable = sorted(_IMMUTABLE_INPUT_KEYS.intersection(payload))
    if immutable:
        return _error(
            "EXIT_CASE_IDENTITY_IMMUTABLE",
            f"以下身份字段不可原地修改: {', '.join(immutable)}",
            status=409,
        )

    kwargs = {}
    try:
        if "requestedDate" in payload:
            kwargs["requested_date"] = _optional_date(
                payload.get("requestedDate"), field="requestedDate"
            )
        if "lastWorkingDate" in payload:
            kwargs["last_working_date"] = _optional_date(
                payload.get("lastWorkingDate"), field="lastWorkingDate"
            )
        if "plannedEmploymentEndDate" in payload:
            kwargs["planned_employment_end_date"] = _optional_date(
                payload.get("plannedEmploymentEndDate"),
                field="plannedEmploymentEndDate",
            )
        if "plannedAccessEndAt" in payload:
            kwargs["planned_access_end_at"] = _optional_datetime(
                payload.get("plannedAccessEndAt"),
                field="plannedAccessEndAt",
            )
    except ValueError as exc:
        return _error(
            "INVALID_FIELD",
            f"字段格式错误: {exc}",
            status=400,
        )

    if not kwargs:
        return _error(
            "EXIT_CASE_PATCH_EMPTY",
            "至少提供一个可修改的计划字段",
            status=400,
        )

    try:
        case = ExitCaseService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).update_draft(case_id, ExitCasePatch(**kwargs))
    except ExitCaseError as exc:
        return _error(exc.code, str(exc), status=_case_status(exc.code))

    response = JsonResponse(
        {
            "data": _case_data(case),
            "apiVersion": "1.0",
            "schemaVersion": "hr16.exit-case.1",
        }
    )
    response["Cache-Control"] = "no-store"
    return response
