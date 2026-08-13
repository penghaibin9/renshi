import json

from django.http import JsonResponse
from django.utils import timezone

from base.auth_backends import get_allowed_company_ids
from hr_control_center.context import resolve_tenant_from_request

from .selectors import dashboard_snapshot
from .services.ranking_service import AppointmentRankingError, AppointmentRankingService

READ_PERMISSION = "hr.appointment.view"
REVIEW_PERMISSION = "hr.appointment.review"


class HrAppointmentAccessError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def resolve_request_tenant(request, *, required_permission: str = READ_PERMISSION) -> int:
    if not getattr(request.user, "is_authenticated", False):
        raise HrAppointmentAccessError("AUTHENTICATION_REQUIRED", "authentication required")
    tenant_id = resolve_tenant_from_request(request)
    if not tenant_id:
        raise HrAppointmentAccessError("TENANT_CONTEXT_REQUIRED", "请选择当前学校")
    tenant_id = int(tenant_id)
    if not request.user.is_superuser:
        allowed = {int(x) for x in get_allowed_company_ids(request.user)}
        if tenant_id not in allowed:
            raise HrAppointmentAccessError("TENANT_ACCESS_DENIED", "当前账号无权访问该学校")
        if not request.user.has_perm(required_permission):
            raise HrAppointmentAccessError(
                "PERMISSION_DENIED", f"缺少权限: {required_permission}"
            )
    return tenant_id


def _error(code: str, message: str = "", *, status: int) -> JsonResponse:
    response = JsonResponse({"error": {"code": code, "message": message}}, status=status)
    response["Cache-Control"] = "no-store"
    return response


def dashboard(request):
    if request.method != "GET":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request)
    except HrAppointmentAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    data = dashboard_snapshot(tenant_id)
    data.update(
        {
            "apiVersion": "1.0",
            "schemaVersion": "hr14.workspace.1",
            "generatedAt": timezone.now().isoformat(),
        }
    )
    response = JsonResponse(data)
    response["Cache-Control"] = "no-store"
    return response


def ranking_result(request, case_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(
            request, required_permission=REVIEW_PERMISSION
        )
    except HrAppointmentAccessError as exc:
        return _error(exc.code, exc.message, status=403)

    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _error("INVALID_JSON", "请求体必须是合法 JSON", status=400)
    if not isinstance(payload, dict):
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)

    try:
        outcome = AppointmentRankingService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).finalize(
            case_id=case_id,
            ranking_no=payload.get("rankingNo", ""),
            total_score=payload.get("totalScore"),
            rank_no=payload.get("rankNo"),
            outcome=payload.get("outcome", ""),
            score_snapshot=payload.get("scoreSnapshot"),
        )
    except AppointmentRankingError as exc:
        if exc.code in {"APPOINTMENT_CASE_NOT_FOUND", "APPOINTMENT_BATCH_NOT_FOUND"}:
            status = 404
        elif exc.code in {
            "APPOINTMENT_RANKING_IDEMPOTENCY_CONFLICT",
            "APPOINTMENT_RANKING_INVALID_CASE_STATE",
            "APPOINTMENT_RANKING_INVALID_BATCH_STATE",
        }:
            status = 409
        else:
            status = 400
        return _error(exc.code, str(exc), status=status)

    ranking = outcome.ranking
    response = JsonResponse(
        {
            "data": {
                "id": str(ranking.id),
                "rankingNo": ranking.ranking_no,
                "applicationCaseId": str(ranking.application_case_id),
                "batchNo": ranking.batch_no,
                "positionInstanceId": ranking.position_instance_id,
                "attemptNo": ranking.attempt_no,
                "totalScore": str(ranking.total_score),
                "rankNo": ranking.rank_no,
                "outcome": ranking.outcome,
                "caseStatus": outcome.case.status,
                "created": outcome.created,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr14.ranking-result.1",
        },
        status=201 if outcome.created else 200,
    )
    response["Cache-Control"] = "no-store"
    return response
