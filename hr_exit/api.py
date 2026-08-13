import json

from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_date

from base.auth_backends import get_allowed_company_ids
from hr_control_center.context import resolve_tenant_from_request

from .selectors import dashboard_snapshot
from .services.handover_service import ExitHandoverError, ExitHandoverService

READ_PERMISSION = "hr.exit.view"
HANDOVER_PERMISSION = "hr.exit.handover"


class HrExitAccessError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def resolve_request_tenant(request, *, required_permission: str = READ_PERMISSION) -> int:
    if not getattr(request.user, "is_authenticated", False):
        raise HrExitAccessError("AUTHENTICATION_REQUIRED", "authentication required")
    tenant_id = resolve_tenant_from_request(request)
    if not tenant_id:
        raise HrExitAccessError("TENANT_CONTEXT_REQUIRED", "请选择当前学校")
    tenant_id = int(tenant_id)
    if not request.user.is_superuser:
        allowed = {int(x) for x in get_allowed_company_ids(request.user)}
        if tenant_id not in allowed:
            raise HrExitAccessError("TENANT_ACCESS_DENIED", "当前账号无权访问该学校")
        if not request.user.has_perm(required_permission):
            raise HrExitAccessError(
                "PERMISSION_DENIED", f"缺少权限: {required_permission}"
            )
    return tenant_id


def _error(code: str, message: str = "", *, status: int) -> JsonResponse:
    response = JsonResponse({"error": {"code": code, "message": message}}, status=status)
    response["Cache-Control"] = "no-store"
    return response


def _payload(request):
    try:
        data = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("INVALID_JSON")
    if not isinstance(data, dict):
        raise ValueError("INVALID_JSON")
    return data


def dashboard(request):
    if request.method != "GET":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request)
    except HrExitAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    data = dashboard_snapshot(tenant_id)
    data.update(
        {
            "apiVersion": "1.0",
            "schemaVersion": "hr16.workspace.1",
            "generatedAt": timezone.now().isoformat(),
        }
    )
    response = JsonResponse(data)
    response["Cache-Control"] = "no-store"
    return response


def create_handover_item(request, case_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(
            request, required_permission=HANDOVER_PERMISSION
        )
    except HrExitAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _payload(request)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)

    due_date = None
    if payload.get("dueDate"):
        due_date = parse_date(str(payload["dueDate"]))
        if due_date is None:
            return _error("INVALID_DUE_DATE", "dueDate 必须是 YYYY-MM-DD", status=400)

    try:
        item = ExitHandoverService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).add_item(
            case_id=case_id,
            item_no=payload.get("itemNo", ""),
            category_code=payload.get("categoryCode", ""),
            title=payload.get("title", ""),
            description=payload.get("description", ""),
            required=payload.get("required", True),
            owner_staff_id=payload.get("ownerStaffId"),
            due_date=due_date,
            supersedes_item_id=payload.get("supersedesItemId"),
        )
    except ExitHandoverError as exc:
        status = 404 if exc.code in {
            "EXIT_CASE_NOT_FOUND",
            "EXIT_HANDOVER_SUPERSEDED_ITEM_NOT_FOUND",
        } else 409 if exc.code in {
            "EXIT_HANDOVER_INVALID_CASE_STATE",
            "EXIT_HANDOVER_ITEM_NO_CONFLICT",
        } else 400
        return _error(exc.code, str(exc), status=status)

    response = JsonResponse(
        {
            "data": {
                "id": str(item.id),
                "itemNo": item.item_no,
                "caseId": str(item.case_id),
                "categoryCode": item.category_code,
                "title": item.title,
                "required": item.required,
                "ownerStaffId": str(item.owner_staff_id) if item.owner_staff_id else None,
                "dueDate": item.due_date.isoformat() if item.due_date else None,
                "status": item.status,
                "supersedesItemId": str(item.supersedes_item_id) if item.supersedes_item_id else None,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr16.handover-item.1",
        },
        status=201,
    )
    response["Cache-Control"] = "no-store"
    return response


def complete_handover_item(request, item_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(
            request, required_permission=HANDOVER_PERMISSION
        )
    except HrExitAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _payload(request)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
    try:
        item = ExitHandoverService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).complete(item_id, evidence_ref=payload.get("evidenceRef", ""))
    except ExitHandoverError as exc:
        status = 404 if exc.code == "EXIT_HANDOVER_ITEM_NOT_FOUND" else 409
        return _error(exc.code, str(exc), status=status)
    response = JsonResponse(
        {
            "data": {"id": str(item.id), "status": item.status},
            "apiVersion": "1.0",
            "schemaVersion": "hr16.handover-item.1",
        }
    )
    response["Cache-Control"] = "no-store"
    return response


def waive_handover_item(request, item_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(
            request, required_permission=HANDOVER_PERMISSION
        )
    except HrExitAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _payload(request)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
    try:
        item = ExitHandoverService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).waive(item_id, reason=payload.get("reason", ""))
    except ExitHandoverError as exc:
        if exc.code == "EXIT_HANDOVER_ITEM_NOT_FOUND":
            status = 404
        elif exc.code in {
            "EXIT_HANDOVER_ITEM_ALREADY_TERMINAL",
            "EXIT_HANDOVER_INVALID_CASE_STATE",
        }:
            status = 409
        else:
            status = 400
        return _error(exc.code, str(exc), status=status)
    response = JsonResponse(
        {
            "data": {"id": str(item.id), "status": item.status},
            "apiVersion": "1.0",
            "schemaVersion": "hr16.handover-item.1",
        }
    )
    response["Cache-Control"] = "no-store"
    return response
