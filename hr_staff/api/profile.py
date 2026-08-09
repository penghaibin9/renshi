"""
hr_staff/api/profile.py —— HR03-02 主档 Profile bootstrap API（S5）。

GET /api/hr/v1/staff/{staff_id}/profile?asOf=
- 404 STAFF_NOT_FOUND（跨租户同样返回 404，不泄漏存在性）
- 403 STAFF_SCOPE_DENIED（越权 fail-closed）
- 高敏字段不进 bootstrap；reveal 走独立 endpoint（S8）
"""

from __future__ import annotations

from django.views.decorators.http import require_GET

from hr_staff.api.base import (
    api_root,
    error_response,
    json_response,
    make_staff_context,
)
from hr_staff.context import HrStaffContextError
from hr_staff.permissions import require_hr_staff_permission
from hr_staff.selectors.profile import ProfileSelector, StaffNotFound, StaffScopeDenied

SCHEMA_VERSION = "hr03.profile.1"


@require_GET
@require_hr_staff_permission("hr.staff.view")
def profile_bootstrap(request, staff_id):
    try:
        context = make_staff_context(request)
    except HrStaffContextError as exc:
        return error_response(request, exc.code, exc.message, status=403)

    try:
        data = ProfileSelector(context).bootstrap(staff_id)
    except StaffNotFound:
        return error_response(request, "STAFF_NOT_FOUND", "未找到该教职工", status=404)
    except StaffScopeDenied:
        return error_response(
            request, "STAFF_SCOPE_DENIED", "无权访问该教职工", status=403
        )
    except Exception as exc:
        return error_response(
            request,
            "PROFILE_QUERY_FAILED",
            "主档查询失败",
            status=500,
            details={"errorClass": exc.__class__.__name__},
        )

    payload = api_root(request)
    payload["schemaVersion"] = SCHEMA_VERSION
    payload["asOf"] = context.as_of.isoformat()
    payload["dataBasis"] = data["identityHeader"]["dataBasis"]
    payload["data"] = data
    return json_response(request, payload)
