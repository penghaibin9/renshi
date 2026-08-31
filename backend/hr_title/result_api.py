"""Canonical HTTP authority for HR13 formal professional-title results."""

from __future__ import annotations

from django.http import JsonResponse
from django.utils.dateparse import parse_date

from .api import HrTitleAccessError, _error, _json_payload, resolve_request_tenant
from .services.result_service import (
    ProfessionalTitleResultService,
    TitleResultError,
    TitleResultInput,
    TitleResultPublicationInput,
)

RESULT_PERMISSION = "hr.title.result"
RESULT_CORRECT_PERMISSION = "hr.title.result.correct"


def _date(value, field_name: str, *, required=True):
    if value in (None, ""):
        if required:
            raise ValueError(f"{field_name} is required in YYYY-MM-DD format")
        return None
    parsed = parse_date(str(value).strip())
    if parsed is None:
        raise ValueError(f"{field_name} must be YYYY-MM-DD")
    return parsed


def _status(code: str) -> int:
    if code in {"TITLE_CASE_NOT_FOUND", "TITLE_RESULT_NOT_FOUND"}:
        return 404
    if code in {
        "TITLE_RESULT_IDEMPOTENCY_CONFLICT",
        "TITLE_RESULT_ALREADY_EXISTS",
        "TITLE_RESULT_ALREADY_SUPERSEDED",
        "TITLE_RESULT_REVOKED",
        "TITLE_CASE_INVALID_STATE",
        "TITLE_PUBLICITY_REQUIRED",
        "TITLE_PUBLICITY_NOT_CLOSED",
        "TITLE_APPEALS_PENDING",
        "TITLE_APPEAL_UPHELD",
        "TITLE_RESULT_REVISION_DATE_INVALID",
        "TITLE_RESULT_REVOCATION_DATE_INVALID",
        "TITLE_RESULT_CASE_MISMATCH",
        "TITLE_RESULT_POLICY_NOT_FOUND",
        "TITLE_RESULT_POLICY_NOT_PUBLISHED",
        "TITLE_RESULT_POLICY_HASH_INVALID",
        "TITLE_RESULT_POLICY_NOT_EFFECTIVE",
        "TITLE_RESULT_POLICY_TITLE_IDENTITY_MISSING",
        "TITLE_RESULT_TITLE_IDENTITY_MISSING",
        "TITLE_RESULT_PASSED_REVIEW_REQUIRED",
        "TITLE_RESULT_REVIEW_RULE_MISMATCH",
        "TITLE_RESULT_REVIEW_EVIDENCE_INCONSISTENT",
        "TITLE_RESULT_REVIEW_DECISION_INVALID",
        "TITLE_RESULT_REVIEW_SNAPSHOT_INVALID",
    }:
        return 409
    return 400


def _serialize(result):
    return {
        "id": str(result.id),
        "resultNo": result.result_no,
        "personId": str(result.person_id),
        "applicationCaseId": str(result.application_case_id),
        "titleCode": result.title_code,
        "titleName": result.title_name,
        "titleSeriesCode": result.title_series_code,
        "titleLevelCode": result.title_level_code,
        "effectiveFrom": result.effective_from.isoformat(),
        "effectiveTo": result.effective_to.isoformat() if result.effective_to else None,
        "status": result.status,
        "supersedesResultId": (
            str(result.supersedes_result_id) if result.supersedes_result_id else None
        ),
        "contentHash": result.content_hash,
        "sealedAt": result.sealed_at.isoformat(),
        "authoritySnapshot": result.authority_snapshot_json,
    }


def _service(request, *, permission=RESULT_PERMISSION):
    tenant_id = resolve_request_tenant(request, required_permission=permission)
    return ProfessionalTitleResultService(
        tenant_id,
        actor_user_id=getattr(request.user, "id", None),
    )


def _payload_input(payload) -> TitleResultInput:
    forbidden = sorted(_FORBIDDEN_RESULT_METRICS.intersection(payload))
    if forbidden:
        raise ValueError(
            "calculated result fields are server-owned and must not be submitted: "
            + ", ".join(forbidden)
        )
    return TitleResultInput(
        result_no=payload.get("resultNo", ""),
        title_code=payload.get("titleCode", ""),
        title_name=payload.get("titleName", ""),
        title_series_code=payload.get("titleSeriesCode", ""),
        title_level_code=payload.get("titleLevelCode", ""),
        effective_from=_date(payload.get("effectiveFrom"), "effectiveFrom"),
        effective_to=_date(
            payload.get("effectiveTo"),
            "effectiveTo",
            required=False,
        ),
    )


_FORBIDDEN_RESULT_METRICS = frozenset(
    {
        "totalScore",
        "score",
        "rank",
        "outcome",
        "decision",
        "passed",
        "certificateSnapshot",
        "appointmentSnapshot",
        "authoritySnapshot",
        "snapshot",
    }
)

_FORBIDDEN_PUBLICATION_FIELDS = _FORBIDDEN_RESULT_METRICS | frozenset(
    {"titleCode", "titleName", "titleSeriesCode", "titleLevelCode"}
)


def _publication_input(payload) -> TitleResultPublicationInput:
    forbidden = sorted(_FORBIDDEN_PUBLICATION_FIELDS.intersection(payload))
    if forbidden:
        raise ValueError(
            "authoritative result fields are server-derived and must not be submitted: "
            + ", ".join(forbidden)
        )
    return TitleResultPublicationInput(
        result_no=payload.get("resultNo", ""),
        effective_from=_date(payload.get("effectiveFrom"), "effectiveFrom"),
        effective_to=_date(
            payload.get("effectiveTo"),
            "effectiveTo",
            required=False,
        ),
    )


def make_effective(request, case_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        service = _service(request)
    except HrTitleAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _json_payload(request)
        result_input = _publication_input(payload)
    except ValueError as exc:
        return _error("INVALID_REQUEST", str(exc), status=400)
    try:
        result = service.make_effective(
            application_case_id=case_id,
            payload=result_input,
        )
    except TitleResultError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))
    response = JsonResponse(
        {
            "data": _serialize(result),
            "apiVersion": "1.0",
            "schemaVersion": "hr13.title-result.1",
        },
        status=200,
    )
    response["Cache-Control"] = "no-store"
    return response


def revise_result(request, result_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        service = _service(request, permission=RESULT_CORRECT_PERMISSION)
    except HrTitleAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _json_payload(request)
        result_input = _payload_input(payload)
    except ValueError as exc:
        return _error("INVALID_REQUEST", str(exc), status=400)
    try:
        result = service.revise(result_id=result_id, payload=result_input)
    except TitleResultError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))
    response = JsonResponse(
        {
            "data": _serialize(result),
            "apiVersion": "1.0",
            "schemaVersion": "hr13.title-result.1",
        }
    )
    response["Cache-Control"] = "no-store"
    return response


def revoke_result(request, result_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        service = _service(request, permission=RESULT_CORRECT_PERMISSION)
    except HrTitleAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _json_payload(request)
        revoked_at = _date(payload.get("revokedAt"), "revokedAt")
    except ValueError as exc:
        return _error("INVALID_REQUEST", str(exc), status=400)
    try:
        result = service.revoke(
            result_id=result_id,
            result_no=payload.get("resultNo", ""),
            revoked_at=revoked_at,
        )
    except TitleResultError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))
    response = JsonResponse(
        {
            "data": _serialize(result),
            "apiVersion": "1.0",
            "schemaVersion": "hr13.title-result.1",
        }
    )
    response["Cache-Control"] = "no-store"
    return response
