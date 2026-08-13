"""Canonical API for HR13 professional-title workflows."""

from __future__ import annotations

import json

from django.http import JsonResponse
from django.utils import timezone

from base.auth_backends import get_allowed_company_ids
from hr_control_center.context import resolve_tenant_from_request

from .selectors import dashboard_snapshot
from .services.qualification_service import (
    TitleQualificationError,
    TitleQualificationService,
)

READ_PERMISSION = "hr.title.view"
REVIEW_PERMISSION = "hr.title.review"


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
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _error("INVALID_JSON", "请求体必须是合法 JSON", status=400)
    if not isinstance(payload, dict):
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)

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
