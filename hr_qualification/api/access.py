"""HR09 API access guard.

Hard rules:
- tenant always comes from the server-selected school, never query/body/header input;
- every endpoint authenticates and checks semantic HR09 permission codes;
- SELF endpoints derive the current person from the authenticated user's HR03 mapping;
- session-authenticated unsafe requests always pass Django CSRF validation, even when
  a legacy view still carries ``csrf_exempt`` on its outer wrapper.
"""

from __future__ import annotations

from functools import wraps

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_protect

from hr_staff.context import resolve_tenant_from_request


class QualificationAccessError(Exception):
    def __init__(self, code: str, message: str, status: int = 403):
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)


def resolve_tenant_or_raise(request) -> int:
    tenant_id = resolve_tenant_from_request(request)
    if not tenant_id:
        raise QualificationAccessError(
            "TENANT_CONTEXT_REQUIRED",
            "请选择当前学校后再执行资格与双师业务。",
            403,
        )
    return int(tenant_id)


def require_any_permission(request, *permission_codes: str) -> None:
    user = request.user
    if not getattr(user, "is_authenticated", False):
        raise QualificationAccessError("UNAUTHENTICATED", "请先登录。", 401)
    if getattr(user, "is_superuser", False):
        return
    if not permission_codes or not any(user.has_perm(code) for code in permission_codes):
        raise QualificationAccessError("PERMISSION_DENIED", "没有执行此资格业务的权限。", 403)


def api_guard(*permission_codes: str):
    """Resolve tenant + permission and enforce CSRF for every unsafe request.

    Several early HR09 function views were decorated ``csrf_exempt`` so JSON POSTs
    would work during construction.  Those endpoints authenticate with the Django
    session, therefore leaving the exemption at middleware level would permit
    cross-site state changes.  The guard wraps the *original* view in
    ``csrf_protect`` internally; an outer legacy ``csrf_exempt`` may skip the
    global middleware, but it cannot skip this source-owned enforcement point.
    """

    def decorator(view_func):
        csrf_checked_view = csrf_protect(view_func)

        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            try:
                tenant_id = resolve_tenant_or_raise(request)
                require_any_permission(request, *permission_codes)
            except QualificationAccessError as exc:
                from hr_qualification.api.serializers import error_envelope

                return JsonResponse(
                    error_envelope(exc.code, exc.message),
                    status=exc.status,
                )
            request.hr09_tenant_id = tenant_id
            return csrf_checked_view(request, *args, **kwargs)

        return wrapped

    return decorator


def current_person_id_or_raise(request, tenant_id: int):
    """Map authenticated Horilla user -> legacy Employee -> HR03 canonical person."""
    employee = getattr(request.user, "employee_get", None)
    try:
        if callable(employee):
            employee = employee()
    except Exception:
        employee = None

    legacy_employee_id = getattr(employee, "id", None)
    if not legacy_employee_id:
        legacy_employee_id = getattr(request.user, "employee_id", None)
    if not legacy_employee_id:
        raise QualificationAccessError(
            "SELF_STAFF_MAPPING_REQUIRED",
            "当前账号尚未关联教职工主档，无法执行本人双师申报。",
            403,
        )

    from hr_staff.models import HrStaffMaster

    staff = (
        HrStaffMaster.objects.filter(
            tenant_id=tenant_id,
            legacy_employee_id=legacy_employee_id,
        )
        .select_related("person_id")
        .first()
    )
    if staff is None:
        raise QualificationAccessError(
            "SELF_STAFF_MAPPING_REQUIRED",
            "当前账号在本学校没有可用的 HR03 教职工主档。",
            403,
        )
    return staff.person_id_id, staff.id


def access_error_response(exc: QualificationAccessError):
    from hr_qualification.api.serializers import error_envelope

    return JsonResponse(error_envelope(exc.code, exc.message), status=exc.status)
