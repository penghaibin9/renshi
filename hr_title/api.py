"""Canonical read API for HR13 workspace pages."""

from __future__ import annotations

from django.http import JsonResponse
from django.utils import timezone

from base.auth_backends import get_allowed_company_ids
from hr_control_center.context import resolve_tenant_from_request

from .selectors import dashboard_snapshot

READ_PERMISSION = "hr.title.view"


class HrTitleAccessError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def resolve_request_tenant(request) -> int:
    if not getattr(request.user, "is_authenticated", False):
        raise HrTitleAccessError("AUTHENTICATION_REQUIRED", "authentication required")
    tenant_id = resolve_tenant_from_request(request)
    if not tenant_id:
        raise HrTitleAccessError("TENANT_CONTEXT_REQUIRED", "请选择当前学校")
    tenant_id = int(tenant_id)
    if not request.user.is_superuser:
        allowed = {int(x) for x in get_allowed_company_ids(request.user)}
        if tenant_id not in allowed:
            raise HrTitleAccessError("TENANT_ACCESS_DENIED", "当前账号无权访问该学校")
        if not request.user.has_perm(READ_PERMISSION):
            raise HrTitleAccessError("PERMISSION_DENIED", f"缺少权限: {READ_PERMISSION}")
    return tenant_id


def dashboard(request):
    if request.method != "GET":
        return JsonResponse({"error": {"code": "METHOD_NOT_ALLOWED"}}, status=405)
    try:
        tenant_id = resolve_request_tenant(request)
    except HrTitleAccessError as exc:
        return JsonResponse({"error": {"code": exc.code, "message": exc.message}}, status=403)
    payload = dashboard_snapshot(tenant_id)
    payload.update({"apiVersion": "1.0", "schemaVersion": "hr13.workspace.1", "generatedAt": timezone.now().isoformat()})
    response = JsonResponse(payload)
    response["Cache-Control"] = "no-store"
    return response
