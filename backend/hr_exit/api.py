import json
import uuid

from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from base.auth_backends import get_allowed_company_ids
from hr_control_center.context import resolve_tenant_from_request

from .selectors import dashboard_snapshot
from .services.case_service import ExitCaseError, ExitCaseInput, ExitCaseService
from .services.effect_service import ExitEffectError, ExitEffectService
from .services.handover_service import ExitHandoverError, ExitHandoverService
from .services.saga_service import ExitSagaError

READ_PERMISSION = "hr.exit.view"
MANAGE_PERMISSION = "hr.exit.manage"
HANDOVER_PERMISSION = "hr.exit.handover"
EFFECT_PERMISSION = "hr.exit.effect"


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


def _optional_date(value, *, field: str):
    if value in (None, ""):
        return None
    parsed = parse_date(str(value))
    if parsed is None:
        raise ValueError(field)
    return parsed


def _optional_datetime(value, *, field: str):
    if value in (None, ""):
        return None
    parsed = parse_datetime(str(value))
    if parsed is None:
        raise ValueError(field)
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _uuid(value, *, field: str):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise ValueError(field)


def _case_status(code: str) -> int:
    if code in {"EXIT_CASE_NOT_FOUND", "EXIT_RELATIONSHIP_NOT_FOUND"}:
        return 404
    if code in {
        "EXIT_CASE_INVALID_STATE",
        "EXIT_CASE_ALREADY_OPEN",
        "EXIT_CASE_NO_CONFLICT",
        "EXIT_RELATIONSHIP_PERSON_MISMATCH",
        "EXIT_RELATIONSHIP_NOT_ACTIVE",
        "EXIT_WORKING_DATE_AFTER_END_DATE",
        "EXIT_HANDOVER_INCOMPLETE",
    }:
        return 409
    return 400


def _effect_status(code: str) -> int:
    if code in {"EXIT_CASE_NOT_FOUND", "EXIT_RELATIONSHIP_NOT_FOUND", "EXIT_EFFECT_NOT_FOUND"}:
        return 404
    if code in {
        "EXIT_CASE_INVALID_STATE",
        "EXIT_RELATIONSHIP_PERSON_MISMATCH",
        "EXIT_EFFECT_IDEMPOTENCY_CONFLICT",
        "EXIT_FACT_INVALID_STATE",
        "EXIT_EFFECT_SUCCESS_IMMUTABLE",
    }:
        return 409
    return 400


def _case_data(case):
    return {
        "id": str(case.id),
        "caseNo": case.case_no,
        "personId": str(case.person_id),
        "employmentRelationshipId": str(case.employment_relationship_id),
        "exitType": case.exit_type,
        "status": case.status,
        "requestedDate": case.requested_date.isoformat() if case.requested_date else None,
        "lastWorkingDate": case.last_working_date.isoformat() if case.last_working_date else None,
        "plannedEmploymentEndDate": (
            case.planned_employment_end_date.isoformat()
            if case.planned_employment_end_date
            else None
        ),
        "plannedAccessEndAt": (
            case.planned_access_end_at.isoformat() if case.planned_access_end_at else None
        ),
    }


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


def create_case(request):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request, required_permission=MANAGE_PERMISSION)
    except HrExitAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _payload(request)
        person_id = _uuid(payload.get("personId"), field="personId")
        relationship_id = _uuid(
            payload.get("employmentRelationshipId"),
            field="employmentRelationshipId",
        )
        requested_date = _optional_date(payload.get("requestedDate"), field="requestedDate")
        last_working_date = _optional_date(
            payload.get("lastWorkingDate"), field="lastWorkingDate"
        )
        planned_end = _optional_date(
            payload.get("plannedEmploymentEndDate"),
            field="plannedEmploymentEndDate",
        )
        planned_access_end = _optional_datetime(
            payload.get("plannedAccessEndAt"),
            field="plannedAccessEndAt",
        )
    except ValueError as exc:
        field = str(exc)
        if field == "INVALID_JSON":
            return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
        return _error("INVALID_FIELD", f"字段格式错误: {field}", status=400)

    try:
        case = ExitCaseService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).create_draft(
            ExitCaseInput(
                case_no=payload.get("caseNo", ""),
                person_id=person_id,
                employment_relationship_id=relationship_id,
                exit_type=payload.get("exitType", ""),
                requested_date=requested_date,
                last_working_date=last_working_date,
                planned_employment_end_date=planned_end,
                planned_access_end_at=planned_access_end,
            )
        )
    except ExitCaseError as exc:
        return _error(exc.code, str(exc), status=_case_status(exc.code))

    response = JsonResponse(
        {
            "data": _case_data(case),
            "apiVersion": "1.0",
            "schemaVersion": "hr16.exit-case.1",
        },
        status=201,
    )
    response["Cache-Control"] = "no-store"
    return response


def _transition_case(request, case_id, method_name: str):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request, required_permission=MANAGE_PERMISSION)
    except HrExitAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    service = ExitCaseService(
        tenant_id,
        actor_user_id=getattr(request.user, "id", None),
    )
    try:
        case = getattr(service, method_name)(case_id)
    except ExitCaseError as exc:
        return _error(exc.code, str(exc), status=_case_status(exc.code))
    response = JsonResponse(
        {
            "data": _case_data(case),
            "apiVersion": "1.0",
            "schemaVersion": "hr16.exit-case.1",
        }
    )
    response["Cache-Control"] = "no-store"
    return response


def submit_case(request, case_id):
    return _transition_case(request, case_id, "submit")


def return_case(request, case_id):
    return _transition_case(request, case_id, "return_for_correction")


def approve_case(request, case_id):
    return _transition_case(request, case_id, "approve")


def reject_case(request, case_id):
    return _transition_case(request, case_id, "reject")


def cancel_case(request, case_id):
    return _transition_case(request, case_id, "cancel_before_approval")


def begin_handover(request, case_id):
    return _transition_case(request, case_id, "begin_handover")


def begin_settlement(request, case_id):
    return _transition_case(request, case_id, "begin_settlement")


def apply_effect(request, case_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request, required_permission=EFFECT_PERMISSION)
    except HrExitAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _payload(request)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)

    required_participants = payload.get("requiredParticipants", [])
    if not isinstance(required_participants, list) or not all(
        isinstance(value, str) for value in required_participants
    ):
        return _error(
            "EXIT_EFFECT_PARTICIPANTS_INVALID",
            "requiredParticipants 必须是字符串数组",
            status=400,
        )

    try:
        outcome = ExitEffectService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).apply(
            case_id=case_id,
            fact_no=payload.get("factNo", ""),
            idempotency_key=payload.get("idempotencyKey", ""),
            reason_code=str(payload.get("reasonCode", "") or "").strip(),
            correlation_id=str(payload.get("correlationId", "") or "").strip(),
            required_participants=required_participants,
        )
    except (ExitEffectError, ExitSagaError) as exc:
        return _error(exc.code, str(exc), status=_effect_status(exc.code))

    fact = outcome.fact
    effect = outcome.effect
    response = JsonResponse(
        {
            "data": {
                "factId": str(fact.id),
                "factNo": fact.fact_no,
                "factStatus": fact.status,
                "effective": outcome.effective,
                "effectId": str(effect.id),
                "effectVersion": effect.effect_version,
                "sagaStatus": effect.status,
                "hr03Status": effect.hr03_status,
                "hr07Status": effect.hr07_status,
                "hr14Status": effect.hr14_status,
                "iamStatus": effect.iam_status,
                "assetStatus": effect.asset_status,
                "settlementStatus": effect.settlement_status,
                "financeStatus": effect.finance_status,
                "archiveStatus": effect.archive_status,
                "effectReceipt": fact.effect_receipt_json,
                "supersedesFactId": (
                    str(getattr(fact, "supersedes_fact_id"))
                    if getattr(fact, "supersedes_fact_id", None)
                    else None
                ),
                "changeReason": fact.change_reason,
                "evidenceRef": fact.evidence_ref,
                "contentHash": fact.content_hash,
                "sealedAt": fact.sealed_at.isoformat() if fact.sealed_at else None,
                "error": outcome.error,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr16.exit-effect.2",
        },
        status=200 if outcome.effective else 202,
    )
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
