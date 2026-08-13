"""Canonical HTTP authority for HR18 formal submission lifecycle."""

from __future__ import annotations

import uuid

from django.http import JsonResponse

from .api import HrDataAccessError, _error, _payload, resolve_request_tenant
from .services.submission_dispatch_service import (
    SubmissionDispatchError,
    SubmissionDispatchService,
)
from .services.submission_service import SubmissionLifecycleError, SubmissionLifecycleService

SUBMIT_PERMISSION = "hr.data.submit"


def _status(code: str) -> int:
    if code in {"SUBMISSION_NOT_FOUND", "SUBMISSION_ASOF_EVIDENCE_NOT_FOUND"}:
        return 404
    if code in {
        "SUBMISSION_IDEMPOTENCY_CONFLICT",
        "SUBMISSION_INVALID_STATE",
        "SUBMISSION_ASOF_EVIDENCE_MISMATCH",
        "SUBMISSION_ASOF_INCOMPLETE",
        "SUBMISSION_ASYNC_DISPATCH_REQUIRED",
        "SUBMISSION_DISPATCH_REF_MISMATCH",
    }:
        return 409
    if code in {"SUBMISSION_DISPATCH_UNAVAILABLE"}:
        return 503
    if code in {"SUBMISSION_DISPATCH_FAILED"}:
        return 502
    return 400


def _serialize(snapshot):
    dispatch_requested_at = getattr(snapshot, "dispatch_requested_at", None)
    submitted_at = getattr(snapshot, "submitted_at", None)
    parent_submission_id = getattr(snapshot, "parent_submission_id", None)
    return {
        "id": str(snapshot.id),
        "submissionNo": snapshot.submission_no,
        "definitionKind": getattr(snapshot, "definition_kind", "UNKNOWN"),
        "definitionCode": snapshot.definition_code,
        "definitionVersion": snapshot.definition_version,
        "asOfDate": snapshot.as_of_date.isoformat(),
        "scope": snapshot.scope_json,
        "payloadHash": snapshot.payload_hash,
        "status": snapshot.status,
        "dispatchRef": getattr(snapshot, "dispatch_ref", "") or None,
        "dispatchRequestedAt": (
            dispatch_requested_at.isoformat() if dispatch_requested_at else None
        ),
        "dispatchError": getattr(snapshot, "dispatch_error", "") or None,
        "submittedAt": submitted_at.isoformat() if submitted_at else None,
        "receiptRef": getattr(snapshot, "receipt_ref", "") or None,
        "parentSubmissionId": (
            str(parent_submission_id) if parent_submission_id else None
        ),
    }


def _tenant(request):
    return resolve_request_tenant(
        request,
        required_permission=SUBMIT_PERMISSION,
    )


def _service(request):
    tenant_id = _tenant(request)
    return SubmissionLifecycleService(
        tenant_id,
        actor_user_id=getattr(request.user, "id", None),
    )


def create_submission(request):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        service = _service(request)
    except HrDataAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _payload(request)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
    try:
        evidence_id = uuid.UUID(str(payload.get("asOfEvidenceId", "")))
    except (TypeError, ValueError):
        return _error(
            "SUBMISSION_ASOF_EVIDENCE_ID_INVALID",
            "asOfEvidenceId 必须是 UUID",
            status=400,
        )
    try:
        outcome = service.create_draft(
            submission_no=payload.get("submissionNo", ""),
            as_of_evidence_id=evidence_id,
            payload_hash=payload.get("payloadHash", ""),
            scope=payload.get("scope"),
        )
    except SubmissionLifecycleError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))
    response = JsonResponse(
        {
            "data": {**_serialize(outcome.snapshot), "created": outcome.created},
            "apiVersion": "1.0",
            "schemaVersion": "hr18.submission.1",
        },
        status=201 if outcome.created else 200,
    )
    response["Cache-Control"] = "no-store"
    return response


def _transition(request, submission_id, method_name):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        service = _service(request)
    except HrDataAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        snapshot = getattr(service, method_name)(submission_id)
    except SubmissionLifecycleError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))
    response = JsonResponse(
        {
            "data": _serialize(snapshot),
            "apiVersion": "1.0",
            "schemaVersion": "hr18.submission.1",
        }
    )
    response["Cache-Control"] = "no-store"
    return response


def validate_submission(request, submission_id):
    return _transition(request, submission_id, "validate")


def approve_submission(request, submission_id):
    return _transition(request, submission_id, "approve")


def submit_submission(request, submission_id):
    """Queue async dispatch; never mark SUBMITTED in the request thread."""
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = _tenant(request)
    except HrDataAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        result = SubmissionDispatchService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).queue(submission_id)
    except SubmissionDispatchError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))
    dispatch_error = getattr(result, "error", "")
    if dispatch_error:
        return _error(
            "SUBMISSION_DISPATCH_FAILED",
            dispatch_error,
            status=502,
        )
    response = JsonResponse(
        {
            "data": {
                **_serialize(result.snapshot),
                "queued": result.queued,
                "dispatchRef": result.dispatch_ref,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr18.submission-dispatch.1",
        },
        status=202,
    )
    response["Cache-Control"] = "no-store"
    return response


def record_receipt(request, submission_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        service = _service(request)
    except HrDataAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _payload(request)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
    accepted = payload.get("accepted")
    if not isinstance(accepted, bool):
        return _error(
            "SUBMISSION_RECEIPT_ACCEPTED_INVALID",
            "accepted 必须是布尔值",
            status=400,
        )
    try:
        snapshot = service.record_receipt(
            submission_id,
            accepted=accepted,
            receipt_ref=payload.get("receiptRef", ""),
        )
    except SubmissionLifecycleError as exc:
        return _error(exc.code, str(exc), status=_status(exc.code))
    response = JsonResponse(
        {
            "data": _serialize(snapshot),
            "apiVersion": "1.0",
            "schemaVersion": "hr18.submission.1",
        }
    )
    response["Cache-Control"] = "no-store"
    return response
