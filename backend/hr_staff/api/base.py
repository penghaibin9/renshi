"""
hr_staff/api/base.py —— HR03 API 统一 version envelope + 错误处理（S1）。

对齐总册 §26/§27 与 hr_control_center.api.views：
- 所有 response root 必须包含 apiVersion/schemaVersion/requestId/generatedAt。
- error envelope 统一；内部 traceback 不直接返回浏览器。
- 越权不能靠 200 + empty list；fail-closed。
"""

from __future__ import annotations

import logging
import uuid

from django.conf import settings
from django.http import JsonResponse

from hr_staff.context import (
    HrStaffContextError,
    build_staff_context,
    resolve_tenant_from_request,
)

logger = logging.getLogger(__name__)

API_VERSION = "1.0"
SCHEMA_VERSION = "hr03.base.1"


def _request_id(request) -> str:
    rid = getattr(request, "hr03_request_id", None)
    if not rid:
        rid = uuid.uuid4().hex
        request.hr03_request_id = rid
    return rid


def api_root(request) -> dict:
    return {
        "apiVersion": API_VERSION,
        "schemaVersion": SCHEMA_VERSION,
        "requestId": _request_id(request),
        "generatedAt": None,  # 由 _json 填充
        "schoolTimezone": getattr(request, "hr03_school_timezone", settings.TIME_ZONE),
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


def make_staff_context(request, *, authority_mode=None):
    """
    从请求构造 HrStaffRequestContext（服务端重新验证 tenant/scope，不信任前端参数）。
    tenant 缺失 → HrStaffContextError(TENANT_CONTEXT_REQUIRED)。
    N9：authority_mode 以服务端 AuthorityModeService 解析为准（不信任客户端参数；
    显式参数仅用于测试注入）。
    """
    tenant_id = resolve_tenant_from_request(request)
    if tenant_id is None:
        raise HrStaffContextError(
            "TENANT_CONTEXT_REQUIRED", "请选择当前学校（多学校账号需明确学校上下文）"
        )

    # Tenant membership must be affirmative. An empty allowed-company set means
    # this user belongs to no school; it must never be interpreted as
    # "unrestricted".
    if not request.user.is_superuser:
        from base.auth_backends import get_allowed_company_ids

        allowed = get_allowed_company_ids(request.user)
        if tenant_id not in allowed:
            raise HrStaffContextError(
                "TENANT_CONTEXT_REQUIRED", "当前账号无权访问该学校数据"
            )

    if authority_mode is None:
        from hr_staff.services.authority_mode_service import AuthorityModeService

        authority_mode = AuthorityModeService().get_mode(tenant_id)

    scope_type = request.GET.get("scope_type", "SCHOOL")
    scope_org_id = request.GET.get("scope_id")
    if scope_org_id in (None, "", "null"):
        scope_org_id = None
    else:
        try:
            scope_org_id = int(scope_org_id)
        except (TypeError, ValueError):
            raise HrStaffContextError("SCOPE_NOT_ALLOWED", "scope_id 必须是整数")

    scope_staff_ids = request.GET.getlist("staff_ids")

    # The business date may be selected by the caller for as-of reads, but the
    # timezone is deployment/tenant configuration, not a client-controlled
    # query parameter. Until per-school timezone is modeled, use the server's
    # configured school timezone consistently.
    school_timezone = settings.TIME_ZONE
    request.hr03_school_timezone = school_timezone

    return build_staff_context(
        tenant_id=tenant_id,
        school_timezone=school_timezone,
        user_id=request.user.id,
        as_of=request.GET.get("as_of"),
        scope_type=scope_type,
        scope_org_id=scope_org_id,
        scope_staff_ids=scope_staff_ids,
        authority_mode=authority_mode,
    )
