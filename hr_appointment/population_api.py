"""Canonical HR14 batch-population freeze boundary."""

from __future__ import annotations

from django.http import JsonResponse
from django.utils.dateparse import parse_date

from .api import HrAppointmentAccessError, _error, _payload, resolve_request_tenant
from .permissions import MANAGE_PERMISSION
from .services.population_service import AppointmentPopulationError, AppointmentPopulationService


def _status(code: str) -> int:
    if code == "APPOINTMENT_BATCH_NOT_FOUND":
        return 404
    if code in {
        "APPOINTMENT_POPULATION_IDEMPOTENCY_CONFLICT",
        "APPOINTMENT_POPULATION_BATCH_FROZEN",
        "APPOINTMENT_POPULATION_EMPTY",
        "APPOINTMENT_POPULATION_STAFF_AMBIGUOUS",
        "APPOINTMENT_POPULATION_ASSIGNMENT_ORPHAN",
    }:
        return 409
    return 400


def freeze_population(request, batch_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request, required_permission=MANAGE_PERMISSION)
    except HrAppointmentAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _payload(request)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)

    as_of_date = None
    if payload.get("asOfDate") not in (None, ""):
        as_of_date = parse_date(str(payload.get("asOfDate")))
        if as_of_date is None:
            return _error(
                "APPOINTMENT_POPULATION_ASOF_INVALID",
                "asOfDate 必须是 YYYY-MM-DD",
                status=400,
            )
    try:
        snapshot = AppointmentPopulationService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).freeze_from_hr03(batch_id, as_of_date=as_of_date)
    except AppointmentPopulationError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))

    response = JsonResponse(
        {
            "data": {
                "id": str(snapshot.id),
                "batchId": str(snapshot.batch_id),
                "asOfDate": snapshot.as_of_date.isoformat(),
                "snapshotAt": snapshot.snapshot_at.isoformat(),
                "sourceDomain": snapshot.source_domain,
                "sourceVersion": snapshot.source_version,
                "memberCount": snapshot.member_count,
                "contentHash": snapshot.content_hash,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr14.population-snapshot.1",
        }
    )
    response["Cache-Control"] = "no-store"
    return response
