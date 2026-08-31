"""
hr_changes/api/rescind.py —— 异动撤销 API（S7）。

POST /api/hr/v1/changes/{case_id}/request-rescind   申请撤销（依赖检查）
POST /api/hr/v1/rescinds/{id}/approve               批准撤销
POST /api/hr/v1/rescinds/{id}/execute               执行撤销
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
from hr_changes.permissions import require_hr_change_permission
from hr_changes.services.change_service import ChangeServiceError
from hr_changes.services.rescind_service import RescindService, RescindServiceError


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


def _rescind_payload(rescind):
    return {
        "id": str(rescind.id),
        "caseId": str(rescind.change_case_id_id),
        "status": rescind.status,
        "reason": rescind.reason,
        "dependentBlockers": rescind.dependent_blockers_json,
        "restoreSnapshotHash": rescind.restore_snapshot_hash,
    }


@require_http_methods(["POST"])
@require_hr_change_permission("hr.change.rescind")
def request_rescind(request, case_id):
    ctx, err = _context(request)
    if err:
        return err
    try:
        body = _body(request)
        rescind = RescindService(ctx.tenant_id, actor_user_id=request.user.id).request_rescind(
            case_id=case_id, reason=body.get("reason", "")
        )
    except (RescindServiceError, ChangeServiceError, KeyError) as exc:
        if isinstance(exc, KeyError):
            return error_response(request, "CHANGE_INVALID_PAYLOAD", f"缺少必填参数: {exc.args[0]}", status=400)
        return _service_error(request, exc)
    payload = api_root(request)
    payload["schemaVersion"] = "hr06.rescinds.request.1"
    payload["data"] = _rescind_payload(rescind)
    return json_response(request, payload, status=201)


@require_http_methods(["POST"])
@require_hr_change_permission("hr.change.rescind")
def rescind_action(request, rescind_id, action: str):
    ctx, err = _context(request)
    if err:
        return err
    svc = RescindService(ctx.tenant_id, actor_user_id=request.user.id)
    try:
        if action == "approve":
            rescind = svc.approve_rescind(rescind_id)
        elif action == "execute":
            rescind = svc.execute_rescind(rescind_id)
        else:
            return error_response(request, "CHANGE_INVALID_ACTION", f"未知动作 {action}", status=404)
    except (RescindServiceError, ChangeServiceError) as exc:
        return _service_error(request, exc)
    payload = api_root(request)
    payload["schemaVersion"] = "hr06.rescinds.action.1"
    payload["data"] = _rescind_payload(rescind)
    return json_response(request, payload)
