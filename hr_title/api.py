"""Canonical read API for HR13 workspace pages."""

from __future__ import annotations

from django.http import JsonResponse
from django.utils import timezone

from base.auth_backends import get_allowed_company_ids
from hr_control_center.context import resolve_tenant_from_request

from .selectors import dashboard_snapshot


class HrTitleAccessError(Exception):
    pass


def resolve_request_tenant(request) -> int:
    if not getattr(request.user, "is_authenticated", False):
        raise HrTitleAccessError("authentication required")
    tenant_id = resolve_tenant_from_request(request)
    if not tenant_id:
        raise HrTitleAccessError("请选择当前学校")
    if not request.user.is_superuser:
        allowed = get_allowed_company_ids(request.user)
        if allowed and int(tenant_id) not in {int(x) for x in allowed}:
            raise HrTitleAccessError("当前账号无权访问该学校")
    return int(tenant_id)


def dashboard(request):
    if request.method != "GET":
        return JsonResponse({"error": {"code": "METHOD_NOT_ALLOWED"}}, status=405)
    try:
        tenant_id = resolve_request_tenant(request)
    except HrTitleAccessError as exc:
        return JsonResponse({"error": {"code": "ACCESS_DENIED", "message": str(exc)}}, status=403)
    payload = dashboard_snapshot(tenant_id)
    payload.update({"apiVersion": "1.0", "schemaVersion": "hr13.workspace.1", "generatedAt": timezone.now().isoformat()})
    response = JsonResponse(payload)
    response["Cache-Control"] = "no-store"
    return response
