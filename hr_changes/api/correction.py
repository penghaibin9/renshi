"""
hr_changes/api/correction.py —— 异动纠错 API（S7，高权限 hr.change.correct）。

POST /api/hr/v1/changes/{case_id}/corrections           发起纠错
POST /api/hr/v1/corrections/{id}/submit | approve | reject | apply
"""

from __future__ import annotations

import json

from django.views.decorators.http import require_http_methods

from hr_changes.api.base import (
    api_root,
    error_response,
    json_response,
    make_hr_change_context,
)
from hr_changes.api.changes import _service_error
from hr_changes.context import HrChangeContextError
from hr_changes.permissions import require_hr_change_permission
from hr_changes.services.change_service import ChangeServiceError
from hr_changes.services.correction_service import CorrectionService, CorrectionServiceError


def _context(request):
    try:
        return make_hr_change_context(request), None
    except HrChangeContextError as exc:
        return None, error_response(request, exc.code, exc.message, status=403)


def _body(request):
    raw = request.body
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        raise ChangeServiceError("CHANGE_INVALID_PAYLOAD", "请求体不是合法 JSON")


def _svc(request, ctx):
    return CorrectionService(ctx.tenant_id, actor_user_id=request.user.id)


def _correction_payload(correction):
    return {
        "id": str(correction.id),
        "caseId": str(correction.change_case_id_id),
        "correctionType": correction.correction_type,
        "requestedValues": correction.requested_values_json,
        "reason": correction.reason,
        "status": correction.status,
        "previousSnapshotHash": correction.previous_snapshot_hash,
        "newSnapshotHash": correction.new_snapshot_hash,
        "authorityVersion": correction.authority_version,
        "providerCode": correction.provider_code,
        "providerCaseId": str(correction.provider_case_id) if correction.provider_case_id else None,
        "providerCaseVersion": correction.provider_case_version,
        "appliedFields": correction.applied_fields_json,
        "applyError": correction.apply_error,
        "version": correction.version,
    }


def _version(request, body):
    raw = request.headers.get("If-Match") or body.get("version")
    if raw in (None, ""):
        return None
    try:
        return int(str(raw).strip().strip('"'))
    except (TypeError, ValueError):
        raise ChangeServiceError("VERSION_INVALID", "If-Match/version 必须是整数") from None


@require_http_methods(["POST"])
@require_hr_change_permission("hr.change.correct")
def create_correction(request, case_id):
    ctx, err = _context(request)
    if err:
        return err
    try:
        body = _body(request)
        correction = _svc(request, ctx).create_correction(
            case_id=case_id,
            correction_type=body.get("correctionType", "TARGET_VALUE"),
            requested_values=body.get("requestedValues", {}),
            reason=body.get("reason", ""),
            authority_version=body.get("authorityVersion"),
            idempotency_key=request.headers.get("Idempotency-Key", ""),
            case_version=_version(request, body),
            evidence_material_id=body.get("evidenceMaterialId"),
        )
    except (CorrectionServiceError, ChangeServiceError, KeyError) as exc:
        if isinstance(exc, KeyError):
            return error_response(request, "CHANGE_INVALID_PAYLOAD", f"缺少必填参数: {exc.args[0]}", status=400)
        return _service_error(request, exc)
    payload = api_root(request)
    payload["schemaVersion"] = "hr06.corrections.create.1"
    payload["data"] = _correction_payload(correction)
    return json_response(request, payload, status=201)


@require_http_methods(["POST"])
@require_hr_change_permission("hr.change.correct")
def correction_action(request, correction_id, action: str):
    ctx, err = _context(request)
    if err:
        return err
    try:
        body = _body(request)
        svc = _svc(request, ctx)
        expected_version = _version(request, body)
        if action == "submit":
            correction = svc.submit(correction_id, expected_version=expected_version)
        elif action == "approve":
            correction = svc.approve(correction_id, expected_version=expected_version)
        elif action == "reject":
            correction = svc.reject(correction_id, expected_version=expected_version)
        elif action == "apply":
            correction = svc.apply(
                correction_id,
                expected_version=expected_version,
                idempotency_key=request.headers.get("Idempotency-Key", ""),
            )
        else:
            return error_response(request, "CHANGE_INVALID_ACTION", f"未知动作 {action}", status=404)
    except (CorrectionServiceError, ChangeServiceError) as exc:
        return _service_error(request, exc)
    payload = api_root(request)
    payload["schemaVersion"] = "hr06.corrections.action.1"
    payload["data"] = _correction_payload(correction)
    return json_response(request, payload)
