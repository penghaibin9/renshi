"""
hr_changes/api/bulk.py —— 批量异动 API（S8）。

POST /api/hr/v1/changes/bulk             创建批量任务
POST /api/hr/v1/changes/bulk/{id}/prevalidate  预校验全部 item
POST /api/hr/v1/changes/bulk/{id}/execute     执行（逐人 Case → 审批 → 生效）
"""

from __future__ import annotations

import json

from django.views.decorators.http import require_http_methods

from hr_changes.api.base import (
    api_root,
    error_response,
    json_response,
    make_hr_change_context,
)
from hr_changes.api.changes import _service_error
from hr_changes.context import HrChangeContextError
from hr_changes.models import HrBulkChangeBatch, HrBulkChangeItem
from hr_changes.permissions import require_hr_change_permission
from hr_changes.services.bulk_service import BulkService, BulkServiceError
from hr_changes.services.change_service import ChangeServiceError


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


@require_http_methods(["POST"])
@require_hr_change_permission("hr.change.bulk.create")
def create_bulk(request):
    ctx, err = _context(request)
    if err:
        return err
    try:
        body = _body(request)
        from hr_changes.models import HrChangeAction

        action = HrChangeAction.objects.filter(
            tenant_id=ctx.tenant_id, id=body["actionId"]
        ).first()
        if action is None:
            return error_response(request, "CHANGE_INVALID_ACTION", "动作不存在", status=400)
        batch = HrBulkChangeBatch.objects.create(
            tenant_id=ctx.tenant_id,
            batch_no=f"BULK-{ctx.tenant_id}-{len(HrBulkChangeBatch.objects.filter(tenant_id=ctx.tenant_id)) + 1}",
            title=body.get("title", "批量异动"),
            reason=body.get("reason", ""),
            action_id=action,
            requested_effective_at=body["requestedEffectiveAt"],
            target_org_id=body.get("targetOrgId"),
            target_position_id=body.get("targetPositionId"),
            strategy=body.get("strategy", "ITEMIZED_COMMIT"),
            created_by=request.user.id,
        )
        from hr_staff.models import HrStaffMaster

        for idx, staff_id in enumerate(body["staffIds"]):
            HrBulkChangeItem.objects.create(
                batch_id=batch,
                tenant_id=ctx.tenant_id,
                staff_master_id=staff_id,
                sequence=idx + 1,
            )
    except (KeyError, ChangeServiceError) as exc:
        if isinstance(exc, KeyError):
            return error_response(request, "CHANGE_INVALID_PAYLOAD", f"缺少必填参数: {exc.args[0]}", status=400)
        return _service_error(request, exc)
    payload = api_root(request)
    payload["schemaVersion"] = "hr06.bulk.create.1"
    payload["data"] = {"batchId": str(batch.id), "batchNo": batch.batch_no, "itemCount": batch.items.count()}
    return json_response(request, payload, status=201)


@require_http_methods(["POST"])
@require_hr_change_permission("hr.change.bulk.create")
def prevalidate_bulk(request, batch_id):
    ctx, err = _context(request)
    if err:
        return err
    batch = HrBulkChangeBatch.objects.filter(tenant_id=ctx.tenant_id, id=batch_id).first()
    if batch is None:
        return error_response(request, "CHANGE_NOT_FOUND", "批量任务不存在", status=404)
    data = BulkService(ctx.tenant_id, actor_user_id=request.user.id).prevalidate(batch)
    payload = api_root(request)
    payload["schemaVersion"] = "hr06.bulk.prevalidate.1"
    payload["data"] = data
    return json_response(request, payload)


@require_http_methods(["POST"])
@require_hr_change_permission("hr.change.apply")
def execute_bulk(request, batch_id):
    ctx, err = _context(request)
    if err:
        return err
    try:
        body = _body(request)
        data = BulkService(ctx.tenant_id, actor_user_id=request.user.id).execute(
            batch_id, approve_first=body.get("approveFirst", True)
        )
    except BulkServiceError as exc:
        return _service_error(request, exc)
    payload = api_root(request)
    payload["schemaVersion"] = "hr06.bulk.execute.1"
    payload["data"] = data
    return json_response(request, payload)
