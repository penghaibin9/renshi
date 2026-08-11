from django.http import JsonResponse
from django.utils import timezone
from base.auth_backends import get_allowed_company_ids
from hr_control_center.context import resolve_tenant_from_request
from .selectors import dashboard_snapshot
from .services.identity_service import SelfIdentityError, SelfIdentityService


class HrSelfAccessError(Exception):
    pass


def resolve_self_context(request):
    if not getattr(request.user, "is_authenticated", False):
        raise HrSelfAccessError("authentication required")
    tenant_id = resolve_tenant_from_request(request)
    if not tenant_id:
        raise HrSelfAccessError("请选择当前学校")
    tenant_id = int(tenant_id)
    if not request.user.is_superuser:
        allowed = get_allowed_company_ids(request.user)
        if allowed and tenant_id not in {int(x) for x in allowed}:
            raise HrSelfAccessError("当前账号无权访问该学校")
    try:
        return SelfIdentityService(tenant_id).resolve(request.user)
    except SelfIdentityError as exc:
        raise HrSelfAccessError(str(exc)) from exc


def dashboard(request):
    if request.method != "GET": return JsonResponse({"error":{"code":"METHOD_NOT_ALLOWED"}}, status=405)
    try: context=resolve_self_context(request)
    except HrSelfAccessError as exc: return JsonResponse({"error":{"code":"SELF_ACCESS_DENIED","message":str(exc)}},status=403)
    data=dashboard_snapshot(context)
    data.update({"apiVersion":"1.0","schemaVersion":"hr17.workspace.1","generatedAt":timezone.now().isoformat()})
    response=JsonResponse(data); response["Cache-Control"]="no-store"; return response
