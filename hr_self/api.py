import json

from django.http import JsonResponse
from django.utils import timezone

from base.auth_backends import get_allowed_company_ids
from hr_control_center.context import resolve_tenant_from_request

from .selectors import dashboard_snapshot
from .services.bootstrap_service import SelfBootstrapService
from .services.catalog_service import SelfCatalogError, SelfCatalogService
from .services.identity_service import SelfIdentityError, SelfIdentityService
from .services.self_records_service import SelfRecordsService

READ_PERMISSION = "hr.self.view"


class HrSelfAccessError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def resolve_self_context(request):
    if not getattr(request.user, "is_authenticated", False):
        raise HrSelfAccessError("AUTHENTICATION_REQUIRED", "authentication required")
    tenant_id = resolve_tenant_from_request(request)
    if not tenant_id:
        raise HrSelfAccessError("TENANT_CONTEXT_REQUIRED", "请选择当前学校")
    tenant_id = int(tenant_id)
    if not request.user.is_superuser:
        allowed = {int(x) for x in get_allowed_company_ids(request.user)}
        if tenant_id not in allowed:
            raise HrSelfAccessError("TENANT_ACCESS_DENIED", "当前账号无权访问该学校")
        if not request.user.has_perm(READ_PERMISSION):
            raise HrSelfAccessError("PERMISSION_DENIED", f"缺少权限: {READ_PERMISSION}")
    try:
        return SelfIdentityService(tenant_id).resolve(request.user)
    except SelfIdentityError as exc:
        raise HrSelfAccessError("SELF_IDENTITY_NOT_RESOLVED", str(exc)) from exc


def _access_error(exc: HrSelfAccessError):
    response = JsonResponse(
        {"error": {"code": exc.code, "message": exc.message}},
        status=403,
    )
    response["Cache-Control"] = "no-store"
    return response


def _method_not_allowed():
    response = JsonResponse({"error": {"code": "METHOD_NOT_ALLOWED"}}, status=405)
    response["Cache-Control"] = "no-store"
    return response


def _identity_override_forbidden(request):
    forbidden = {
        "staff_id",
        "staffId",
        "person_id",
        "personId",
        "employee_id",
        "employeeId",
    }
    if any(key in request.GET for key in forbidden):
        response = JsonResponse(
            {
                "error": {
                    "code": "SELF_IDENTITY_OVERRIDE_FORBIDDEN",
                    "message": "SELF identity is resolved only from the current login and tenant",
                }
            },
            status=400,
        )
        response["Cache-Control"] = "no-store"
        return response
    return None


def dashboard(request):
    if request.method != "GET":
        return _method_not_allowed()
    try:
        context = resolve_self_context(request)
    except HrSelfAccessError as exc:
        return _access_error(exc)
    data = dashboard_snapshot(context)
    data.update(
        {
            "apiVersion": "1.0",
            "schemaVersion": "hr17.workspace.1",
            "generatedAt": timezone.now().isoformat(),
        }
    )
    response = JsonResponse(data)
    response["Cache-Control"] = "no-store"
    return response


def bootstrap(request):
    """Return the HR17 first-screen aggregate in one request.

    Each source provider is isolated inside ``SelfBootstrapService``. A failing
    HR03-HR16 source is represented in ``providerHealth`` and does not become an
    empty list/zero or fail the whole response.
    """

    if request.method != "GET":
        return _method_not_allowed()
    try:
        context = resolve_self_context(request)
    except HrSelfAccessError as exc:
        return _access_error(exc)

    data = SelfBootstrapService(context).build()
    data.update(
        {
            "apiVersion": "1.0",
            "schemaVersion": "hr17.bootstrap.1",
            "generatedAt": timezone.now().isoformat(),
        }
    )
    response = JsonResponse(data)
    response["Cache-Control"] = "no-store"
    return response


def self_records(request):
    """Return controlled files, contract summaries and payslip summaries.

    The route deliberately has no staff/person identifier.  Each source has an
    independent health envelope; unavailable Authority data is returned as
    ``null`` and is never forged into an empty list.
    """

    if request.method != "GET":
        return _method_not_allowed()
    override_error = _identity_override_forbidden(request)
    if override_error is not None:
        return override_error
    try:
        context = resolve_self_context(request)
    except HrSelfAccessError as exc:
        return _access_error(exc)

    data = SelfRecordsService(context).build()
    data.update(
        {
            "apiVersion": "1.0",
            "schemaVersion": "hr17.self-records.1",
            "generatedAt": timezone.now().isoformat(),
        }
    )
    response = JsonResponse(data)
    response["Cache-Control"] = "no-store"
    return response


def service_pin(request, service_code: str):
    """Pin/unpin a catalog service for the authenticated SELF identity.

    No staff identifier is accepted in path, query or payload. Ownership is
    resolved only from ``resolve_self_context``.
    """
    if request.method not in {"POST", "DELETE"}:
        return _method_not_allowed()
    try:
        context = resolve_self_context(request)
    except HrSelfAccessError as exc:
        return _access_error(exc)

    service = SelfCatalogService(context)
    if request.method == "DELETE":
        deleted = service.unpin(service_code=service_code)
        response = JsonResponse(
            {"serviceCode": service_code, "pinned": False, "deleted": bool(deleted)}
        )
        response["Cache-Control"] = "no-store"
        return response

    try:
        payload = json.loads(request.body or b"{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        response = JsonResponse({"error": {"code": "INVALID_JSON"}}, status=400)
        response["Cache-Control"] = "no-store"
        return response
    if not isinstance(payload, dict):
        response = JsonResponse({"error": {"code": "INVALID_JSON"}}, status=400)
        response["Cache-Control"] = "no-store"
        return response
    try:
        sort_order = int(payload.get("sortOrder", 100))
    except (TypeError, ValueError):
        response = JsonResponse({"error": {"code": "SORT_ORDER_INVALID"}}, status=400)
        response["Cache-Control"] = "no-store"
        return response

    try:
        pin = service.pin(service_code=service_code, sort_order=sort_order)
    except SelfCatalogError as exc:
        response = JsonResponse(
            {"error": {"code": exc.code, "message": str(exc)}},
            status=404,
        )
        response["Cache-Control"] = "no-store"
        return response

    response = JsonResponse(
        {
            "serviceCode": pin.service_code,
            "pinned": True,
            "sortOrder": pin.sort_order,
        }
    )
    response["Cache-Control"] = "no-store"
    return response
