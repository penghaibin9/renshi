"""Canonical HTTP authority for HR14 collective final decisions."""

from django.http import JsonResponse

from hr_appointment.api import (
    HrAppointmentAccessError,
    _error,
    _payload,
    resolve_request_tenant,
)
from hr_appointment.services.decision_service import (
    AppointmentDecisionError,
    AppointmentDecisionService,
)

DECISION_PERMISSION = "hr.appointment.decision"


def _status(code: str) -> int:
    if code in {"APPOINTMENT_CASE_NOT_FOUND"}:
        return 404
    if code in {
        "APPOINTMENT_DECISION_IDEMPOTENCY_CONFLICT",
        "APPOINTMENT_DECISION_ALREADY_RECORDED",
        "APPOINTMENT_DECISION_INVALID_CASE_STATE",
        "APPOINTMENT_PUBLICITY_NOT_CLOSED",
        "APPOINTMENT_PUBLICITY_OBJECTION_BLOCKS_EFFECT",
    }:
        return 409
    return 400


def record_collective_decision(request, case_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(
            request, required_permission=DECISION_PERMISSION
        )
    except HrAppointmentAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _payload(request)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)

    try:
        decision, created = AppointmentDecisionService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).record(
            case_id=case_id,
            decision_no=payload.get("decisionNo", ""),
            outcome=payload.get("outcome", ""),
            authority_ref=payload.get("authorityRef", ""),
            decision_reason=payload.get("decisionReason", ""),
            evidence_snapshot=payload.get("evidenceSnapshot"),
        )
    except AppointmentDecisionError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))

    response = JsonResponse(
        {
            "data": {
                "id": str(decision.id),
                "decisionNo": decision.decision_no,
                "applicationCaseId": str(decision.application_case_id),
                "publicityId": str(decision.publicity_id),
                "batchNo": decision.batch_no,
                "personId": str(decision.person_id),
                "positionInstanceId": decision.position_instance_id,
                "outcome": decision.outcome,
                "authorityRef": decision.authority_ref,
                "decisionReason": decision.decision_reason,
                "decidedAt": decision.decided_at.isoformat(),
                "created": created,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr14.collective-decision.1",
        },
        status=201 if created else 200,
    )
    response["Cache-Control"] = "no-store"
    return response
