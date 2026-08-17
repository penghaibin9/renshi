"""
hr_changes/api/temporary.py —— 借调挂职 API（S6）。

GET  /api/hr/v1/changes/temporary                列表+统计
POST /api/hr/v1/changes/temporary/{link_id}/extend   延期（默认立即应用）
POST /api/hr/v1/changes/temporary/{link_id}/plan-return  计划返岗（生成 RETURN Case）
POST /api/hr/v1/changes/temporary/{link_id}/return     执行返岗（V1 直接执行；S7 后经审批）
"""

from __future__ import annotations

import json

from django.views.decorators.http import require_GET, require_http_methods

from hr_changes.api.base import (
    api_root,
    error_response,
    json_response,
    make_hr_change_context,
)
from hr_changes.api.changes import _service_error
from hr_changes.context import HrChangeContextError
from hr_changes.permissions import require_hr_change_permission
from hr_changes.selectors.case_detail import CaseDetailSelector
from hr_changes.selectors.temporary_selector import TemporarySelector
from hr_changes.services.change_service import ChangeServiceError
from hr_changes.services.return_service import ReturnService, ReturnServiceError
from hr_changes.services.temporary_service import (
    TemporaryAssignmentService,
    TemporaryServiceError,
)


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
@require_hr_change_permission("hr.change.temporary.create")
def temporary_list(request):
    ctx, err = _context(request)
    if err:
        return err
    data = TemporarySelector(ctx.tenant_id).list(status=request.GET.get("status", ""))
    payload = api_root(request)
    payload["schemaVersion"] = "hr06.temporary.list.1"
    payload["data"] = data
    return json_response(request, payload)


@require_http_methods(["POST"])
@require_hr_change_permission("hr.change.temporary.create")
def temporary_extend(request, link_id):
    ctx, err = _context(request)
    if err:
        return err
    try:
        body = _body(request)
    except ChangeServiceError as exc:
        return _service_error(request, exc)
    try:
        extension = TemporaryAssignmentService(
            ctx.tenant_id, actor_user_id=request.user.id
        ).extend(
            link_id=link_id,
            new_return_at=body["newReturnAt"],
            reason=body.get("reason", ""),
            apply_immediately=body.get("applyImmediately", True),
        )
    except (TemporaryServiceError, KeyError) as exc:
        if isinstance(exc, KeyError):
            return error_response(request, "CHANGE_INVALID_PAYLOAD", f"缺少必填参数: {exc.args[0]}", status=400)
        return _service_error(request, exc)
    payload = api_root(request)
    payload["schemaVersion"] = "hr06.temporary.extend.1"
    payload["data"] = {
        "extensionId": str(extension.id),
        "status": extension.status,
        "oldReturnAt": extension.old_return_at.isoformat(),
        "newReturnAt": extension.new_return_at.isoformat(),
    }
    return json_response(request, payload)


@require_http_methods(["POST"])
@require_hr_change_permission("hr.change.temporary.create")
def temporary_plan_return(request, link_id):
    ctx, err = _context(request)
    if err:
        return err
    try:
        body = _body(request)
        case = ReturnService(ctx.tenant_id, actor_user_id=request.user.id).plan_return(
            link_id,
            requested_effective_at=body.get("requestedEffectiveAt"),
        )
    except (ReturnServiceError, KeyError) as exc:
        if isinstance(exc, KeyError):
            return error_response(request, "CHANGE_INVALID_PAYLOAD", f"缺少必填参数: {exc.args[0]}", status=400)
        return _service_error(request, exc)
    data = CaseDetailSelector(ctx.tenant_id).get(case.id)
    payload = api_root(request)
    payload["schemaVersion"] = "hr06.temporary.plan-return.1"
    payload["data"] = data
    return json_response(request, payload, status=201)


@require_http_methods(["POST"])
@require_hr_change_permission("hr.change.apply")
def temporary_return(request, link_id):
    ctx, err = _context(request)
    if err:
        return err
    try:
        body = _body(request)
        link = ReturnService(ctx.tenant_id, actor_user_id=request.user.id).execute_return(
            link_id,
            return_effective_at=body["returnEffectiveAt"],
            return_case_id=body.get("returnCaseId"),
        )
    except (ReturnServiceError, KeyError) as exc:
        if isinstance(exc, KeyError):
            return error_response(request, "CHANGE_INVALID_PAYLOAD", f"缺少必填参数: {exc.args[0]}", status=400)
        return _service_error(request, exc)
    payload = api_root(request)
    payload["schemaVersion"] = "hr06.temporary.return.1"
    payload["data"] = {"linkId": str(link.id), "status": link.status}
    return json_response(request, payload)
