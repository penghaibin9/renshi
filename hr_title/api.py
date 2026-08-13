"""Canonical API for HR13 professional-title workflows."""

from __future__ import annotations

import json

from django.http import JsonResponse
from django.utils import timezone

from base.auth_backends import get_allowed_company_ids
from hr_control_center.context import resolve_tenant_from_request

from .selectors import dashboard_snapshot
from .services.panel_service import TitlePanelError, TitlePanelService
from .services.qualification_service import (
    TitleQualificationError,
    TitleQualificationService,
)

READ_PERMISSION = "hr.title.view"
REVIEW_PERMISSION = "hr.title.review"
PANEL_PERMISSION = "hr.title.panel"


class HrTitleAccessError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def resolve_request_tenant(request, *, required_permission: str = READ_PERMISSION) -> int:
    if not getattr(request.user, "is_authenticated", False):
        raise HrTitleAccessError("AUTHENTICATION_REQUIRED", "authentication required")
    tenant_id = resolve_tenant_from_request(request)
    if not tenant_id:
        raise HrTitleAccessError("TENANT_CONTEXT_REQUIRED", "请选择当前学校")
    tenant_id = int(tenant_id)
    if not request.user.is_superuser:
        allowed = {int(x) for x in get_allowed_company_ids(request.user)}
        if tenant_id not in allowed:
            raise HrTitleAccessError("TENANT_ACCESS_DENIED", "当前账号无权访问该学校")
        if not request.user.has_perm(required_permission):
            raise HrTitleAccessError(
                "PERMISSION_DENIED", f"缺少权限: {required_permission}"
            )
    return tenant_id


def _error(code: str, message: str = "", *, status: int) -> JsonResponse:
    response = JsonResponse({"error": {"code": code, "message": message}}, status=status)
    response["Cache-Control"] = "no-store"
    return response


def _json_payload(request):
    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("INVALID_JSON")
    if not isinstance(payload, dict):
        raise ValueError("INVALID_JSON")
    return payload


def _panel_error(exc: TitlePanelError) -> JsonResponse:
    if exc.code in {
        "TITLE_CASE_NOT_FOUND",
        "TITLE_REVIEW_ROUND_NOT_FOUND",
        "TITLE_REVIEW_ASSIGNMENT_NOT_FOUND",
    }:
        status = 404
    elif exc.code in {
        "TITLE_REVIEW_ROUND_IDEMPOTENCY_CONFLICT",
        "TITLE_REVIEW_ASSIGNMENT_IDEMPOTENCY_CONFLICT",
        "TITLE_REVIEW_BALLOT_IDEMPOTENCY_CONFLICT",
        "TITLE_REVIEW_INVALID_CASE_STATE",
        "TITLE_REVIEW_OPEN_ROUND_EXISTS",
        "TITLE_REVIEW_ROUND_NOT_OPEN",
        "TITLE_REVIEW_REVIEWER_DUPLICATE",
        "TITLE_REVIEW_ASSIGNMENT_ALREADY_RESPONDED",
        "TITLE_REVIEW_ASSIGNMENT_NOT_ELIGIBLE",
        "TITLE_REVIEW_BALLOT_ALREADY_SUBMITTED",
        "TITLE_REVIEW_QUORUM_NOT_MET",
    }:
        status = 409
    else:
        status = 400
    return _error(exc.code, str(exc), status=status)


def dashboard(request):
    if request.method != "GET":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request)
    except HrTitleAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    payload = dashboard_snapshot(tenant_id)
    payload.update(
        {
            "apiVersion": "1.0",
            "schemaVersion": "hr13.workspace.1",
            "generatedAt": timezone.now().isoformat(),
        }
    )
    response = JsonResponse(payload)
    response["Cache-Control"] = "no-store"
    return response


def qualification_decision(request, case_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(
            request, required_permission=REVIEW_PERMISSION
        )
    except HrTitleAccessError as exc:
        return _error(exc.code, exc.message, status=403)

    try:
        payload = _json_payload(request)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是合法 JSON 对象", status=400)

    try:
        outcome = TitleQualificationService(
            tenant_id,
            actor_user_id=getattr(request.user, "id", None),
        ).decide(
            case_id=case_id,
            decision_no=payload.get("decisionNo", ""),
            decision=payload.get("decision", ""),
            reason_code=payload.get("reasonCode", ""),
            reason=payload.get("reason", ""),
        )
    except TitleQualificationError as exc:
        if exc.code == "TITLE_CASE_NOT_FOUND":
            status = 404
        elif exc.code in {
            "TITLE_QUALIFICATION_IDEMPOTENCY_CONFLICT",
            "TITLE_QUALIFICATION_INVALID_STATE",
        }:
            status = 409
        else:
            status = 400
        return _error(exc.code, str(exc), status=status)

    decision = outcome.decision
    response = JsonResponse(
        {
            "data": {
                "id": str(decision.id),
                "decisionNo": decision.decision_no,
                "applicationCaseId": str(decision.application_case_id),
                "attemptNo": decision.attempt_no,
                "decision": decision.decision,
                "reasonCode": decision.reason_code,
                "reason": decision.reason,
                "caseStatus": outcome.case.status,
                "created": outcome.created,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr13.qualification-decision.1",
        },
        status=201 if outcome.created else 200,
    )
    response["Cache-Control"] = "no-store"
    return response


def open_review_round(request, case_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request, required_permission=PANEL_PERMISSION)
    except HrTitleAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _json_payload(request)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是合法 JSON 对象", status=400)
    try:
        review_round = TitlePanelService(
            tenant_id, actor_user_id=getattr(request.user, "id", None)
        ).open_round(
            case_id=case_id,
            round_no=payload.get("roundNo", ""),
            required_ballots=payload.get("requiredBallots"),
            required_pass_votes=payload.get("requiredPassVotes"),
        )
    except TitlePanelError as exc:
        return _panel_error(exc)
    response = JsonResponse(
        {
            "data": {
                "id": str(review_round.id),
                "roundNo": review_round.round_no,
                "applicationCaseId": str(review_round.application_case_id),
                "attemptNo": review_round.attempt_no,
                "requiredBallots": review_round.required_ballots,
                "requiredPassVotes": review_round.required_pass_votes,
                "status": review_round.status,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr13.review-round.1",
        },
        status=201,
    )
    response["Cache-Control"] = "no-store"
    return response


def create_review_assignment(request, round_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request, required_permission=PANEL_PERMISSION)
    except HrTitleAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _json_payload(request)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是合法 JSON 对象", status=400)
    try:
        assignment = TitlePanelService(
            tenant_id, actor_user_id=getattr(request.user, "id", None)
        ).assign_reviewer(
            round_id=round_id,
            assignment_no=payload.get("assignmentNo", ""),
            reviewer_staff_id=payload.get("reviewerStaffId"),
            reviewer_role=payload.get("reviewerRole", "EXPERT"),
        )
    except TitlePanelError as exc:
        return _panel_error(exc)
    response = JsonResponse(
        {
            "data": {
                "id": str(assignment.id),
                "assignmentNo": assignment.assignment_no,
                "reviewRoundId": str(assignment.review_round_id),
                "reviewerStaffId": str(assignment.reviewer_staff_id),
                "reviewerRole": assignment.reviewer_role,
                "status": assignment.status,
                "conflictDeclared": assignment.conflict_declared,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr13.review-assignment.1",
        },
        status=201,
    )
    response["Cache-Control"] = "no-store"
    return response


def respond_review_assignment(request, assignment_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request, required_permission=PANEL_PERMISSION)
    except HrTitleAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _json_payload(request)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是合法 JSON 对象", status=400)
    try:
        assignment = TitlePanelService(
            tenant_id, actor_user_id=getattr(request.user, "id", None)
        ).respond_assignment(
            assignment_id,
            accept=bool(payload.get("accept", False)),
            conflict_declared=bool(payload.get("conflictDeclared", False)),
            conflict_note=payload.get("conflictNote", ""),
        )
    except TitlePanelError as exc:
        return _panel_error(exc)
    responded_at = getattr(assignment, "responded_at", None)
    response = JsonResponse(
        {
            "data": {
                "id": str(assignment.id),
                "status": assignment.status,
                "conflictDeclared": assignment.conflict_declared,
                "conflictNote": assignment.conflict_note,
                "respondedAt": responded_at.isoformat() if responded_at else None,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr13.review-assignment-response.1",
        }
    )
    response["Cache-Control"] = "no-store"
    return response


def submit_review_ballot(request, assignment_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request, required_permission=PANEL_PERMISSION)
    except HrTitleAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        payload = _json_payload(request)
    except ValueError:
        return _error("INVALID_JSON", "请求体必须是合法 JSON 对象", status=400)
    try:
        ballot = TitlePanelService(
            tenant_id, actor_user_id=getattr(request.user, "id", None)
        ).submit_ballot(
            assignment_id=assignment_id,
            ballot_no=payload.get("ballotNo", ""),
            recommendation=payload.get("recommendation", ""),
            score=payload.get("score"),
            rationale=payload.get("rationale", ""),
        )
    except TitlePanelError as exc:
        return _panel_error(exc)
    response = JsonResponse(
        {
            "data": {
                "id": str(ballot.id),
                "ballotNo": ballot.ballot_no,
                "reviewRoundId": str(ballot.review_round_id),
                "assignmentId": str(ballot.assignment_id),
                "recommendation": ballot.recommendation,
                "score": str(ballot.score) if ballot.score is not None else None,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr13.review-ballot.1",
        },
        status=201,
    )
    response["Cache-Control"] = "no-store"
    return response


def close_review_round(request, round_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request, required_permission=PANEL_PERMISSION)
    except HrTitleAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        outcome = TitlePanelService(
            tenant_id, actor_user_id=getattr(request.user, "id", None)
        ).close_round(round_id)
    except TitlePanelError as exc:
        return _panel_error(exc)
    response = JsonResponse(
        {
            "data": {
                "id": str(outcome.round.id),
                "roundNo": outcome.round.round_no,
                "status": outcome.round.status,
                "caseStatus": outcome.case.status,
                "ballots": outcome.ballots,
                "passVotes": outcome.pass_votes,
                "failVotes": outcome.fail_votes,
                "abstentions": outcome.abstentions,
                "closureSnapshot": outcome.round.closure_snapshot_json,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr13.review-round-close.1",
        }
    )
    response["Cache-Control"] = "no-store"
    return response
