import json

from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from base.auth_backends import get_allowed_company_ids
from hr_control_center.context import resolve_tenant_from_request

from .selectors import dashboard_snapshot
from .services.effect_service import AppointmentEffectError, AppointmentEffectService
from .services.publicity_service import (
    AppointmentPublicityError,
    AppointmentPublicityService,
)
from .services.ranking_service import AppointmentRankingError, AppointmentRankingService

READ_PERMISSION = "hr.appointment.view"
REVIEW_PERMISSION = "hr.appointment.review"
PUBLICITY_PERMISSION = "hr.appointment.publicity"
EFFECT_PERMISSION = "hr.appointment.effect"
FACT_PUBLISH_PERMISSION = "hr.appointment.fact.publish"


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


def _date(value, *, field: str):
    if not value:
        raise ValueError(field)
    parsed = parse_date(str(value))
    if parsed is None:
        raise ValueError(field)
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


def _effect_status(code: str) -> int:
    if code in {
        "APPOINTMENT_CASE_NOT_FOUND",
        "APPOINTMENT_RESERVATION_NOT_FOUND",
        "APPOINTMENT_STAFF_NOT_FOUND",
    }:
        return 404
    if code in {
        "APPOINTMENT_CASE_INVALID_STATE",
        "APPOINTMENT_EFFECT_IDEMPOTENCY_CONFLICT",
        "APPOINTMENT_RESULT_INVALID_STATE",
        "APPOINTMENT_PUBLICITY_NOT_CLOSED",
        "APPOINTMENT_PUBLICITY_OBJECTION_BLOCKS_EFFECT",
        "APPOINTMENT_QUOTA_RESERVATION_REQUIRED",
        "APPOINTMENT_QUOTA_BATCH_MISMATCH",
        "APPOINTMENT_QUOTA_NOT_ACTIVE",
        "APPOINTMENT_RESERVATION_INVALID_STATE",
        "APPOINTMENT_RESERVATION_EXPIRED",
        "APPOINTMENT_RESERVATION_POSITION_MISMATCH",
        "APPOINTMENT_RESERVATION_SOURCE_MISMATCH",
        "APPOINTMENT_RESERVATION_OWNER_MISMATCH",
        "APPOINTMENT_POSITION_NOT_ACTIVE",
        "APPOINTMENT_ACTIVE_RELATIONSHIP_REQUIRED",
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
            "APPOINTMENT_RANKING_QUOTA_ALREADY_CONSUMED",
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


def apply_effect(request, case_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        try:
            tenant_id = resolve_request_tenant(
                request, required_permission=FACT_PUBLISH_PERMISSION
            )
        except HrAppointmentAccessError as publish_exc:
            if publish_exc.code != "PERMISSION_DENIED":
                raise
            # Compatibility bridge for roles created before the dedicated
            # publication permission.  Correction/revocation never use it.
            tenant_id = resolve_request_tenant(
                request, required_permission=EFFECT_PERMISSION
            )
    except HrAppointmentAccessError as exc:
        return _error(exc.code, exc.message, status=403)

    try:
        payload = _payload(request)
        effective_from = _date(payload.get("effectiveFrom"), field="effectiveFrom")
    except ValueError as exc:
        field = str(exc)
        if field == "INVALID_JSON":
            return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
        return _error("INVALID_DATE", f"{field} 必须是 YYYY-MM-DD 日期", status=400)

    appointment_no = str(payload.get("appointmentNo", "") or "").strip()
    if not appointment_no:
        return _error(
            "APPOINTMENT_NO_REQUIRED",
            "appointmentNo 不能为空",
            status=400,
        )
    try:
        reservation_id = int(payload.get("reservationId"))
    except (TypeError, ValueError):
        return _error(
            "INVALID_RESERVATION_ID",
            "reservationId 必须是正整数",
            status=400,
        )
    if reservation_id <= 0:
        return _error(
            "INVALID_RESERVATION_ID",
            "reservationId 必须是正整数",
            status=400,
        )

    try:
        effect_kwargs = dict(
            case_id=case_id,
            appointment_no=appointment_no,
            reservation_id=reservation_id,
            effective_from=effective_from,
            level_code=str(payload.get("levelCode", "") or "").strip(),
        )
        request_idempotency_key = str(
            request.headers.get("Idempotency-Key", "") or ""
        ).strip()
        if request_idempotency_key:
            effect_kwargs["idempotency_key"] = request_idempotency_key
        outcome = AppointmentEffectService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).apply(**effect_kwargs)
    except AppointmentEffectError as exc:
        return _error(exc.code, str(exc), status=_effect_status(exc.code))

    fact = outcome.fact
    response = JsonResponse(
        {
            "data": {
                "id": str(fact.id),
                "appointmentNo": fact.appointment_no,
                "applicationCaseId": str(fact.application_case_id),
                "positionInstanceId": fact.position_instance_id,
                "effectiveFrom": fact.effective_from.isoformat(),
                "status": fact.status,
                "effective": outcome.effective,
                "effectReceipt": fact.effect_receipt_json,
                "factKind": getattr(fact, "fact_kind", "INITIAL"),
                "supersedesFactId": (
                    str(fact.supersedes_fact_id)
                    if getattr(fact, "supersedes_fact_id", None)
                    else None
                ),
                "contentHash": getattr(fact, "content_hash", ""),
                "sealedAt": (
                    fact.sealed_at.isoformat()
                    if getattr(fact, "sealed_at", None)
                    else None
                ),
                "publishedBy": getattr(fact, "published_by", None),
                "authorityReceipt": getattr(
                    fact, "authority_receipt_json", {}
                ),
                "error": outcome.error,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr14.appointment-effect.1",
        },
        status=200 if outcome.effective else 202,
    )
    response["Cache-Control"] = "no-store"
    return response
