"""Canonical HTTP execution boundary for HR16 non-core saga participants."""

from __future__ import annotations

from django.http import JsonResponse

from .api import (
    EFFECT_PERMISSION,
    HrExitAccessError,
    _error,
    resolve_request_tenant,
)
from .services.participant_service import ExitParticipantError, ExitParticipantService


def _status(code: str) -> int:
    if code in {"EXIT_EFFECT_NOT_FOUND", "EXIT_CASE_NOT_FOUND"}:
        return 404
    if code in {
        "EXIT_EFFECT_PARTICIPANT_NOT_REQUIRED",
        "EXIT_EFFECT_CORE_NOT_EFFECTIVE",
    }:
        return 409
    return 400


def _serialize(result):
    return {
        "effectId": str(result.effect.id),
        "participant": result.participant,
        "participantStatus": result.status,
        "effectStatus": result.effect.status,
        "receipt": dict(result.receipt or {}),
        "error": result.error,
    }


def execute_participant(request, effect_id, participant):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(
            request, required_permission=EFFECT_PERMISSION
        )
    except HrExitAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        result = ExitParticipantService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).execute(effect_id=effect_id, participant=participant)
    except ExitParticipantError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))
    response = JsonResponse(
        {
            "data": _serialize(result),
            "apiVersion": "1.0",
            "schemaVersion": "hr16.exit-participant.1",
        },
        status=200 if result.status == "SUCCESS" else 202,
    )
    response["Cache-Control"] = "no-store"
    return response


def reconcile_participants(request, effect_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(
            request, required_permission=EFFECT_PERMISSION
        )
    except HrExitAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        results = ExitParticipantService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).reconcile(effect_id=effect_id)
    except ExitParticipantError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))
    all_success = all(result.status == "SUCCESS" for result in results)
    response = JsonResponse(
        {
            "data": [_serialize(result) for result in results],
            "apiVersion": "1.0",
            "schemaVersion": "hr16.exit-participant.1",
        },
        status=200 if all_success else 202,
        safe=True,
    )
    response["Cache-Control"] = "no-store"
    return response
