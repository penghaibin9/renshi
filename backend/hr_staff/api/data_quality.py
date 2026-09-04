"""
hr_staff/api/data_quality.py —— 数据质量 API 端点（§34，S12 补线）。

GET /api/hr/v1/staff/data-quality-scan?as_of=...
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
from hr_staff.services.data_quality_service import DataQualityService


@require_GET
@require_hr_staff_permission("hr.staff.data_quality.manage")
def scan(request):
    try:
        context = make_staff_context(request)
    except HrStaffContextError as exc:
        return error_response(request, exc.code, exc.message, status=403)

    result = DataQualityService(context.tenant_id, as_of=context.as_of).scan()
    payload = api_root(request)
    payload["data"] = result
    return json_response(request, payload)
