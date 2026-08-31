import json

from django.http import JsonResponse
from django.utils import timezone

from base.auth_backends import get_allowed_company_ids
from hr_control_center.context import resolve_tenant_from_request

from .selectors import dashboard_snapshot
from .services.definition_service import HrDataDefinitionError, HrDataDefinitionService

READ_PERMISSION = "hr.data.view"
DEFINE_PERMISSION = "hr.data.define"


class HrDataAccessError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def resolve_request_tenant(request, *, required_permission: str = READ_PERMISSION) -> int:
    if not getattr(request.user, "is_authenticated", False):
        raise HrDataAccessError("AUTHENTICATION_REQUIRED", "authentication required")
    tenant_id = resolve_tenant_from_request(request)
    if not tenant_id:
        raise HrDataAccessError("TENANT_CONTEXT_REQUIRED", "请选择当前学校")
    tenant_id = int(tenant_id)
    if not request.user.is_superuser:
        allowed = {int(x) for x in get_allowed_company_ids(request.user)}
        if tenant_id not in allowed:
            raise HrDataAccessError("TENANT_ACCESS_DENIED", "当前账号无权访问该学校")
        if not request.user.has_perm(required_permission):
            raise HrDataAccessError(
                "PERMISSION_DENIED", f"缺少权限: {required_permission}"
            )
    return tenant_id


def _error(code: str, message: str = "", *, status: int) -> JsonResponse:
    response = JsonResponse({"error": {"code": code, "message": message}}, status=status)
    response["Cache-Control"] = "no-store"
    return response


def _payload(request):
    try:
        value = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("INVALID_JSON")
    if not isinstance(value, dict):
        raise ValueError("INVALID_JSON")
    return value


def dashboard(request):
    if request.method != "GET":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request)
    except HrDataAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    data = dashboard_snapshot(tenant_id)
    data.update(
        {
            "apiVersion": "1.0",
            "schemaVersion": "hr18.workspace.1",
            "generatedAt": timezone.now().isoformat(),
        }
    )
    response = JsonResponse(data)
    response["Cache-Control"] = "no-store"
    return response


def create_population_definition(request):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(
            request, required_permission=DEFINE_PERMISSION
        )
    except HrDataAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _payload(request)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
    try:
        outcome = HrDataDefinitionService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).create_population_version(
            population_code=payload.get("populationCode", ""),
            name=payload.get("name", ""),
            root_domain=payload.get("rootDomain", ""),
            grain=payload.get("grain", ""),
            predicate=payload.get("predicate"),
            source_domains=payload.get("sourceDomains"),
            description=payload.get("description", ""),
            as_of_required=payload.get("asOfRequired", True),
        )
    except HrDataDefinitionError as exc:
        return _error(exc.code, str(exc), status=400)
    definition = outcome.definition
    response = JsonResponse(
        {
            "data": {
                "id": str(definition.id),
                "populationCode": definition.population_code,
                "versionNo": definition.version_no,
                "grain": definition.grain,
                "status": definition.status,
                "contentHash": definition.content_hash,
                "created": outcome.created,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr18.population-definition.2",
        },
        status=201 if outcome.created else 200,
    )
    response["Cache-Control"] = "no-store"
    return response


def create_dimension_definition(request):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(
            request, required_permission=DEFINE_PERMISSION
        )
    except HrDataAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _payload(request)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
    try:
        outcome = HrDataDefinitionService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).create_dimension_version(
            dimension_code=payload.get("dimensionCode", ""),
            name=payload.get("name", ""),
            source_domain=payload.get("sourceDomain", ""),
            attribute_path=payload.get("attributePath", ""),
            value_type=payload.get("valueType", ""),
            label_map=payload.get("labelMap"),
            description=payload.get("description", ""),
            as_of_required=payload.get("asOfRequired", True),
        )
    except HrDataDefinitionError as exc:
        return _error(exc.code, str(exc), status=400)
    definition = outcome.definition
    response = JsonResponse(
        {
            "data": {
                "id": str(definition.id),
                "dimensionCode": definition.dimension_code,
                "versionNo": definition.version_no,
                "status": definition.status,
                "contentHash": definition.content_hash,
                "created": outcome.created,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr18.dimension-definition.1",
        },
        status=201 if outcome.created else 200,
    )
    response["Cache-Control"] = "no-store"
    return response
