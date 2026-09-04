"""
hr_external/api/base.py —— HR08 API 统一 version envelope + 错误处理（S1）。

对齐总册 §81/§82 与 hr_staff.api.base：
- 所有 response root 必须包含 apiVersion/schemaVersion/requestId/generatedAt；
- error envelope 统一；内部 traceback 不直接返回浏览器；
- 越权不能靠 200 + empty list；fail-closed。
"""

from __future__ import annotations

import logging
import uuid

from django.conf import settings
from django.http import JsonResponse

from hr_external.context import (
    HrExternalContextError,
    build_external_context,
    resolve_tenant_from_request,
)

logger = logging.getLogger(__name__)

API_VERSION = "1.0"
SCHEMA_VERSION = "hr08.base.1"


def _request_id(request) -> str:
    rid = getattr(request, "hr08_request_id", None)
    if not rid:
        rid = uuid.uuid4().hex
        request.hr08_request_id = rid
    return rid


def api_root(request) -> dict:
    return {
        "apiVersion": API_VERSION,
        "schemaVersion": SCHEMA_VERSION,
        "requestId": _request_id(request),
        "generatedAt": None,  # 由 _json 填充
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
        "details": details or {},
        "retryable": False,
    }
    return json_response(request, body, status=status)


def make_external_context(request, *, authority_mode=None):
    """
    从请求构造 HrExternalRequestContext（服务端重新验证 tenant/scope，不信任前端参数）。
    tenant 缺失 → HrExternalContextError(TENANT_CONTEXT_REQUIRED)。
    scope 越权 → HrExternalContextError(EXTERNAL_SCOPE_DENIED)（A13 授权校验）。
    """
    from hr_external.context import authorize_external_scope

    tenant_id = resolve_tenant_from_request(request)
    if tenant_id is None:
        raise HrExternalContextError(
            "TENANT_CONTEXT_REQUIRED", "请选择当前学校（多学校账号需明确学校上下文）"
        )

    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        raise HrExternalContextError("UNAUTHENTICATED", "请先登录")
    if not getattr(user, "is_superuser", False):
        from base.auth_backends import get_allowed_company_ids

        if tenant_id not in (get_allowed_company_ids(user) or ()):
            raise HrExternalContextError(
                "TENANT_CONTEXT_REQUIRED", "当前账号无权访问该学校数据"
            )

    scope_type = request.GET.get("scope_type", "SCHOOL")
    scope_org_id = request.GET.get("scope_id")
    if scope_org_id in (None, "", "null"):
        scope_org_id = None
    else:
        try:
            scope_org_id = int(scope_org_id)
        except (TypeError, ValueError):
            raise HrExternalContextError(
                "EXTERNAL_SCOPE_DENIED", "scope_id 必须是整数"
            )

    # 生产级：scope 授权（A13）——非 superuser 的 COLLEGE/ORGANIZATION 必须验证 membership
    authorize_external_scope(
        request, tenant_id=tenant_id, scope_type=scope_type, scope_org_id=scope_org_id
    )

    scope_engagement_ids = request.GET.getlist("engagement_ids")

    if authority_mode is None:
        from hr_external.services.authority_service import AuthorityService

        authority_mode = AuthorityService.get_mode(tenant_id)

    return build_external_context(
        tenant_id=tenant_id,
        school_timezone=settings.TIME_ZONE,
        user_id=user.id,
        as_of=request.GET.get("as_of"),
        scope_type=scope_type,
        scope_org_id=scope_org_id,
        scope_engagement_ids=scope_engagement_ids,
        authority_mode=authority_mode,
    )
