"""
hr_time/api/views.py

HR11 API views —— 统一 version envelope + 错误信封（总册 §130）。

硬合同：
- response root 必须包含 apiVersion/schemaVersion/requestId/generatedAt；
- error envelope 统一；内部 traceback 不直接返回浏览器；
- tenant fail-closed：无学校上下文 → 403 TENANT_CONTEXT_REQUIRED；
- 越权不能靠 200 + empty list。
"""

from __future__ import annotations

import logging
import uuid

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from hr_time.constants import API_VERSION, SCHEMA_VERSION, TimeErrorCode
from hr_time.context import HrTimeContextError, resolve_tenant_from_request

logger = logging.getLogger(__name__)


def _request_id(request) -> str:
    rid = getattr(request, "hr_time_request_id", None)
    if not rid:
        rid = uuid.uuid4().hex
        request.hr_time_request_id = rid
    return rid


def _api_root(request) -> dict:
    return {
        "apiVersion": API_VERSION,
        "schemaVersion": SCHEMA_VERSION,
        "requestId": _request_id(request),
        "generatedAt": None,  # 由 _json 填充
    }


def _json(request, payload: dict, status: int = 200) -> JsonResponse:
    from django.utils import timezone

    payload["generatedAt"] = timezone.now().isoformat()
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = "no-store"
    return response


def _error(request, code: str, message: str, status: int, details=None) -> JsonResponse:
    body = _api_root(request)
    body["error"] = {
        "code": code,
        "message": message,
        "details": details,
    }
    return _json(request, body, status=status)


def _make_context(request):
    """从请求构造 HrTimeContext（服务端重新验证 tenant/scope，不信任前端参数）。"""
    from hr_time.context import build_hr_time_context

    tenant_id = resolve_tenant_from_request(request)
    if tenant_id is None:
        raise HrTimeContextError(
            "TENANT_CONTEXT_REQUIRED", "请选择当前学校（多学校账号需明确学校上下文）"
        )

    user_id = request.user.id if getattr(request.user, "is_authenticated", False) else None

    scope_id = request.GET.get("scope_id")
    if scope_id in (None, "", "null"):
        scope_id = None
    else:
        try:
            scope_id = int(scope_id)
        except (TypeError, ValueError):
            raise HrTimeContextError(
                "INVALID_REQUEST", "scope_id 必须是整数"
            )

    return build_hr_time_context(
        tenant_id=tenant_id,
        school_timezone=request.GET.get("school_timezone") or "Asia/Shanghai",
        user_id=user_id,
        as_of=request.GET.get("as_of"),
        period_from=request.GET.get("period_from"),
        period_to=request.GET.get("period_to"),
        scope_type=request.GET.get("scope_type", "TENANT_ALL"),
        scope_org_id=scope_id,
        authority_mode=request.GET.get("authority_mode", "LEGACY_ONLY"),
    )


def _require_permission(request, perm_code: str):
    """权限校验（S1 起所有 HR11 业务 API 必须显式调用；禁止默认放行）。"""
    if not request.user.is_authenticated:
        raise HrTimeContextError(
            TimeErrorCode.UNAUTHENTICATED, "未登录", status=401
        )
    if not (request.user.is_superuser or request.user.has_perm(perm_code)):
        raise HrTimeContextError(
            TimeErrorCode.PERMISSION_DENIED, "无 HR11 权限", status=403
        )


@require_GET
def time_health(request):
    """
    GET /api/hr/v1/time/health —— S1 存活/合同探针。

    tenant fail-closed：必须携带明确学校上下文，否则 403 TENANT_CONTEXT_REQUIRED。
    此端点证明 envelope 与租户闸门已生效。
    """
    try:
        ctx = _make_context(request)
        _require_permission(request, "hr.time.admin")
    except HrTimeContextError as exc:
        return _error(request, exc.code, exc.message, status=getattr(exc, "status", 403))

    data = {
        "module": "HR11",
        "authority": "REWRITE_AS_AUTHORITY",
        "tenant": {
            "tenantId": ctx.tenant_id,
            "timezone": ctx.school_timezone,
            "schoolToday": ctx.today().isoformat(),
        },
        # JSON 字段规范：机器字段 camelCase（status），人看的中文 label 成对（statusLabel）
        "stages": {
            "S1": {"status": "DONE", "statusLabel": "已完成"},
            "S2": {"status": "DONE", "statusLabel": "已完成"},
            "S3": {"status": "DONE", "statusLabel": "已完成"},
            "S4": {"status": "DONE", "statusLabel": "已完成"},
            "S5": {"status": "DONE", "statusLabel": "已完成"},
            "S6": {"status": "DONE", "statusLabel": "已完成"},
            "S7": {"status": "DONE", "statusLabel": "已完成"},
            "S8": {"status": "DONE", "statusLabel": "已完成"},
            "S9": {"status": "DONE", "statusLabel": "已完成"},
        },
    }
    body = _api_root(request)
    body["data"] = data
    return _json(request, body)
