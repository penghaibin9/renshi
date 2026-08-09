"""
hr_onboarding/api/portal.py

Portal API（总册 §34）：
- Portal 不接受任意 case id，只用 token 解析（header `X-Prehire-Token` 或 `Authorization: Bearer`）；
- token 有时效、不入日志、公共 URL 不可枚举；
- 数据只写 HrPrehireProfile staging，不写 HR03 权威表。
"""

from __future__ import annotations

from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from hr_onboarding.api import base as api_base
from hr_onboarding.api.exceptions import Hr05ApiError, NotFoundError
from hr_onboarding.services import portal_service


def _resolve_portal(request):
    token = request.headers.get("X-Prehire-Token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
    if not token:
        raise NotFoundError("missing portal token")
    # 公开 Portal：仅凭全局唯一 token_hash 解析（00 §134），不依赖请求 tenant 上下文
    portal = portal_service.get_portal_by_token(tenant_id=None, token=token)
    if portal is None:
        # 统一 404 语义，不泄露 token 是否存在
        raise NotFoundError("portal access not found")
    return portal


@require_GET
def prehire_me(request):
    """Portal 首页：欢迎/预计报到日/状态/进度。"""
    try:
        portal = _resolve_portal(request)
        return api_base.ok(request, portal_service.get_me(portal))
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)


@require_POST
@csrf_exempt
def prehire_update_profile(request):
    try:
        portal = _resolve_portal(request)
        import json

        try:
            data = json.loads(request.body or b"{}")
        except (ValueError, TypeError):
            data = dict(request.POST)
        result = portal_service.update_profile(portal, data)
        return api_base.ok(request, result)
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)


@require_POST
@csrf_exempt
def prehire_confirm_intent(request):
    try:
        portal = _resolve_portal(request)
        result = portal_service.confirm_intent(portal)
        return api_base.ok(request, result)
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)
