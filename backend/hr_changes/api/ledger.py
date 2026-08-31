"""
hr_changes/api/ledger.py —— 异动台账 API（S7）。

GET /api/hr/v1/changes/ledger             台账列表 + 筛选
GET /api/hr/v1/changes/ledger/{case_id}   案件详情（复用 CaseDetailSelector）
GET /api/hr/v1/changes/staff/{staff_id}/history  人员异动历史
"""

from __future__ import annotations

from datetime import date

from django.views.decorators.http import require_GET
from django.utils.dateparse import parse_date

from hr_changes.api.base import (
    api_root,
    error_response,
    json_response,
    make_hr_change_context,
)
from hr_changes.context import HrChangeContextError
from hr_changes.permissions import require_hr_change_permission
from hr_changes.selectors.case_detail import CaseDetailSelector
from hr_changes.selectors.ledger import LedgerSelector


def _context(request):
    try:
        return make_hr_change_context(request), None
    except HrChangeContextError as exc:
        return None, error_response(request, exc.code, exc.message, status=403)


@require_GET
@require_hr_change_permission("hr.change.ledger.view")
def ledger_list(request):
    ctx, err = _context(request)
    if err:
        return err

    def _d(v):
        return parse_date(v) if v else None

    try:
        page = max(1, int(request.GET.get("page", 1)))
        page_size = min(100, max(1, int(request.GET.get("pageSize", 20))))
        year = int(request.GET["year"]) if request.GET.get("year") else None
    except ValueError:
        return error_response(request, "CHANGE_INVALID_PAYLOAD", "筛选参数非法", status=400)

    data = LedgerSelector(ctx.tenant_id).list(
        year=year,
        org_id=_int_or_none(request.GET.get("orgId")),
        action_code=request.GET.get("action") or None,
        reason_code=request.GET.get("reason") or None,
        status=request.GET.get("status") or None,
        effective_from=_d(request.GET.get("effectiveFrom")),
        effective_to=_d(request.GET.get("effectiveTo")),
        staff_id=request.GET.get("staffId") or None,
        page=page,
        page_size=page_size,
    )
    payload = api_root(request)
    payload["schemaVersion"] = "hr06.ledger.list.1"
    payload["data"] = data
    return json_response(request, payload)


@require_GET
@require_hr_change_permission("hr.change.ledger.view")
def ledger_detail(request, case_id):
    ctx, err = _context(request)
    if err:
        return err
    data = CaseDetailSelector(ctx.tenant_id).get(case_id)
    if data is None:
        return error_response(request, "CHANGE_NOT_FOUND", "异动案件不存在", status=404)
    payload = api_root(request)
    payload["schemaVersion"] = "hr06.ledger.detail.1"
    payload["data"] = data
    return json_response(request, payload)


@require_GET
@require_hr_change_permission("hr.change.ledger.view")
def staff_history(request, staff_id):
    ctx, err = _context(request)
    if err:
        return err
    data = LedgerSelector(ctx.tenant_id).staff_history(staff_id)
    payload = api_root(request)
    payload["schemaVersion"] = "hr06.ledger.staff-history.1"
    payload["data"] = data
    return json_response(request, payload)


def _int_or_none(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
