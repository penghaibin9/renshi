"""
hr_changes/api/base.py —— HR06 API 统一 version envelope + 错误处理（S1）。

对齐 00 §28.1（/api/v1/hr）与 hr_staff.api.base：
- 所有 response root 必须包含 apiVersion/schemaVersion/requestId/generatedAt。
- error envelope 统一；内部 traceback 不直接返回浏览器。
- 越权不能靠 200 + empty list；fail-closed。
"""

from __future__ import annotations

import logging
import uuid

from django.conf import settings
from django.http import JsonResponse

from hr_changes.context import (
    HrChangeContextError,
    build_hr_change_context,
    resolve_tenant_from_request,
)

logger = logging.getLogger(__name__)

API_VERSION = "1.0"
SCHEMA_VERSION = "hr06.base.1"


def _request_id(request) -> str:
    rid = getattr(request, "hr06_request_id", None)
    if not rid:
        rid = uuid.uuid4().hex
        request.hr06_request_id = rid
    return rid


def api_root(request) -> dict:
    return {
        "apiVersion": API_VERSION,
        "schemaVersion": SCHEMA_VERSION,
        "requestId": _request_id(request),
        "generatedAt": None,  # 由 json_response 填充
        "schoolTimezone": getattr(request, "hr06_school_timezone", "Asia/Shanghai"),
    }


def json_response(request, payload: dict, status: int = 200) -> JsonResponse:
    from django.utils import timezone

    payload["generatedAt"] = timezone.now().isoformat()
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = "no-store"
    return response


def error_response(request, code: str, message: str, status: int, details=None) -> JsonResponse:
    body = api_root(request)
    body["error"] = {
        "code": code,
        "message": message,
        "details": details,
        "retryable": False,
    }
    return json_response(request, body, status=status)


def make_hr_change_context(request, *, tenant_membership_check=True):
    """
    从请求构造 HrChangeRequestContext（服务端重新验证 tenant/scope，不信任前端参数）。
    tenant 缺失 → HrChangeContextError(TENANT_CONTEXT_REQUIRED)。
    """
    tenant_id = resolve_tenant_from_request(request)
    if tenant_id is None:
        raise HrChangeContextError(
            "TENANT_CONTEXT_REQUIRED", "请选择当前学校（多学校账号需明确学校上下文）"
        )

    if not getattr(request.user, "is_authenticated", False):
        raise HrChangeContextError("UNAUTHENTICATED", "请先登录")

    if tenant_membership_check and not request.user.is_superuser:
        from base.auth_backends import get_allowed_company_ids

        allowed = get_allowed_company_ids(request.user)
        # An empty membership set means the account belongs to no tenant.  It
        # must never be interpreted as an unrestricted account.
        if tenant_id not in allowed:
            raise HrChangeContextError(
                "TENANT_CONTEXT_REQUIRED", "当前账号无权访问该学校数据"
            )

    school_timezone = settings.TIME_ZONE
    request.hr06_school_timezone = school_timezone

    scope_type = request.GET.get("scope_type", "SCHOOL")
    scope_org_id = request.GET.get("scope_id")
    if scope_org_id in (None, "", "null"):
        scope_org_id = None
    else:
        try:
            scope_org_id = int(scope_org_id)
        except (TypeError, ValueError):
            raise HrChangeContextError("SCOPE_DENIED", "scope_id 必须是整数")

    return build_hr_change_context(
        tenant_id=tenant_id,
        school_timezone=school_timezone,
        user_id=request.user.id,
        as_of=request.GET.get("as_of"),
        scope_type=scope_type,
        scope_org_id=scope_org_id,
    )
