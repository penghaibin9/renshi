"""
hr_staff/api/material_requests.py —— 材料索要 API（§14.7，S12 补线）。

POST /api/hr/v1/staff/{staff_id}/material-requests  向员工索要材料
GET  /api/hr/v1/staff/{staff_id}/material-requests  材料请求列表
"""

from __future__ import annotations

import json

from django.views.decorators.http import require_GET, require_POST

from hr_staff.api.base import (
    api_root,
    error_response,
    json_response,
    make_staff_context,
)
from hr_staff.context import HrStaffContextError
from hr_staff.models import HrMaterialRequest
from hr_staff.permissions import require_hr_staff_permission


def _make(request):
    try:
        return make_staff_context(request)
    except HrStaffContextError as exc:
        return error_response(request, exc.code, exc.message, status=403)


@require_GET
@require_hr_staff_permission("hr.staff.material.upload")
def list_requests(request, staff_id):
    resp = _make(request)
    if not hasattr(resp, "tenant_id"):
        return resp
    items = HrMaterialRequest.objects.filter(
        tenant_id=resp.tenant_id, target_staff_id=staff_id
    ).order_by("-created_at")[:50]
    payload = api_root(request)
    payload["data"] = {
        "items": [
            {
                "id": str(r.id),
                "requestType": r.request_type,
                "requiredCategoryCode": r.required_category_code,
                "dueAt": r.due_at.isoformat() if r.due_at else None,
                "instruction": r.instruction,
                "status": r.status,
                "requestedBy": r.requested_by,
            }
            for r in items
        ]
    }
    return json_response(request, payload)


@require_POST
@require_hr_staff_permission("hr.staff.material.upload")
def create_request(request, staff_id):
    resp = _make(request)
    if not hasattr(resp, "tenant_id"):
        return resp
    try:
        body = json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        body = {}
    req = HrMaterialRequest.objects.create(
        tenant_id=resp.tenant_id,
        target_staff_id=staff_id,
        request_type=body.get("request_type", ""),
        required_category_code=body.get("required_category_code", ""),
        due_at=body.get("due_at"),
        instruction=body.get("instruction", ""),
        requested_by=request.user.id,
    )
    payload = api_root(request)
    payload["data"] = {"id": str(req.id), "status": req.status}
    return json_response(request, payload, status=201)
