"""
hr_changes/api/transfers.py —— 校内调动 API（S4）。

GET  /api/hr/v1/changes/transfers            调动列表
POST /api/hr/v1/changes/transfers            发起调动（transfer 专用校验）
GET  /api/hr/v1/changes/transfers/{case_id}  调动详情（含 Before/After）
POST /api/hr/v1/changes/transfers/{case_id}/reserve  预占目标岗位（批准前）
POST /api/hr/v1/changes/transfers/{case_id}/release  释放预占（未生效取消）
"""

from __future__ import annotations

import json

from django.views.decorators.http import require_GET, require_http_methods, require_POST

from hr_changes.api.base import (
    api_root,
    error_response,
    json_response,
    make_hr_change_context,
)
from hr_changes.api.changes import _service_error, _version
from hr_changes.context import HrChangeContextError
from hr_changes.integrations.hr02 import PositionGate
from hr_changes.models import HrPersonnelChangeCase
from hr_changes.permissions import require_hr_change_permission
from hr_changes.selectors.transfer_selector import TransferSelector
from hr_changes.services.change_service import ChangeServiceError
from hr_changes.services.transfer_service import TransferService


def _context(request):
    try:
        return make_hr_change_context(request), None
    except HrChangeContextError as exc:
        return None, error_response(request, exc.code, exc.message, status=403)


def _body(request):
    raw = request.body
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        raise ChangeServiceError("CHANGE_INVALID_PAYLOAD", "请求体不是合法 JSON")


@require_GET
@require_hr_change_permission("hr.change.transfer.create")
def transfer_list(request):
    ctx, err = _context(request)
    if err:
        return err
    try:
        page = max(1, int(request.GET.get("page", 1)))
        page_size = min(100, max(1, int(request.GET.get("pageSize", 20))))
    except ValueError:
        return error_response(request, "CHANGE_INVALID_PAYLOAD", "分页参数非法", status=400)
    payload = api_root(request)
    payload["schemaVersion"] = "hr06.transfers.list.1"
    payload["data"] = TransferSelector(ctx.tenant_id).list(page=page, page_size=page_size)
    return json_response(request, payload)


@require_http_methods(["POST"])
@require_hr_change_permission("hr.change.transfer.create")
def transfer_create(request):
    ctx, err = _context(request)
    if err:
        return err
    try:
        body = _body(request)
    except ChangeServiceError as exc:
        return _service_error(request, exc)
    try:
        case = TransferService(ctx.tenant_id, actor_user_id=request.user.id).create_transfer(
            staff_master_id=body["staffMasterId"],
            action_id=body["actionId"],
            reason_id=body["reasonId"],
            requested_effective_at=body["requestedEffectiveAt"],
            target_org_id=body.get("targetOrgId"),
            target_position_id=body.get("targetPositionId"),
            source_org_id=body.get("sourceOrgId"),
            source_position_id=body.get("sourcePositionId"),
            fte=body.get("fte"),
            reporting_staff_id=body.get("reportingStaffId"),
            priority=body.get("priority", "NORMAL"),
        )
    except (ChangeServiceError, KeyError) as exc:
        if isinstance(exc, KeyError):
            return error_response(request, "CHANGE_INVALID_PAYLOAD", f"缺少必填参数: {exc.args[0]}", status=400)
        return _service_error(request, exc)
    payload = api_root(request)
    payload["schemaVersion"] = "hr06.transfers.create.1"
    payload["data"] = TransferSelector(ctx.tenant_id).detail(case.id)
    return json_response(request, payload, status=201)


@require_GET
@require_hr_change_permission("hr.change.view")
def transfer_detail(request, case_id):
    ctx, err = _context(request)
    if err:
        return err
    data = TransferSelector(ctx.tenant_id).detail(case_id)
    if data is None:
        return error_response(request, "CHANGE_NOT_FOUND", "调动案件不存在", status=404)
    payload = api_root(request)
    payload["schemaVersion"] = "hr06.transfers.detail.1"
    payload["data"] = data
    return json_response(request, payload)


@require_POST
@require_hr_change_permission("hr.change.approve")
def transfer_reserve(request, case_id):
    ctx, err = _context(request)
    if err:
        return err
    case = HrPersonnelChangeCase.objects.filter(tenant_id=ctx.tenant_id, id=case_id).first()
    if case is None:
        return error_response(request, "CHANGE_NOT_FOUND", "调动案件不存在", status=404)
    try:
        reservation = PositionGate(ctx.tenant_id).reserve_for_case(case)
    except ChangeServiceError as exc:
        return _service_error(request, exc)
    from hr_changes.integrations.hr02 import Hr02GateError

    if reservation is None:
        return error_response(request, "CHANGE_INVALID_ACTION", "该动作不需要岗位预占", status=400)
    payload = api_root(request)
    payload["schemaVersion"] = "hr06.transfers.reserve.1"
    payload["data"] = {
        "reservationId": str(reservation.id),
        "status": reservation.status,
    }
    return json_response(request, payload)


@require_POST
@require_hr_change_permission("hr.change.cancel")
def transfer_release(request, case_id):
    ctx, err = _context(request)
    if err:
        return err
    case = HrPersonnelChangeCase.objects.filter(tenant_id=ctx.tenant_id, id=case_id).first()
    if case is None:
        return error_response(request, "CHANGE_NOT_FOUND", "调动案件不存在", status=404)
    try:
        reservation = PositionGate(ctx.tenant_id).release_for_case(case)
    except Hr02GateError as exc:
        return _service_error(request, exc)
    payload = api_root(request)
    payload["schemaVersion"] = "hr06.transfers.release.1"
    payload["data"] = {
        "released": reservation is not None,
        "status": reservation.status if reservation else None,
    }
    return json_response(request, payload)
