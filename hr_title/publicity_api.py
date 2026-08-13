"""Canonical HR13 publicity and appeal API endpoints."""

from __future__ import annotations

from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .api import HrTitleAccessError, _error, _json_payload, resolve_request_tenant
from .services.publicity_service import TitlePublicityError, TitlePublicityService

PUBLICITY_PERMISSION = "hr.title.publicity"


def _dt(value):
    parsed = parse_datetime(str(value or "").strip())
    if parsed is None:
        raise ValueError("datetime is required in ISO-8601 format")
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _publicity_error(exc: TitlePublicityError) -> JsonResponse:
    if exc.code in {
        "TITLE_CASE_NOT_FOUND",
        "TITLE_PUBLICITY_NOT_FOUND",
        "TITLE_APPEAL_NOT_FOUND",
    }:
        status = 404
    elif exc.code in {
        "TITLE_PUBLICITY_INVALID_CASE_STATE",
        "TITLE_PUBLICITY_ALREADY_OPEN",
        "TITLE_APPEAL_PUBLICITY_NOT_OPEN",
        "TITLE_APPEAL_WINDOW_CLOSED",
        "TITLE_APPEAL_ALREADY_RESOLVED",
        "TITLE_PUBLICITY_NOT_OPEN",
        "TITLE_PUBLICITY_PERIOD_NOT_ENDED",
        "TITLE_PUBLICITY_APPEALS_PENDING",
        "TITLE_PUBLICITY_UPHELD_APPEAL",
        "TITLE_PUBLICITY_CASE_STATE_MISMATCH",
    }:
        status = 409
    else:
        status = 400
    return _error(exc.code, str(exc), status=status)


def _service(request):
    tenant_id = resolve_request_tenant(
        request, required_permission=PUBLICITY_PERMISSION
    )
    return TitlePublicityService(
        tenant_id, actor_user_id=getattr(request.user, "id", None)
    )


def open_publicity(request, case_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        service = _service(request)
    except HrTitleAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _json_payload(request)
        start_at = _dt(payload.get("startAt"))
        end_at = _dt(payload.get("endAt"))
    except ValueError as exc:
        return _error("INVALID_REQUEST", str(exc), status=400)
    try:
        publicity = service.open_publicity(
            case_id=case_id,
            publicity_no=payload.get("publicityNo", ""),
            start_at=start_at,
            end_at=end_at,
            content_snapshot=payload.get("contentSnapshot"),
        )
    except TitlePublicityError as exc:
        return _publicity_error(exc)
    return JsonResponse(
        {
            "data": {
                "id": str(publicity.id),
                "publicityNo": publicity.publicity_no,
                "applicationCaseId": str(publicity.application_case_id),
                "startAt": publicity.start_at.isoformat(),
                "endAt": publicity.end_at.isoformat(),
                "status": publicity.status,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr13.publicity.1",
        },
        status=201,
    )


def lodge_appeal(request, publicity_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        service = _service(request)
    except HrTitleAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _json_payload(request)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是合法 JSON 对象", status=400)
    try:
        appeal = service.lodge_appeal(
            publicity_id=publicity_id,
            appeal_no=payload.get("appealNo", ""),
            reason=payload.get("reason", ""),
            appellant_ref=payload.get("appellantRef", ""),
            evidence=payload.get("evidence"),
        )
    except TitlePublicityError as exc:
        return _publicity_error(exc)
    return JsonResponse(
        {
            "data": {
                "id": str(appeal.id),
                "appealNo": appeal.appeal_no,
                "publicityId": str(appeal.publicity_id),
                "applicationCaseId": str(appeal.application_case_id),
                "status": appeal.status,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr13.appeal.1",
        },
        status=201,
    )


def resolve_appeal(request, appeal_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        service = _service(request)
    except HrTitleAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _json_payload(request)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是合法 JSON 对象", status=400)
    try:
        appeal = service.resolve_appeal(
            appeal_id,
            outcome=payload.get("outcome", ""),
            resolution=payload.get("resolution", ""),
        )
    except TitlePublicityError as exc:
        return _publicity_error(exc)
    return JsonResponse(
        {
            "data": {
                "id": str(appeal.id),
                "appealNo": appeal.appeal_no,
                "status": appeal.status,
                "resolution": appeal.resolution,
                "resolvedAt": appeal.resolved_at.isoformat() if appeal.resolved_at else None,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr13.appeal-resolution.1",
        }
    )


def close_publicity(request, publicity_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        service = _service(request)
    except HrTitleAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        publicity = service.close_publicity(publicity_id)
    except TitlePublicityError as exc:
        return _publicity_error(exc)
    return JsonResponse(
        {
            "data": {
                "id": str(publicity.id),
                "publicityNo": publicity.publicity_no,
                "status": publicity.status,
                "closedAt": publicity.closed_at.isoformat() if publicity.closed_at else None,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr13.publicity-close.1",
        }
    )


def cancel_publicity(request, publicity_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        service = _service(request)
    except HrTitleAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        publicity = service.cancel_publicity(publicity_id)
    except TitlePublicityError as exc:
        return _publicity_error(exc)
    return JsonResponse(
        {
            "data": {
                "id": str(publicity.id),
                "publicityNo": publicity.publicity_no,
                "status": publicity.status,
                "cancelledAt": publicity.cancelled_at.isoformat()
                if publicity.cancelled_at
                else None,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr13.publicity-cancel.1",
        }
    )
