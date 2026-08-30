"""
hr_changes/api/changes.py —— 异动案件 API（S3）。

端点（总册 §46）：
  GET/POST /api/hr/v1/changes
  GET/PATCH /api/hr/v1/changes/{id}
  POST .../{id}/validate | /preview | /submit | /start-approval
  POST .../{id}/withdraw | /return | /approve | /reject | /cancel
  GET  .../future | .../{id}/impact | .../{id}/timeline

错误信封统一；写接口版本冲突 → 409 VERSION_CONFLICT；状态非法 → 409 CHANGE_INVALID_STATE。
"""

from __future__ import annotations

import json

from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django.utils.datastructures import MultiValueDict

from hr_changes.api.base import (
    api_root,
    error_response,
    json_response,
    make_hr_change_context,
)
from hr_changes.context import HrChangeContextError
from hr_changes.permissions import require_hr_change_permission
from hr_changes.selectors.case_detail import CaseDetailSelector
from hr_changes.selectors.case_list import CaseListSelector
from hr_changes.services.change_service import ChangeService, ChangeServiceError
from hr_changes.services.apply_service import ApplyService, ApplyServiceError
from hr_changes.services.impact_service import ImpactService
from hr_changes.services.state_machine import ChangeStateError
from hr_changes.services.validation_service import ValidationService

SCHEMA_LIST = "hr06.changes.list.1"
SCHEMA_DETAIL = "hr06.changes.detail.1"
SCHEMA_CREATE = "hr06.changes.create.1"

_ACTION_PERMISSIONS = {
    "submit": "hr.change.submit",
    "start-approval": "hr.change.submit",
    "withdraw": "hr.change.submit",
    "resubmit": "hr.change.submit",
    "cancel": "hr.change.cancel",
    "return": "hr.change.approve",
    "approve": "hr.change.approve",
    "reject": "hr.change.approve",
    "apply": "hr.change.apply",
}
_FORBIDDEN_EFFECT_FIELDS = frozenset(
    {
        "status",
        "effectiveAt",
        "providerCode",
        "providerReceipt",
        "providerReceiptHash",
        "sourceFactIds",
        "targetFactIds",
        "forceEarly",
    }
)


def _context(request):
    try:
        return make_hr_change_context(request), None
    except HrChangeContextError as exc:
        return None, error_response(request, exc.code, exc.message, status=403)


def _version(request) -> int | None:
    raw = request.GET.get("version") or request.headers.get("If-Match")
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _svc(request, context):
    return ChangeService(context.tenant_id, actor_user_id=request.user.id)


def _service_error(request, exc):
    if isinstance(exc, ChangeStateError):
        return error_response(request, "CHANGE_INVALID_STATE", str(exc), status=409)
    code = getattr(exc, "code", "CHANGE_INVALID_PAYLOAD")
    message = getattr(exc, "message", str(exc))
    status = 409 if code in (
        "VERSION_CONFLICT",
        "AUTHORITY_VERSION_CONFLICT",
        "IDEMPOTENCY_KEY_CONFLICT",
        "CHANGE_INVALID_STATE",
        "CHANGE_CORRECTION_REQUIRES_APPROVAL",
    ) else 400
    return error_response(request, code, message, status=status)


def _json_body(request):
    raw = request.body
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        raise ChangeServiceError("CHANGE_INVALID_PAYLOAD", "请求体不是合法 JSON")


# ---------------------------------------------------------------------------
# 列表 / 创建 / 详情 / 更新
# ---------------------------------------------------------------------------
@require_http_methods(["GET", "POST"])
def change_list(request):
    """GET 列表 / POST 创建（共用 /api/hr/v1/changes）。"""
    if request.method == "POST":
        return _change_create(request)
    ctx, err = _context(request)
    if err:
        return err
    try:
        page = max(1, int(request.GET.get("page", 1)))
        page_size = min(100, max(1, int(request.GET.get("pageSize", 20))))
    except ValueError:
        return error_response(request, "CHANGE_INVALID_PAYLOAD", "分页参数非法", status=400)
    data = CaseListSelector(ctx).list(
        view=request.GET.get("view", "initiated"),
        user_id=request.user.id,
        page=page,
        page_size=page_size,
    )
    payload = api_root(request)
    payload["schemaVersion"] = SCHEMA_LIST
    payload["data"] = data
    payload["stats"] = CaseListSelector(ctx).stats(request.user.id)
    return json_response(request, payload)


def _change_create(request):
    ctx, err = _context(request)
    if err:
        return err
    if not (request.user.is_superuser or request.user.has_perm("hr.change.create")):
        return error_response(request, "PERMISSION_DENIED", "无发起异动权限", status=403)
    try:
        body = _json_body(request)
    except ChangeServiceError as exc:
        return _service_error(request, exc)
    try:
        case = _svc(request, ctx).create_case(
            staff_master_id=body["staffMasterId"],
            action_id=body["actionId"],
            reason_id=body["reasonId"],
            requested_effective_at=body["requestedEffectiveAt"],
            proposals=body.get("proposals", []),
            source_org_id=body.get("sourceOrgId"),
            target_org_id=body.get("targetOrgId"),
            source_position_id=body.get("sourcePositionId"),
            target_position_id=body.get("targetPositionId"),
            priority=body.get("priority", "NORMAL"),
            version=_version(request),
        )
    except (ChangeServiceError, ChangeStateError) as exc:
        return _service_error(request, exc)
    except KeyError as exc:
        return error_response(
            request, "CHANGE_INVALID_PAYLOAD", f"缺少必填参数: {exc.args[0]}", status=400
        )
    data = CaseDetailSelector(ctx.tenant_id).get(case.id)
    payload = api_root(request)
    payload["schemaVersion"] = SCHEMA_CREATE
    payload["data"] = data
    return json_response(request, payload, status=201)


@require_GET
@require_hr_change_permission("hr.change.view")
def change_detail(request, case_id):
    ctx, err = _context(request)
    if err:
        return err
    data = CaseDetailSelector(ctx.tenant_id).get(case_id)
    if data is None:
        return error_response(request, "CHANGE_NOT_FOUND", "异动案件不存在", status=404)
    payload = api_root(request)
    payload["schemaVersion"] = SCHEMA_DETAIL
    payload["data"] = data
    return json_response(request, payload)


@require_POST
def change_action(request, case_id, action: str):
    """统一动作入口：submit/withdraw/cancel/return/resubmit/approve/reject/start-approval。"""
    ctx, err = _context(request)
    if err:
        return err
    if request.method != "POST":
        return error_response(request, "METHOD_NOT_ALLOWED", "仅支持 POST", status=405)
    permission = _ACTION_PERMISSIONS.get(action)
    if permission is None:
        return error_response(request, "CHANGE_INVALID_ACTION", f"未知动作 {action}", status=404)
    if not request.user.is_authenticated or not (
        request.user.is_superuser or request.user.has_perm(permission)
    ):
        return error_response(request, "PERMISSION_DENIED", "无权执行该异动动作", status=403)
    try:
        body = _json_body(request)
    except ChangeServiceError as exc:
        return _service_error(request, exc)
    svc = _svc(request, ctx)
    try:
        if action == "submit":
            case = svc.submit(case_id, version=_version(request), request_id=body.get("requestId", ""))
        elif action == "start-approval":
            case = svc.start_approval(case_id, version=_version(request))
        elif action == "withdraw":
            case = svc.withdraw(case_id, version=_version(request), comment=body.get("comment", ""))
        elif action == "cancel":
            case = svc.cancel(case_id, version=_version(request), comment=body.get("comment", ""))
        elif action == "return":
            case = svc.return_case(case_id, version=_version(request), comment=body.get("comment", ""))
        elif action == "resubmit":
            case = svc.resubmit(case_id, version=_version(request), comment=body.get("comment", ""))
        elif action == "approve":
            case = svc.approve(case_id, version=_version(request), comment=body.get("comment", ""))
        elif action == "reject":
            case = svc.reject(case_id, version=_version(request), comment=body.get("comment", ""))
        elif action == "apply":
            forbidden = _FORBIDDEN_EFFECT_FIELDS.intersection(body)
            unknown = set(body).difference({"requestId"})
            if forbidden or unknown:
                return error_response(
                    request,
                    "CHANGE_INVALID_PAYLOAD",
                    "生效接口只接受 requestId；状态、日期和 Authority 回执由服务端生成",
                    status=400,
                )
            case = ApplyService(
                ctx.tenant_id,
                actor_user_id=request.user.id,
            ).apply_case(
                case_id,
                as_of=ctx.as_of,
                expected_version=_version(request),
                request_id=(
                    request.headers.get("Idempotency-Key")
                    or body.get("requestId", "")
                ),
            )
    except (ChangeServiceError, ChangeStateError, ApplyServiceError) as exc:
        return _service_error(request, exc)
    data = CaseDetailSelector(ctx.tenant_id).get(case.id)
    payload = api_root(request)
    payload["schemaVersion"] = SCHEMA_DETAIL
    payload["data"] = data
    return json_response(request, payload)


@require_POST
@require_hr_change_permission("hr.change.submit")
def change_validate(request, case_id):
    ctx, err = _context(request)
    if err:
        return err
    from hr_changes.models import HrPersonnelChangeCase

    case = HrPersonnelChangeCase.objects.filter(tenant_id=ctx.tenant_id, id=case_id).first()
    if case is None:
        return error_response(request, "CHANGE_NOT_FOUND", "异动案件不存在", status=404)
    result = ValidationService(ctx.tenant_id).validate(case)
    payload = api_root(request)
    payload["schemaVersion"] = "hr06.changes.validate.1"
    payload["data"] = {
        "items": _label_levels(result["items"]),
        "blockers": _label_levels(result["blockers"]),
        "warnings": _label_levels(result["warnings"]),
        "infos": _label_levels(result["infos"]),
    }
    return json_response(request, payload)


@require_POST
@require_hr_change_permission("hr.change.submit")
def change_preview(request, case_id):
    ctx, err = _context(request)
    if err:
        return err
    from hr_changes.models import HrPersonnelChangeCase

    case = HrPersonnelChangeCase.objects.filter(tenant_id=ctx.tenant_id, id=case_id).first()
    if case is None:
        return error_response(request, "CHANGE_NOT_FOUND", "异动案件不存在", status=404)
    result = ImpactService(ctx.tenant_id).compute(case)
    payload = api_root(request)
    payload["schemaVersion"] = "hr06.changes.preview.1"
    payload["data"] = {
        "blockers": _label_levels(result["blockers"]),
        "warnings": _label_levels(result["warnings"]),
        "infos": _label_levels(result["infos"]),
    }
    return json_response(request, payload)


def _label_levels(items: list[dict]) -> list[dict]:
    from hr_changes.api.labels import impact_level_label

    return [
        {**item, "levelLabel": impact_level_label(item.get("level"))}
        for item in items
    ]


@require_GET
@require_hr_change_permission("hr.change.view")
def future_changes(request):
    ctx, err = _context(request)
    if err:
        return err
    from hr_changes.models import HrPersonnelChangeCase

    cases = (
        HrPersonnelChangeCase.objects.filter(
            tenant_id=ctx.tenant_id,
            status="APPROVED_WAITING_EFFECTIVE",
        )
        .select_related("action_id", "staff_master_id", "target_org_id")
        .order_by("requested_effective_at")
    )
    items = [
        {
            "id": str(c.id),
            "caseNo": c.case_no,
            "staffName": c.staff_master_id.person_id.legal_name,
            "actionCode": c.action_id.code,
            "actionLabel": _action_display(c),
            "requestedEffectiveAt": c.requested_effective_at.isoformat(),
            "target": c.target_org_id.stable_code if c.target_org_id else "",
        }
        for c in cases
    ]
    payload = api_root(request)
    payload["schemaVersion"] = "hr06.changes.future.1"
    payload["data"] = {"items": items, "total": len(items)}
    return json_response(request, payload)


def _action_display(case):
    from hr_changes.api.labels import action_label

    return action_label(case.action_id.code)
