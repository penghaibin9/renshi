"""
hr_recruitment/api/base.py

HR04 统一 response envelope（总册 8.5/17.1/17.3）：
{
  "apiVersion": "v1",
  "schemaVersion": "hr04.1",
  "requestId": "uuid",
  "data": {}
}
错误信封：
{
  "apiVersion": "v1",
  "requestId": "...",
  "error": {"code": "...", "message": "...", "details": {}}
}

硬合同：
- 无 tenant context fail-closed 403；
- 写 API 接受 Idempotency-Key 与 If-Match/version；
- 内部 traceback 不直接返回浏览器。
"""

from __future__ import annotations

import logging
import uuid

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone

from hr_recruitment.api.exceptions import (
    Hr04ApiError,
    PermissionDeniedError,
    TenantContextRequiredError,
)
from hr_recruitment.context import build_hr04_context, resolve_tenant_from_request

logger = logging.getLogger(__name__)

API_VERSION = "v1"
SCHEMA_VERSION = "hr04.1"


def _request_id(request) -> str:
    rid = getattr(request, "hr04_request_id", None)
    if not rid:
        rid = uuid.uuid4().hex
        request.hr04_request_id = rid
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


def error(request, code: str, message: str, status: int, details=None) -> JsonResponse:
    body = api_root(request)
    body["error"] = {
        "code": code,
        "message": message,
        "details": details or {},
    }
    return json_response(request, body, status=status)


def make_hr04_context(request):
    """
    从请求构造 Hr04RequestContext（服务端重新验证 tenant/scope，不信任前端）。
    tenant_id 由 session/contextvar 解析，禁止读取客户端查询参数。
    """
    from hr_recruitment.api.exceptions import Hr04ApiError

    tenant_id = resolve_tenant_from_request(request)
    if tenant_id is None:
        raise TenantContextRequiredError()

    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        raise PermissionDeniedError("请先登录")

    # Selected-company is session state, not an authorization decision.  An
    # empty membership set means no school access and must fail closed.
    if not user.is_superuser:
        from base.auth_backends import get_allowed_company_ids

        allowed = get_allowed_company_ids(user)
        if tenant_id not in allowed:
            raise TenantContextRequiredError("当前账号无权访问该学校数据")

    scope_type = request.GET.get("scope_type", "SCHOOL")
    scope_org_id = request.GET.get("scope_id")
    if scope_org_id in (None, "", "null"):
        scope_org_id = None
    else:
        try:
            scope_org_id = int(scope_org_id)
        except (TypeError, ValueError):
            raise Hr04ApiError(
                "SCOPE_NOT_ALLOWED", "scope_id 必须是整数", status_code=403
            ) from None

    try:
        return build_hr04_context(
            tenant_id=tenant_id,
            school_timezone=settings.TIME_ZONE,
            user_id=request.user.id if request.user.is_authenticated else None,
            as_of=request.GET.get("as_of"),
            period_from=request.GET.get("period_from"),
            period_to=request.GET.get("period_to"),
            scope_type=scope_type,
            scope_org_id=scope_org_id,
            authority_mode="HR04_AUTHORITY",
        )
    except Exception as exc:  # HrContextError（非法日期/scope）→ Hr04ApiError 统一错误码
        code = getattr(exc, "code", "INVALID_REQUEST")
        message = getattr(exc, "message", "请求参数无效")
        status = 403 if code == "SCOPE_NOT_ALLOWED" else 400
        raise Hr04ApiError(code, message, status_code=status) from exc


def get_idempotency_key(request) -> str | None:
    """Read an idempotency key from non-loggable mutation inputs only."""
    value = request.headers.get("Idempotency-Key")
    if value:
        return value
    if request.method == "POST":
        value = getattr(request, "POST", {}).get("idempotency_key")
        if value:
            return value
    return None


def get_if_match(request) -> str | None:
    """读 If-Match（乐观锁/版本冲突）。"""
    return request.headers.get("If-Match")


def handle_hr04_error(request, exc: Exception) -> JsonResponse:
    """
    统一异常 → 错误信封。Hr04ApiError 输出业务错误码；
    其他异常记录日志后输出 500 通用信封（不泄露内部细节）。
    """
    if isinstance(exc, Hr04ApiError):
        return error(request, exc.code, exc.message, exc.status_code, exc.details)

    if isinstance(exc, Exception):
        logger.exception(
            "hr04 unhandled error requestId=%s tenant=%s",
            _request_id(request),
            getattr(request, "hr04_tenant", None),
        )
        return error(request, "INTERNAL_ERROR", "服务器内部错误", 500)

    return error(request, "UNKNOWN_ERROR", "未知错误", 500)
