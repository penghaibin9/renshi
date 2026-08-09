"""
hr_staff/api/backgrounds.py —— HR03-04 教育资格履历 API（S7）。

GET  /api/hr/v1/staff/{staff_id}/backgrounds —— bundle（只读）
POST /api/hr/v1/staff/{staff_id}/backgrounds/education|degrees|work|credentials|honors —— 写入
写入是否允许由 FieldGovernancePolicy + hr.staff.background.manage 权限决定。
"""

from __future__ import annotations

import json

from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from hr_staff.api.base import (
    api_root,
    error_response,
    json_response,
    make_staff_context,
)
from hr_staff.context import HrStaffContextError
from hr_staff.permissions import require_hr_staff_permission
from hr_staff.selectors.backgrounds import BackgroundSelector, StaffNotFound
from hr_staff.services.background_service import (
    BackgroundPolicyDenied,
    BackgroundService,
)

SCHEMA_BACKGROUNDS = "hr03.backgrounds.1"


def _parse_json_body(request):
    try:
        return json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return None


def _body_error(request, message="请求体不是合法 JSON"):
    return error_response(request, "INVALID_REQUEST", message, status=400)


@require_GET
@require_hr_staff_permission("hr.staff.background.view")
def backgrounds(request, staff_id):
    try:
        context = make_staff_context(request)
    except HrStaffContextError as exc:
        return error_response(request, exc.code, exc.message, status=403)
    try:
        data = BackgroundSelector(context).bundle(staff_id)
    except StaffNotFound:
        return error_response(request, "STAFF_NOT_FOUND", "未找到该教职工", status=404)
    payload = api_root(request)
    payload["schemaVersion"] = SCHEMA_BACKGROUNDS
    payload["data"] = data
    return json_response(request, payload)


@require_POST
@require_hr_staff_permission("hr.staff.background.manage")
def add_background(request, staff_id, kind):
    try:
        context = make_staff_context(request)
    except HrStaffContextError as exc:
        return error_response(request, exc.code, exc.message, status=403)

    body = _parse_json_body(request)
    if body is None:
        return _body_error(request)

    svc = BackgroundService(
        context.tenant_id,
        actor_user_id=request.user.id,
        has_manage_perm=True,
    )
    try:
        if kind == "education":
            obj = svc.add_education(staff_id=staff_id, **body)
        elif kind == "degrees":
            obj = svc.add_degree(staff_id=staff_id, **body)
        elif kind == "work":
            obj = svc.add_work_experience(staff_id=staff_id, **body)
        elif kind == "credentials":
            obj = svc.add_credential(staff_id=staff_id, **body)
        elif kind == "honors":
            obj = svc.add_talent_honor(staff_id=staff_id, **body)
        else:
            return error_response(request, "INVALID_REQUEST", f"未知类型: {kind}", status=400)
    except BackgroundPolicyDenied as exc:
        return error_response(request, exc.code, str(exc), status=403)
    except Exception as exc:
        code = getattr(exc, "code", "")
        if code == "CROSS_TENANT_REFERENCE":
            return error_response(request, "CROSS_TENANT_REFERENCE", str(exc), status=403)
        if code == "STAFF_NOT_FOUND":
            return error_response(request, "STAFF_NOT_FOUND", "未找到该教职工", status=404)
        return error_response(
            request,
            "BACKGROUND_WRITE_FAILED",
            "写入失败",
            status=400,
            details={"errorClass": exc.__class__.__name__},
        )

    payload = api_root(request)
    payload["schemaVersion"] = SCHEMA_BACKGROUNDS
    payload["data"] = {"id": str(obj.id)}
    return json_response(request, payload, status=201)
