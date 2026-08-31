"""
hr_changes/api/identity_changes.py —— 岗位与身份变更 API（S5）。

GET  /api/hr/v1/changes/identity-changes            列表
POST /api/hr/v1/changes/identity-changes            发起（IdentityChangeService）
GET  /api/hr/v1/changes/identity-changes/{case_id}  详情（含变更矩阵）
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
from hr_changes.models import HrPersonnelChangeCase
from hr_changes.permissions import require_hr_change_permission
from hr_changes.selectors.case_detail import CaseDetailSelector
from hr_changes.selectors.identity_selector import IDENTITY_ACTIONS, IdentitySelector
from hr_changes.services.change_service import ChangeServiceError
from hr_changes.services.identity_change_service import IdentityChangeService


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


@require_http_methods(["GET", "POST"])
def identity_change_collection(request):
    """同一路径按 method 分派，避免 create writer 成为不可达死代码。"""
    if request.method == "POST":
        return identity_change_create(request)
    return identity_change_list(request)


@require_GET
@require_hr_change_permission("hr.change.identity_change.create")
def identity_change_list(request):
    ctx, err = _context(request)
    if err:
        return err
    payload = api_root(request)
    payload["schemaVersion"] = "hr06.identity-changes.list.1"
    payload["data"] = IdentitySelector(ctx.tenant_id).list()
    return json_response(request, payload)


@require_http_methods(["POST"])
@require_hr_change_permission("hr.change.identity_change.create")
def identity_change_create(request):
    ctx, err = _context(request)
    if err:
        return err
    try:
        body = _body(request)
    except ChangeServiceError as exc:
        return _service_error(request, exc)
    try:
        case = IdentityChangeService(
            ctx.tenant_id, actor_user_id=request.user.id
        ).create_identity_change(
            staff_master_id=body["staffMasterId"],
            action_id=body["actionId"],
            reason_id=body["reasonId"],
            requested_effective_at=body["requestedEffectiveAt"],
            proposals=body.get("proposals", []),
            source_assignment_id=body.get("sourceAssignmentId"),
            priority=body.get("priority", "NORMAL"),
        )
    except (ChangeServiceError, KeyError) as exc:
        if isinstance(exc, KeyError):
            return error_response(
                request,
                "CHANGE_INVALID_PAYLOAD",
                f"缺少必填参数: {exc.args[0]}",
                status=400,
            )
        return _service_error(request, exc)
    data = _detail(ctx.tenant_id, case.id)
    payload = api_root(request)
    payload["schemaVersion"] = "hr06.identity-changes.create.1"
    payload["data"] = data
    return json_response(request, payload, status=201)


@require_GET
@require_hr_change_permission("hr.change.view")
def identity_change_detail(request, case_id):
    ctx, err = _context(request)
    if err:
        return err
    data = _detail(ctx.tenant_id, case_id)
    if data is None:
        return error_response(request, "CHANGE_NOT_FOUND", "案件不存在", status=404)
    payload = api_root(request)
    payload["schemaVersion"] = "hr06.identity-changes.detail.1"
    payload["data"] = data
    return json_response(request, payload)


def _detail(tenant_id, case_id):
    case = HrPersonnelChangeCase.objects.filter(
        tenant_id=tenant_id, id=case_id
    ).first()
    if case is None:
        return None
    data = CaseDetailSelector(tenant_id).get(case.id)
    data["changeMatrix"] = IdentityChangeService(tenant_id).change_matrix(case)
    data["validation"] = IdentityChangeService(tenant_id).validate_identity_change(case)
    return data
