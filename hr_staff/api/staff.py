"""
hr_staff/api/staff.py —— HR03-01 教职工名册 API（S4）。

GET /api/hr/v1/staff
- 响应按总册 §10.6：apiVersion/schemaVersion/requestId/asOf/scope/dataBasis/items/page/pageSize/total
- tenant fail-closed：未选择学校 → 403 TENANT_CONTEXT_REQUIRED
- 权限：hr.staff.view（越权 403，不靠空列表伪装）
- 高敏字段默认不进列表（selector 已裁剪）
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
from hr_staff.selectors.staff_list import StaffListSelector

SCHEMA_VERSION = "hr03.staff.list.1"


def _as_int(value, default):
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


@require_GET
@require_hr_staff_permission("hr.staff.view")
def staff_list(request):
    try:
        context = make_staff_context(request)
    except HrStaffContextError as exc:
        return error_response(request, exc.code, exc.message, status=403)

    page = _as_int(request.GET.get("page"), 1)
    page_size = _as_int(request.GET.get("pageSize"), 50)
    page_size = min(page_size, 200)

    params = {
        "keyword": request.GET.get("keyword", ""),
        "status": request.GET.get("status", ""),
        "category": request.GET.get("category", ""),
        "relationship_type": request.GET.get("relationship_type", ""),
        "joining_from": request.GET.get("joining_from", ""),
        "joining_to": request.GET.get("joining_to", ""),
        "has_future_change": request.GET.get("has_future_change", ""),
    }

    try:
        result = StaffListSelector(context).rows(params, page=page, page_size=page_size)
    except Exception as exc:  # 不暴露内部 traceback
        return error_response(
            request,
            "STAFF_LIST_QUERY_FAILED",
            "名册查询失败",
            status=500,
            details={"errorClass": exc.__class__.__name__},
        )

    payload = api_root(request)
    payload["schemaVersion"] = SCHEMA_VERSION
    payload["asOf"] = context.as_of.isoformat()
    payload["scope"] = {
        "type": context.scope.scope_type,
        "id": context.scope.org_id,
    }
    payload["dataBasis"] = "HR03_AUTHORITY" if context.authority_mode == "HR03_AUTHORITY" else "LEGACY_CURRENT_SNAPSHOT"
    payload.update(result)
    return json_response(request, payload)
