"""
hr_onboarding/api/base.py

HR05 统一 response envelope（总册 §33）：
{
  "apiVersion": "v1",
  "schemaVersion": "hr05.1",
  "requestId": "uuid",
  "data": {}
}
错误信封（00 §29）：
{
  "apiVersion": "v1",
  "requestId": "...",
  "error": {"code": "...", "message": "...", "details": {}, "retryable": false}
}

硬合同：
- 无 tenant context fail-closed 403；
- 写 API 接受 Idempotency-Key 与 If-Match/version；
- 内部 traceback 不直接返回浏览器；
- 高敏 payload 禁止进日志。
"""

from __future__ import annotations

import logging
import uuid

from django.http import JsonResponse
from django.utils import timezone

from hr_onboarding.api.exceptions import Hr05ApiError, TenantContextRequiredError
from hr_onboarding.context import build_hr05_context, resolve_tenant_from_request

logger = logging.getLogger(__name__)

API_VERSION = "v1"
SCHEMA_VERSION = "hr05.1"


def _request_id(request) -> str:
    rid = getattr(request, "hr05_request_id", None)
    if not rid:
        rid = uuid.uuid4().hex
        request.hr05_request_id = rid
    return rid


def api_root(request) -> dict:
    return {
        "apiVersion": API_VERSION,
        "schemaVersion": SCHEMA_VERSION,
        "requestId": _request_id(request),
        "generatedAt": None,
    }


def json_response(request, payload: dict, status: int = 200) -> JsonResponse:
    payload["generatedAt"] = timezone.now().isoformat()
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = "no-store"
    return response


def ok(request, data, status: int = 200) -> JsonResponse:
    body = api_root(request)
    body["data"] = data
    return json_response(request, body, status=status)


def error(request, code: str, message: str, status: int, details=None, retryable=False) -> JsonResponse:
    body = api_root(request)
    body["error"] = {
        "code": code,
        "message": message,
        "details": details or {},
        "retryable": retryable,
    }
    return json_response(request, body, status=status)


def make_hr05_context(request):
    """
    从请求构造 Hr05RequestContext（服务端重新验证 tenant/scope，不信任前端）。
    tenant_id 由 session/contextvar 解析，禁止读取客户端查询参数。
    """
    from hr_control_center.context import HrContextError

    tenant_id = resolve_tenant_from_request(request)
    if tenant_id is None:
        raise TenantContextRequiredError()

    scope_type = request.GET.get("scope_type", "SCHOOL")
    scope_org_id = request.GET.get("scope_id")
    if scope_org_id in (None, "", "null"):
        scope_org_id = None
    else:
        try:
            scope_org_id = int(scope_org_id)
        except (TypeError, ValueError):
            raise Hr05ApiError("scope_id 必须是整数", details={"code": "SCOPE_NOT_ALLOWED"})

    try:
        return build_hr05_context(
            tenant_id=tenant_id,
            school_timezone=request.GET.get("school_timezone") or "Asia/Shanghai",
            user_id=request.user.id if request.user.is_authenticated else None,
            as_of=request.GET.get("as_of"),
            period_from=request.GET.get("period_from"),
            period_to=request.GET.get("period_to"),
            scope_type=scope_type,
            scope_org_id=scope_org_id,
            authority_mode=request.GET.get("authority_mode", "LEGACY_ONBOARDING_ONLY"),
        )
    except HrContextError as exc:
        # HR01 上下文错误 → HR05 信封（非法 scope/日期不再 500）
        raise Hr05ApiError(str(exc), details={"code": getattr(exc, "code", "CONTEXT_ERROR")})


def get_idempotency_key(request) -> str | None:
    """读 Idempotency-Key（HEADER 优先，其次 body/query）。"""
    value = request.headers.get("Idempotency-Key")
    if value:
        return value
    if request.method == "POST":
        value = getattr(request, "POST", {}).get("idempotency_key")
    if value:
        return value
    return request.GET.get("idempotency_key")


def get_if_match(request) -> str | None:
    """读 If-Match（乐观锁/版本冲突）。"""
    return request.headers.get("If-Match")


def handle_hr05_error(request, exc: Exception) -> JsonResponse:
    """
    统一异常 → 错误信封。Hr05ApiError 输出业务错误码；
    其他异常记录日志后输出 500 通用信封（不泄露内部细节）。
    """
    if isinstance(exc, Hr05ApiError):
        return error(
            request,
            exc.code,
            exc.message,
            exc.status_code,
            exc.details,
            getattr(exc, "retryable", False),
        )

    if isinstance(exc, Exception):
        logger.exception(
            "hr05 unhandled error requestId=%s tenant=%s",
            _request_id(request),
            getattr(request, "hr05_tenant", None),
        )
        return error(request, "INTERNAL_ERROR", "服务器内部错误", 500)

    return error(request, "UNKNOWN_ERROR", "未知错误", 500)
