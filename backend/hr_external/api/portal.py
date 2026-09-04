"""
hr_external/api/portal.py —— 外聘本人门户 API（B6，总册 §90/§55）。

- POST /api/hr/v1/external-teachers/portal/tokens    签发 token（需 hr08.access.manage）
- GET  /api/hr/v1/external-teachers/portal/me?token= 本人视图（公开 token 鉴权；禁止客户端传 tenant_id，00 §134）
- POST /api/hr/v1/external-teachers/portal/me/task-{id}/submit  本人提交任务证据/进展
"""

from __future__ import annotations

from django.views.decorators.http import require_GET, require_POST

from hr_external.api.base import (
    api_root,
    error_response,
    json_response,
    make_external_context,
)
from hr_external.models import HrExternalTeacherProfile
from hr_external.permissions import require_hr_external_permission
from hr_external.services.portal_service import PortalService, PortalTokenInvalid


def _ctx(request):
    try:
        return make_external_context(request), None
    except Exception as exc:  # noqa: BLE001
        code = getattr(exc, "code", "INVALID_REQUEST")
        status = 403 if code == "TENANT_CONTEXT_REQUIRED" else 400
        return None, error_response(request, code, str(exc), status)


@require_POST
@require_hr_external_permission("hr08.access.manage")
def portal_token_issue(request):
    """POST .../portal/tokens body: {profileId} —— 签发本人门户 token（明文只返回一次）。"""
    import json

    ctx, err = _ctx(request)
    if err:
        return err
    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return error_response(request, "INVALID_REQUEST", "请求体必须是 JSON", 400)

    profile_id = payload.get("profileId")
    if not profile_id:
        return error_response(request, "INVALID_REQUEST", "profileId 必填", 400)
    profile = HrExternalTeacherProfile.objects.filter(
        tenant_id=ctx.tenant_id, id=profile_id
    ).first()
    if profile is None:
        return error_response(request, "EXTERNAL_PROFILE_NOT_FOUND", "外聘档案不存在", 404)

    raw, token = PortalService().issue_token(
        tenant_id=ctx.tenant_id,
        external_profile_id=profile.id,
        issued_by=ctx.user_id,
    )
    body = api_root(request)
    body["data"] = {
        "token": raw,
        "expiresAt": token.expires_at.isoformat(),
        "portalUrl": f"/hr/external-teachers/portal/me?token={raw}",
        "note": "token 明文仅返回一次；库中只存 SHA-256（00 §134）",
    }
    return json_response(request, body, status=201)


def _extract_token(request) -> str:
    """优先从 header 取 token（避免 URL 日志泄漏），兼容旧 query 参数。"""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[len("Bearer ") :].strip()
    header = request.headers.get("X-Portal-Token", "")
    if header:
        return header.strip()
    # 兼容：query 参数（会进 access log，标记 deprecated）
    return (request.GET.get("token") or "").strip()


@require_GET
def portal_me(request):
    """GET .../portal/me —— 本人视图（公开入口，token 鉴权）。

    生产级：token 优先从 Authorization: Bearer / X-Portal-Token 头取，
    避免进入 URL/access log（00 §45 日志禁 token）。"""
    raw = _extract_token(request)
    if not raw:
        return error_response(request, "PORTAL_TOKEN_INVALID", "缺少 token", 401)
    try:
        profile = PortalService().resolve_token(raw=raw)
    except PortalTokenInvalid as exc:
        return error_response(request, exc.code, str(exc), 401)

    body = api_root(request)
    body["data"] = PortalService().me(profile=profile)
    return json_response(request, body)
