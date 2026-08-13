import json

from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from base.auth_backends import get_allowed_company_ids
from hr_control_center.context import resolve_tenant_from_request

from .selectors import dashboard_snapshot
from .services.publicity_service import (
    AppointmentPublicityError,
    AppointmentPublicityService,
)
from .services.ranking_service import AppointmentRankingError, AppointmentRankingService

READ_PERMISSION = "hr.appointment.view"
REVIEW_PERMISSION = "hr.appointment.review"
PUBLICITY_PERMISSION = "hr.appointment.publicity"


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


def _payload(request):
    try:
        value = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("INVALID_JSON")
    if not isinstance(value, dict):
        raise ValueError("INVALID_JSON")
    return value


def _datetime(value, *, field: str):
    if not value:
        raise ValueError(field)
    parsed = parse_datetime(str(value))
    if parsed is None:
        raise ValueError(field)
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _publicity_status(code: str) -> int:
    if code in {
        "APPOINTMENT_CASE_NOT_FOUND",
        "APPOINTMENT_BATCH_NOT_FOUND",
        "APPOINTMENT_PUBLICITY_NOT_FOUND",
        "APPOINTMENT_OBJECTION_NOT_FOUND",
    }:
        return 404
    if code in {
        "APPOINTMENT_PUBLICITY_IDEMPOTENCY_CONFLICT",
        "APPOINTMENT_PUBLICITY_INVALID_CASE_STATE",
        "APPOINTMENT_PUBLICITY_INVALID_BATCH_STATE",
        "APPOINTMENT_BATCH_RANKING_INCOMPLETE",
        "APPOINTMENT_SELECTED_RANKING_REQUIRED",
        "APPOINTMENT_PUBLICITY_BATCH_WINDOW_MISMATCH",
        "APPOINTMENT_PUBLICITY_NOT_OPEN",
        "APPOINTMENT_OBJECTION_OUTSIDE_WINDOW",
        "APPOINTMENT_OBJECTION_IDEMPOTENCY_CONFLICT",
        "APPOINTMENT_OBJECTION_ALREADY_RESOLVED",
        "APPOINTMENT_PUBLICITY_WINDOW_NOT_ENDED",
        "APPOINTMENT_PUBLICITY_OBJECTION_PENDING",
        "APPOINTMENT_PUBLICITY_UPHELD_OBJECTION",
    }:
        return 409
    return 400


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
        payload = _payload(request)
    except ValueError:
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


def open_publicity(request, case_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(
            request, required_permission=PUBLICITY_PERMISSION
        )
    except HrAppointmentAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _payload(request)
        start_at = _datetime(payload.get("startAt"), field="startAt")
        end_at = _datetime(payload.get("endAt"), field="endAt")
    except ValueError as exc:
        field = str(exc)
        if field == "INVALID_JSON":
            return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
        return _error("INVALID_DATETIME", f"{field} 必须是 ISO-8601 时间", status=400)
    try:
        outcome = AppointmentPublicityService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).open_publicity(
            case_id=case_id,
            ranking_result_id=payload.get("rankingResultId"),
            publicity_no=payload.get("publicityNo", ""),
            start_at=start_at,
            end_at=end_at,
            notice_snapshot=payload.get("noticeSnapshot"),
        )
    except AppointmentPublicityError as exc:
        return _error(exc.code, str(exc), status=_publicity_status(exc.code))
    record = outcome.publicity
    response = JsonResponse(
        {
            "data": {
                "id": str(record.id),
                "publicityNo": record.publicity_no,
                "applicationCaseId": str(record.application_case_id),
                "rankingResultId": str(record.ranking_result_id),
                "attemptNo": record.attempt_no,
                "startAt": record.start_at.isoformat(),
                "endAt": record.end_at.isoformat(),
                "status": record.status,
                "caseStatus": outcome.case.status,
                "created": outcome.created,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr14.publicity.1",
        },
        status=201 if outcome.created else 200,
    )
    response["Cache-Control"] = "no-store"
    return response


def submit_publicity_objection(request, publicity_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(
            request, required_permission=PUBLICITY_PERMISSION
        )
    except HrAppointmentAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _payload(request)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
    try:
        objection = AppointmentPublicityService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).submit_objection(
            publicity_id=publicity_id,
            objection_no=payload.get("objectionNo", ""),
            content_summary=payload.get("contentSummary", ""),
            submitter_ref=payload.get("submitterRef", ""),
            evidence_refs=payload.get("evidenceRefs"),
        )
    except AppointmentPublicityError as exc:
        return _error(exc.code, str(exc), status=_publicity_status(exc.code))
    response = JsonResponse(
        {
            "data": {
                "id": str(objection.id),
                "objectionNo": objection.objection_no,
                "publicityId": str(objection.publicity_id),
                "status": objection.status,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr14.publicity-objection.1",
        },
        status=201,
    )
    response["Cache-Control"] = "no-store"
    return response


def resolve_publicity_objection(request, objection_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(
            request, required_permission=PUBLICITY_PERMISSION
        )
    except HrAppointmentAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _payload(request)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
    try:
        objection = AppointmentPublicityService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).resolve_objection(
            objection_id,
            outcome=payload.get("outcome", ""),
            resolution_note=payload.get("resolutionNote", ""),
        )
    except AppointmentPublicityError as exc:
        return _error(exc.code, str(exc), status=_publicity_status(exc.code))
    response = JsonResponse(
        {
            "data": {
                "id": str(objection.id),
                "objectionNo": objection.objection_no,
                "status": objection.status,
                "resolutionNote": objection.resolution_note,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr14.publicity-objection.1",
        }
    )
    response["Cache-Control"] = "no-store"
    return response


def close_publicity(request, publicity_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(
            request, required_permission=PUBLICITY_PERMISSION
        )
    except HrAppointmentAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        record = AppointmentPublicityService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).close_publicity(publicity_id)
    except AppointmentPublicityError as exc:
        return _error(exc.code, str(exc), status=_publicity_status(exc.code))
    response = JsonResponse(
        {
            "data": {"id": str(record.id), "status": record.status},
            "apiVersion": "1.0",
            "schemaVersion": "hr14.publicity.1",
        }
    )
    response["Cache-Control"] = "no-store"
    return response


def cancel_publicity(request, publicity_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(
            request, required_permission=PUBLICITY_PERMISSION
        )
    except HrAppointmentAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _payload(request)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
    try:
        record = AppointmentPublicityService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).cancel_publicity(publicity_id, reason=payload.get("reason", ""))
    except AppointmentPublicityError as exc:
        return _error(exc.code, str(exc), status=_publicity_status(exc.code))
    response = JsonResponse(
        {
            "data": {"id": str(record.id), "status": record.status},
            "apiVersion": "1.0",
            "schemaVersion": "hr14.publicity.1",
        }
    )
    response["Cache-Control"] = "no-store"
    return response
