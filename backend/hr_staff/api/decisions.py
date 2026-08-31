"""HR03 formal personnel-decision Authority APIs.

All writes delegate to ``PersonnelAuthorityService``.  The API never exposes an
in-place edit or delete route; corrections and revocations append successors.
"""

from __future__ import annotations

import json

from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.http import require_GET, require_POST

from hr_staff.api.base import api_root, error_response, json_response, make_staff_context
from hr_staff.context import HrStaffContextError
from hr_staff.models import HrPersonnelDecision
from hr_staff.permissions import require_hr_staff_permission
from hr_staff.services.decision_service import (
    PersonnelAuthorityError,
    PersonnelAuthorityService,
)

SCHEMA_VERSION = "hr03.personnel-decision.2"


def _body(request):
    try:
        value = json.loads(request.body or b"{}")
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _date(value):
    return parse_date(value) if isinstance(value, str) else value


def _datetime(value):
    return parse_datetime(value) if isinstance(value, str) else value


def _serialize(row: HrPersonnelDecision):
    return {
        "id": str(row.id),
        "decisionNo": row.decision_no,
        "staffId": str(row.staff_id),
        "decisionType": row.decision_type,
        "decisionAction": row.decision_action,
        "title": row.title,
        "basisText": row.basis_text,
        "contentSnapshot": row.content_snapshot_json,
        "decidedAt": row.decided_at.isoformat(),
        "effectiveFrom": row.effective_from.isoformat(),
        "effectiveTo": row.effective_to.isoformat() if row.effective_to else None,
        "supersedesDecisionId": (
            str(row.supersedes_decision_id) if row.supersedes_decision_id else None
        ),
        "correctionReason": row.correction_reason,
        "correctionEvidenceRef": row.correction_evidence_ref,
        "sealedAt": row.sealed_at.isoformat(),
        "contentHash": row.content_hash,
    }


def _context_or_error(request):
    try:
        return make_staff_context(request), None
    except HrStaffContextError as exc:
        return None, error_response(request, exc.code, exc.message, status=403)


def _service_error(request, exc: PersonnelAuthorityError):
    if exc.code in {"STAFF_NOT_FOUND", "PERSONNEL_DECISION_NOT_FOUND"}:
        status = 404
    elif exc.code.endswith("CONFLICT") or exc.code.endswith("SUPERSEDED"):
        status = 409
    else:
        status = 400
    return error_response(request, exc.code, str(exc), status=status)


@require_GET
@require_hr_staff_permission("hr.staff.personnel_decision.view")
def personnel_decisions(request, staff_id):
    context, error = _context_or_error(request)
    if error:
        return error
    try:
        rows = PersonnelAuthorityService(context.tenant_id).effective_decisions(
            staff_id=staff_id,
            as_of=context.as_of,
        )
    except PersonnelAuthorityError as exc:
        return _service_error(request, exc)
    payload = api_root(request)
    payload["schemaVersion"] = SCHEMA_VERSION
    payload["data"] = [_serialize(row) for row in rows]
    return json_response(request, payload)


@require_POST
@require_hr_staff_permission("hr.staff.personnel_decision.manage")
def create_personnel_decision(request, staff_id):
    context, error = _context_or_error(request)
    if error:
        return error
    body = _body(request)
    if body is None:
        return error_response(request, "INVALID_REQUEST", "请求体不是合法 JSON", 400)
    try:
        row = PersonnelAuthorityService(
            context.tenant_id,
            actor_user_id=request.user.id,
            correlation_id=body.get("correlationId", ""),
        ).create_effective_decision(
            decision_no=body.get("decisionNo", ""),
            staff_id=staff_id,
            decision_type=body.get("decisionType", ""),
            title=body.get("title", ""),
            basis_text=body.get("basisText", ""),
            content_snapshot=body.get("contentSnapshot") or {},
            decided_at=_datetime(body.get("decidedAt")),
            effective_from=_date(body.get("effectiveFrom")),
            effective_to=_date(body.get("effectiveTo")),
            source_business_type=body.get("sourceBusinessType", ""),
            source_business_id=body.get("sourceBusinessId", ""),
        )
    except PersonnelAuthorityError as exc:
        return _service_error(request, exc)
    payload = api_root(request)
    payload["schemaVersion"] = SCHEMA_VERSION
    payload["data"] = _serialize(row)
    return json_response(request, payload, status=201)


@require_POST
@require_hr_staff_permission("hr.staff.personnel_decision.correct")
def correct_personnel_decision(request, decision_id):
    context, error = _context_or_error(request)
    if error:
        return error
    body = _body(request)
    if body is None:
        return error_response(request, "INVALID_REQUEST", "请求体不是合法 JSON", 400)
    try:
        row = PersonnelAuthorityService(
            context.tenant_id,
            actor_user_id=request.user.id,
            correlation_id=body.get("correlationId", ""),
        ).correct_effective_decision(
            prior_decision_id=decision_id,
            decision_no=body.get("decisionNo", ""),
            title=body.get("title", ""),
            basis_text=body.get("basisText", ""),
            content_snapshot=body.get("contentSnapshot") or {},
            decided_at=_datetime(body.get("decidedAt")),
            effective_from=_date(body.get("effectiveFrom")),
            effective_to=_date(body.get("effectiveTo")),
            correction_reason=body.get("correctionReason", ""),
            correction_evidence_ref=body.get("correctionEvidenceRef", ""),
        )
    except PersonnelAuthorityError as exc:
        return _service_error(request, exc)
    payload = api_root(request)
    payload["schemaVersion"] = SCHEMA_VERSION
    payload["data"] = _serialize(row)
    return json_response(request, payload, status=201)


@require_POST
@require_hr_staff_permission("hr.staff.personnel_decision.revoke")
def revoke_personnel_decision(request, decision_id):
    context, error = _context_or_error(request)
    if error:
        return error
    body = _body(request)
    if body is None:
        return error_response(request, "INVALID_REQUEST", "请求体不是合法 JSON", 400)
    try:
        row = PersonnelAuthorityService(
            context.tenant_id,
            actor_user_id=request.user.id,
            correlation_id=body.get("correlationId", ""),
        ).revoke_effective_decision(
            prior_decision_id=decision_id,
            decision_no=body.get("decisionNo", ""),
            title=body.get("title", ""),
            decided_at=_datetime(body.get("decidedAt")),
            effective_from=_date(body.get("effectiveFrom")),
            correction_reason=body.get("correctionReason", ""),
            correction_evidence_ref=body.get("correctionEvidenceRef", ""),
        )
    except PersonnelAuthorityError as exc:
        return _service_error(request, exc)
    payload = api_root(request)
    payload["schemaVersion"] = SCHEMA_VERSION
    payload["data"] = _serialize(row)
    return json_response(request, payload, status=201)
