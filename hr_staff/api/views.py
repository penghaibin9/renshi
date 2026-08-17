"""
hr_staff/api/views.py —— HR03 API views（S1 骨架）。

S1 只提供契约探针（GET /api/hr/v1/staff/contract）：
- 验证 version envelope 是否可用；
- 验证 tenant fail-closed（未选择学校 → 403 TENANT_CONTEXT_REQUIRED）；
- 声明 HR03 已安装的 schemaVersion。
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


@require_GET
def contract_probe(request):
    """
    GET /api/hr/v1/staff/contract
    契约探针：确认 tenant 上下文可用 + 返回当前 schema/常量清单摘要。
    """
    try:
        make_staff_context(request)
    except HrStaffContextError as exc:
        return error_response(request, exc.code, exc.message, status=403)

    from hr_staff.constants import (
        HR03_ERROR_CODES,
        HR03_EVENT_TYPES,
        HR_STAFF_PERMISSIONS,
    )

    payload = api_root(request)
    payload["staff"] = {
        "installed": True,
        "scopeTypes": ["SCHOOL", "COLLEGE", "DEPARTMENT", "ASSIGNMENT", "SELF", "EXPLICIT_STAFF_SET"],
        "errorCodes": sorted(HR03_ERROR_CODES),
        "permissions": list(HR_STAFF_PERMISSIONS),
        "eventTypes": sorted(HR03_EVENT_TYPES),
    }
    return json_response(request, payload)
