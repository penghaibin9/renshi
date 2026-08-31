"""
hr_staff/api/corrections.py —— HR03-06 信息更正 API（S9）。

POST /api/hr/v1/staff/{staff_id}/corrections            创建
GET  /api/hr/v1/staff/{staff_id}/corrections            列表
GET  /api/hr/v1/corrections/{case_id}                   详情
POST /api/hr/v1/corrections/{case_id}/submit|review|return|resubmit|approve|reject|cancel|apply
全部写操作带 version + reason + 事务 + 审计。
"""

from __future__ import annotations

import json
import uuid

from django.views.decorators.http import require_GET, require_POST

from hr_staff.api.base import (
    api_root,
    error_response,
    json_response,
    make_staff_context,
)
from hr_staff.context import HrStaffContextError
from hr_staff.permissions import require_hr_staff_permission
from hr_staff.services.correction_service import (
    CorrectionPolicyDenied,
    CorrectionService,
    CorrectionStateError,
)

SCHEMA_CORRECTIONS = "hr03.corrections.1"


def _make(request):
    try:
        return make_staff_context(request)
    except HrStaffContextError as exc:
        return error_response(request, exc.code, exc.message, status=403)


def _parse_json_body(request):
    try:
        return json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return None


def _error_for(request, exc):
    if isinstance(exc, CorrectionPolicyDenied):
        return error_response(request, exc.code, str(exc), status=403)
    if isinstance(exc, CorrectionStateError):
        code = exc.code
        status = 409 if "CONFLICT" in code or "APPLY_FAILED" in code else 400
        return error_response(request, code, str(exc), status=status)
    code = getattr(exc, "code", "")
    if code == "CROSS_TENANT_REFERENCE":
        return error_response(request, "CROSS_TENANT_REFERENCE", str(exc), status=403)
    if code == "STAFF_NOT_FOUND":
        return error_response(request, "STAFF_NOT_FOUND", "未找到该教职工", status=404)
    return error_response(
        request,
        "CORRECTION_OPERATION_FAILED",
        str(exc),
        status=400,
        details={"errorClass": exc.__class__.__name__},
    )


def _case_payload(case):
    return {
        "id": str(case.id),
        "caseNo": case.case_no,
        "staffId": str(case.staff_id_id),
        "status": case.status,
        "reason": case.reason,
        "impactLevel": case.impact_level,
        "evidenceMaterialId": str(case.evidence_material_id) if case.evidence_material_id else None,
        "submittedBy": case.submitted_by,
        "reviewedBy": case.reviewed_by,
        "approvedBy": case.approved_by,
        "appliedAt": case.applied_at.isoformat() if case.applied_at else None,
        "applyError": case.apply_error,
        "returnReason": case.return_reason,
        "rejectReason": case.reject_reason,
        "items": [
            {
                "id": str(i.id),
                "fieldCode": i.field_code,
                "factType": i.fact_type,
                "oldValueMasked": i.old_value_masked,
                "newValueMasked": i.new_value_masked,
                "effectiveDate": i.effective_date.isoformat() if i.effective_date else None,
                "impactLevel": i.impact_level,
                "applied": i.applied,
            }
            for i in case.items.all()
        ],
    }


@require_POST
@require_hr_staff_permission("hr.staff.correction.create")
def create_correction(request, staff_id):
    resp = _make(request)
    if not hasattr(resp, "tenant_id"):
        return resp
    body = _parse_json_body(request)
    if body is None:
        return error_response(request, "INVALID_REQUEST", "请求体不是合法 JSON", status=400)
    svc = CorrectionService(resp.tenant_id, actor_user_id=request.user.id)
    try:
        case = svc.create_case(
            staff_id=staff_id,
            reason=body.get("reason", ""),
            items=body.get("items", []),
            evidence_material_id=body.get("evidence_material_id"),
        )
    except Exception as exc:
        return _error_for(request, exc)
    payload = api_root(request)
    payload["schemaVersion"] = SCHEMA_CORRECTIONS
    payload["data"] = _case_payload(case)
    return json_response(request, payload, status=201)


@require_GET
@require_hr_staff_permission("hr.staff.correction.view")
def list_corrections(request, staff_id):
    resp = _make(request)
    if not hasattr(resp, "tenant_id"):
        return resp
    from hr_staff.models import HrCorrectionCase

    cases = HrCorrectionCase.objects.filter(
        tenant_id=resp.tenant_id, staff_id=staff_id
    ).order_by("-created_at")[:100]
    payload = api_root(request)
    payload["schemaVersion"] = SCHEMA_CORRECTIONS
    payload["data"] = {"items": [_case_payload(c) for c in cases]}
    return json_response(request, payload)


@require_GET
@require_hr_staff_permission("hr.staff.correction.view")
def correction_detail(request, case_id):
    resp = _make(request)
    if not hasattr(resp, "tenant_id"):
        return resp
    from hr_staff.models import HrCorrectionCase

    case = HrCorrectionCase.objects.filter(
        tenant_id=resp.tenant_id, id=case_id
    ).prefetch_related("items").first()
    if case is None:
        # P2：统一 JSON 信封，不返回 HTML 404
        return error_response(request, "CORRECTION_NOT_FOUND", "更正不存在", status=404)
    payload = api_root(request)
    payload["schemaVersion"] = SCHEMA_CORRECTIONS
    payload["data"] = _case_payload(case)
    return json_response(request, payload)


def _transition(request, case_id, action, high_risk=False):
    resp = _make(request)
    if not hasattr(resp, "tenant_id"):
        return resp
    body = _parse_json_body(request) or {}
    svc = CorrectionService(resp.tenant_id, actor_user_id=request.user.id)
    try:
        if action == "submit":
            case = svc.submit(case_id)
        elif action == "review":
            case = svc.review(case_id)
        elif action == "return":
            case = svc.return_(case_id, body.get("reason", ""))
        elif action == "resubmit":
            case = svc.resubmit(case_id)
        elif action == "approve":
            case = svc.approve(case_id, approve_high_risk=high_risk)
        elif action == "reject":
            case = svc.reject(case_id, body.get("reason", ""))
        elif action == "cancel":
            case = svc.cancel(case_id)
        elif action == "apply":
            # P1-3：apply 支持乐观锁 expected_version（body.version），冲突 → 409 VERSION_CONFLICT
            expected_version = body.get("version")
            case = svc.apply(
                case_id,
                expected_version=int(expected_version) if expected_version else None,
            )
        else:
            return error_response(request, "INVALID_REQUEST", f"未知动作: {action}", status=400)
    except Exception as exc:
        return _error_for(request, exc)
    payload = api_root(request)
    payload["schemaVersion"] = SCHEMA_CORRECTIONS
    payload["data"] = _case_payload(case)
    return json_response(request, payload)


@require_POST
@require_hr_staff_permission("hr.staff.correction.create")
def submit_correction(request, case_id):
    return _transition(request, case_id, "submit")


@require_POST
@require_hr_staff_permission("hr.staff.correction.review")
def review_correction(request, case_id):
    return _transition(request, case_id, "review")


@require_POST
@require_hr_staff_permission("hr.staff.correction.review")
def return_correction(request, case_id):
    return _transition(request, case_id, "return")


@require_POST
@require_hr_staff_permission("hr.staff.correction.create")
def resubmit_correction(request, case_id):
    return _transition(request, case_id, "resubmit")


@require_POST
@require_hr_staff_permission("hr.staff.correction.review")
def approve_correction(request, case_id):
    # P1-7 修复：不再恒传 high_risk=True；是否可批高风险由独立权限 hr.staff.correction.approve_high_risk 决定，
    # 服务层对高风险 impact 校验 approve_high_risk 标志，权限不足 → 403。
    high_risk_ok = request.user.has_perm("hr.staff.correction.approve_high_risk")
    return _transition(request, case_id, "approve", high_risk=high_risk_ok)


@require_POST
@require_hr_staff_permission("hr.staff.correction.review")
def reject_correction(request, case_id):
    return _transition(request, case_id, "reject")


@require_POST
@require_hr_staff_permission("hr.staff.correction.review")
def cancel_correction(request, case_id):
    return _transition(request, case_id, "cancel")


@require_POST
@require_hr_staff_permission("hr.staff.correction.review")
def apply_correction(request, case_id):
    return _transition(request, case_id, "apply")
