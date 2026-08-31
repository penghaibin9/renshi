"""
hr_staff/api/assignments.py —— HR03-03 任职履历 API（S6，只读）。

GET /api/hr/v1/staff/{staff_id}/assignments?asOf=
GET /api/hr/v1/staff/{staff_id}/employment-relationships
GET /api/hr/v1/staff/{staff_id}/timeline

正式写 API 不暴露成普通前端 CRUD；由 S10 事件接收（domain service + outbox consumer）驱动。
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
from hr_staff.selectors.assignments import (
    AssignmentHistorySelector,
    StaffNotFound,
)

SCHEMA_ASSIGNMENTS = "hr03.assignments.1"
SCHEMA_RELATIONSHIPS = "hr03.employment-relationships.1"
SCHEMA_TIMELINE = "hr03.timeline.1"


def _run(request, staff_id, selector_fn, schema):
    try:
        context = make_staff_context(request)
    except HrStaffContextError as exc:
        return error_response(request, exc.code, exc.message, status=403)
    try:
        data = selector_fn(AssignmentHistorySelector(context), staff_id)
    except StaffNotFound:
        return error_response(request, "STAFF_NOT_FOUND", "未找到该教职工", status=404)
    except Exception as exc:
        return error_response(
            request,
            "HISTORY_QUERY_FAILED",
            "履历查询失败",
            status=500,
            details={"errorClass": exc.__class__.__name__},
        )
    payload = api_root(request)
    payload["schemaVersion"] = schema
    payload["asOf"] = context.as_of.isoformat()
    payload["data"] = data
    return json_response(request, payload)


@require_GET
@require_hr_staff_permission("hr.staff.assignment.view")
def assignments(request, staff_id):
    return _run(request, staff_id, lambda sel, sid: sel.assignments(sid, sel.as_of), SCHEMA_ASSIGNMENTS)


@require_GET
@require_hr_staff_permission("hr.staff.assignment.view")
def employment_relationships(request, staff_id):
    return _run(request, staff_id, lambda sel, sid: {"items": sel.relationships(sid)}, SCHEMA_RELATIONSHIPS)


@require_GET
@require_hr_staff_permission("hr.staff.assignment.view")
def timeline(request, staff_id):
    return _run(request, staff_id, lambda sel, sid: {"events": sel.timeline(sid)}, SCHEMA_TIMELINE)
