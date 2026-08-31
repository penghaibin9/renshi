"""Canonical HTTP authority for HR14 competition-batch lifecycle."""

from __future__ import annotations

from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .api import HrAppointmentAccessError, _error, _payload, resolve_request_tenant
from .permissions import MANAGE_PERMISSION
from .services.batch_service import (
    AppointmentBatchError,
    AppointmentBatchInput,
    AppointmentBatchService,
)


def _optional_datetime(value, *, field: str):
    if value in (None, ""):
        return None
    parsed = parse_datetime(str(value))
    if parsed is None:
        raise ValueError(field)
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _status(code: str) -> int:
    if code in {"APPOINTMENT_BATCH_NOT_FOUND", "APPOINTMENT_POLICY_NOT_FOUND"}:
        return 404
    if code in {
        "APPOINTMENT_BATCH_NO_CONFLICT",
        "APPOINTMENT_BATCH_INVALID_STATE",
        "APPOINTMENT_BATCH_POPULATION_REQUIRED",
        "APPOINTMENT_BATCH_SUPPLY_REQUIRED",
        "APPOINTMENT_BATCH_SUPPLY_TARGET_MISMATCH",
        "APPOINTMENT_BATCH_QUOTA_REQUIRED",
        "APPOINTMENT_BATCH_QUOTA_EMPTY",
        "APPOINTMENT_APPLICATION_WINDOW_REQUIRED",
        "APPOINTMENT_PUBLICITY_WINDOW_REQUIRED",
        "APPOINTMENT_APPLICATION_WINDOW_NOT_STARTED",
        "APPOINTMENT_APPLICATION_WINDOW_ENDED",
        "APPOINTMENT_ELIGIBILITY_INCOMPLETE",
    }:
        return 409
    return 400


def _serialize(batch):
    return {
        "id": str(batch.id),
        "batchNo": batch.batch_no,
        "name": batch.name,
        "businessType": batch.business_type,
        "policyVersionId": str(batch.policy_version_id),
        "targetCategories": batch.target_categories_json,
        "targetLevels": batch.target_levels_json,
        "applicationFrom": batch.application_from.isoformat() if batch.application_from else None,
        "applicationTo": batch.application_to.isoformat() if batch.application_to else None,
        "publicityFrom": batch.publicity_from.isoformat() if batch.publicity_from else None,
        "publicityTo": batch.publicity_to.isoformat() if batch.publicity_to else None,
        "versionNo": batch.version_no,
        "contentHash": batch.content_hash,
        "status": batch.status,
    }


def _service(request):
    tenant_id = resolve_request_tenant(request, required_permission=MANAGE_PERMISSION)
    return AppointmentBatchService(
        tenant_id,
        actor_user_id=getattr(request.user, "id", None),
    )


def create_batch(request):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        service = _service(request)
    except HrAppointmentAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _payload(request)
        application_from = _optional_datetime(
            payload.get("applicationFrom"), field="applicationFrom"
        )
        application_to = _optional_datetime(
            payload.get("applicationTo"), field="applicationTo"
        )
        publicity_from = _optional_datetime(
            payload.get("publicityFrom"), field="publicityFrom"
        )
        publicity_to = _optional_datetime(
            payload.get("publicityTo"), field="publicityTo"
        )
    except ValueError as exc:
        field = str(exc)
        if field == "INVALID_JSON":
            return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
        return _error("INVALID_DATETIME", f"{field} 必须是 ISO-8601 时间", status=400)
    try:
        batch = service.create_draft(
            AppointmentBatchInput(
                batch_no=payload.get("batchNo", ""),
                name=payload.get("name", ""),
                policy_version_id=payload.get("policyVersionId"),
                business_type=payload.get(
                    "businessType", "COMPETITIVE_APPOINTMENT"
                ),
                target_categories=payload.get("targetCategories") or (),
                target_levels=payload.get("targetLevels") or (),
                application_from=application_from,
                application_to=application_to,
                publicity_from=publicity_from,
                publicity_to=publicity_to,
            )
        )
    except AppointmentBatchError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))
    response = JsonResponse(
        {
            "data": _serialize(batch),
            "apiVersion": "1.0",
            "schemaVersion": "hr14.batch.2",
        },
        status=201,
    )
    response["Cache-Control"] = "no-store"
    response["ETag"] = f'"hr14-batch-v{batch.version_no}"'
    return response


def _transition(request, batch_id, method_name):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        service = _service(request)
    except HrAppointmentAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        batch = getattr(service, method_name)(batch_id)
    except AppointmentBatchError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))
    response = JsonResponse(
        {
            "data": _serialize(batch),
            "apiVersion": "1.0",
            "schemaVersion": "hr14.batch.2",
        }
    )
    response["Cache-Control"] = "no-store"
    response["ETag"] = f'"hr14-batch-v{batch.version_no}"'
    return response


def publish_batch(request, batch_id):
    return _transition(request, batch_id, "publish")


def open_applications(request, batch_id):
    return _transition(request, batch_id, "open_applications")


def close_applications(request, batch_id):
    return _transition(request, batch_id, "close_applications")


def begin_eligibility_review(request, batch_id):
    return _transition(request, batch_id, "begin_eligibility_review")


def begin_review(request, batch_id):
    return _transition(request, batch_id, "begin_review")
