"""
hr_external/api/hiring.py —— HR08-03 聘用审批 API（S5）。

路由（总册 §83）：
- GET  /api/hr/v1/external-teachers/hiring-cases
- POST /api/hr/v1/external-teachers/hiring-cases
- GET  /api/hr/v1/external-teachers/hiring-cases/{id}
- POST /api/hr/v1/external-teachers/hiring-cases/{id}/validate
- POST /api/hr/v1/external-teachers/hiring-cases/{id}/submit
- POST /api/hr/v1/external-teachers/hiring-cases/{id}/return
- POST /api/hr/v1/external-teachers/hiring-cases/{id}/approve
- POST /api/hr/v1/external-teachers/hiring-cases/{id}/activate
"""

from __future__ import annotations

import json
import uuid
from datetime import date

from django.utils.dateparse import parse_date

from hr_external.api.base import (
    api_root,
    error_response,
    json_response,
    make_external_context,
)
from hr_external.constants import ExternalHiringStatus
from hr_external.display_labels import category_label
from hr_external.models import (
    HrExternalCategory,
    HrExternalHiringCase,
    HrExternalTeacherProfile,
)
from hr_external.permissions import require_hr_external_permission

_HIRING_STATUS_LABELS = {
    "DRAFT": "草稿",
    "VALIDATING": "校验中",
    "SUBMITTED": "已提交",
    "UNDER_COLLEGE_REVIEW": "学院审批",
    "UNDER_HR_REVIEW": "HR 审批",
    "UNDER_SCHOOL_APPROVAL": "学校批准",
    "APPROVED": "已批准",
    "WAITING_AGREEMENT": "待签署协议",
    "READY_TO_ACTIVATE": "待激活",
    "ACTIVATED": "已激活",
    "RETURNED": "已退回",
    "REJECTED": "已拒绝",
    "WITHDRAWN": "已撤回",
    "CANCELLED": "已取消",
}
from hr_external.services.audit_service import write_external_audit
from hr_external.services.compliance_service import ComplianceService
from hr_external.services.hiring_service import (
    AgreementNotReady,
    ComplianceBlocked,
    HiringService,
    InvalidHiringState,
)


def _ctx(request):
    try:
        return make_external_context(request, authority_mode="LEGACY_EMPLOYEE_TAG_ONLY"), None
    except Exception as exc:  # noqa: BLE001
        code = getattr(exc, "code", "INVALID_REQUEST")
        status = 403 if code == "TENANT_CONTEXT_REQUIRED" else 400
        return None, error_response(request, code, str(exc), status)


def _case_row(case: HrExternalHiringCase) -> dict:
    return {
        "id": str(case.id),
        "caseNo": case.case_no,
        "requestOrgId": case.request_org_id,
        "category": case.category_id.code,
        "categoryLabel": category_label(case.category_id.code),
        "purpose": case.purpose,
        "proposedPersonId": str(case.proposed_person_id_id) if case.proposed_person_id_id else None,
        "requestedStart": case.requested_start.isoformat(),
        "requestedEnd": case.requested_end.isoformat() if case.requested_end else None,
        "plannedAssignments": case.planned_assignments_json or [],
        "estimatedWorkload": float(case.estimated_workload) if case.estimated_workload is not None else None,
        "estimatedCostReference": case.estimated_cost_reference,
        "status": case.status,
        "statusLabel": _HIRING_STATUS_LABELS.get(case.status, case.status),
        "approvalInstanceId": case.approval_instance_id,
        "version": case.version,
    }


def hiring_collection(request):
    """Canonical collection dispatcher: GET lists; POST creates."""
    if request.method == "GET":
        return hiring_list(request)
    if request.method == "POST":
        return hiring_create(request)
    return error_response(request, "METHOD_NOT_ALLOWED", "仅支持 GET 或 POST", 405)


@require_hr_external_permission("hr08.hiring.review")
def hiring_list(request):
    ctx, err = _ctx(request)
    if err:
        return err

    status = request.GET.get("status", "")
    qs = HrExternalHiringCase.objects.filter(tenant_id=ctx.tenant_id).select_related("category_id")
    if status:
        qs = qs.filter(status=status)
    qs = qs.order_by("-updated_at")[:200]

    body = api_root(request)
    body["data"] = {"items": [_case_row(c) for c in qs], "total": qs.count()}
    return json_response(request, body)


@require_hr_external_permission("hr08.hiring.create")
def hiring_create(request):
    ctx, err = _ctx(request)
    if err:
        return err
    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return error_response(request, "INVALID_REQUEST", "请求体必须是 JSON", 400)

    requested_start = parse_date(payload.get("requestedStart") or "")
    requested_end = parse_date(payload.get("requestedEnd") or "") if payload.get("requestedEnd") else None
    if requested_start is None:
        return error_response(request, "INVALID_REQUEST", "拟聘开始日期必填且必须有效", 400)
    if requested_end is not None and requested_end <= requested_start:
        return error_response(request, "INVALID_REQUEST", "拟聘结束日期必须晚于开始日期", 400)

    category = HrExternalCategory.objects.filter(
        tenant_id=ctx.tenant_id,
        id=payload.get("categoryId"),
    ).first()
    if category is None:
        return error_response(request, "EXTERNAL_CATEGORY_INVALID", "外聘类别不可用", 400)

    profile_qs = HrExternalTeacherProfile.objects.filter(tenant_id=ctx.tenant_id)
    if payload.get("proposedProfileId"):
        profile = profile_qs.filter(id=payload.get("proposedProfileId")).select_related("person_id").first()
    else:
        profile = profile_qs.filter(
            person_id_id=payload.get("proposedPersonId")
        ).select_related("person_id").first()
    if profile is None:
        return error_response(request, "EXTERNAL_PROFILE_NOT_FOUND", "候选外聘档案不可用", 400)

    try:
        request_org_id = int(payload.get("requestOrgId"))
    except (TypeError, ValueError):
        return error_response(request, "INVALID_REQUEST", "申请学院必填", 400)

    from hr_structure.public import (
        OrganizationEvidenceUnavailable,
        get_organization_evidence,
    )

    try:
        organization_evidence = get_organization_evidence(
            tenant_id=ctx.tenant_id,
            organization_ids=[request_org_id],
            as_of=requested_start or date.today(),
        )
    except OrganizationEvidenceUnavailable as exc:
        return error_response(request, exc.code, str(exc), 409)
    if organization_evidence.missing_organization_ids:
        return error_response(request, "INVALID_REQUEST", "申请学院不是当前有效 HR02 组织", 400)

    planned_assignments = payload.get("plannedAssignments") or []
    if not isinstance(planned_assignments, list):
        return error_response(request, "INVALID_REQUEST", "拟任任务必须为列表", 400)

    case = HrExternalHiringCase.objects.create(
        tenant_id=ctx.tenant_id,
        case_no=f"C{uuid.uuid4().hex[:8].upper()}",
        request_org_id=request_org_id,
        requester_id=ctx.user_id or 0,
        category_id=category,
        purpose=payload.get("purpose") or "",
        proposed_person_id=profile.person_id,
        requested_start=requested_start,
        requested_end=requested_end,
        planned_assignments_json=planned_assignments,
        estimated_workload=payload.get("estimatedWorkload"),
        estimated_cost_reference=payload.get("estimatedCostReference") or "",
        status=ExternalHiringStatus.DRAFT,
    )

    write_external_audit(
        tenant_id=ctx.tenant_id,
        action="ExternalHiringCaseCreated",
        actor_user_id=ctx.user_id,
        business_type="HR08_HIRING",
        business_id=str(case.id),
        source="api",
    )
    body = api_root(request)
    body["data"] = _case_row(case)
    return json_response(request, body, status=201)


@require_hr_external_permission("hr08.hiring.review")
def hiring_detail(request, case_id):
    ctx, err = _ctx(request)
    if err:
        return err
    case = HrExternalHiringCase.objects.filter(
        tenant_id=ctx.tenant_id, id=case_id
    ).select_related("category_id", "proposed_person_id").first()
    if case is None:
        return error_response(request, "EXTERNAL_HIRING_CASE_NOT_FOUND", "聘用审批单不存在", 404)

    # 审批前检查（§35）展示
    profile = HrExternalTeacherProfile.objects.filter(
        tenant_id=ctx.tenant_id, person_id_id=case.proposed_person_id_id
    ).first()
    compliance = None
    if profile is not None:
        compliance = ComplianceService().run_checks(
            tenant_id=ctx.tenant_id,
            case=case,
            profile=profile,
            category=case.category_id,
        ).summary()

    body = api_root(request)
    data = _case_row(case)
    data["proposedPersonName"] = case.proposed_person_id.legal_name if case.proposed_person_id else None
    data["compliance"] = compliance
    body["data"] = data
    return json_response(request, body)


def _get_case(request, case_id):
    ctx, err = _ctx(request)
    if err:
        return None, None, err
    case = HrExternalHiringCase.objects.filter(
        tenant_id=ctx.tenant_id, id=case_id
    ).select_related("category_id").first()
    if case is None:
        return None, None, error_response(request, "EXTERNAL_HIRING_CASE_NOT_FOUND", "聘用审批单不存在", 404)
    return ctx, case, None


@require_hr_external_permission("hr08.hiring.review")
def hiring_validate(request, case_id):
    ctx, case, err = _get_case(request, case_id)
    if err:
        return err
    # VALIDATING 并返回审批前检查（不自动转状态之外动作）
    result = None
    profile = HrExternalTeacherProfile.objects.filter(
        tenant_id=ctx.tenant_id, person_id_id=case.proposed_person_id_id
    ).first()
    if profile is not None:
        result = ComplianceService().run_checks(
            tenant_id=ctx.tenant_id,
            case=case,
            profile=profile,
            category=case.category_id,
        ).summary()
    body = api_root(request)
    body["data"] = {"id": str(case.id), "compliance": result}
    return json_response(request, body)


@require_hr_external_permission("hr08.hiring.review")
def hiring_submit(request, case_id):
    ctx, case, err = _get_case(request, case_id)
    if err:
        return err
    try:
        case = HiringService().submit(case, tenant_id=ctx.tenant_id)
    except InvalidHiringState as exc:
        return error_response(request, exc.code, str(exc), 409)
    write_external_audit(
        tenant_id=ctx.tenant_id, action="ExternalHiringCaseSubmitted", actor_user_id=ctx.user_id,
        business_id=str(case.id), source="api",
    )
    body = api_root(request)
    body["data"] = _case_row(case)
    return json_response(request, body)


@require_hr_external_permission("hr08.hiring.review")
def hiring_return(request, case_id):
    ctx, case, err = _get_case(request, case_id)
    if err:
        return err
    try:
        case = HiringService().return_to_draft(case, tenant_id=ctx.tenant_id)
    except InvalidHiringState as exc:
        return error_response(request, exc.code, str(exc), 409)
    body = api_root(request)
    body["data"] = _case_row(case)
    return json_response(request, body)


@require_hr_external_permission("hr08.hiring.approve")
def hiring_approve(request, case_id):
    """按当前状态推进审批层级：学院→HR→学校。学校批准执行审批前检查（§35）。"""
    ctx, case, err = _get_case(request, case_id)
    if err:
        return err
    service = HiringService()
    try:
        if case.status == ExternalHiringStatus.SUBMITTED:
            case = service.college_approve(case, tenant_id=ctx.tenant_id)
        elif case.status == ExternalHiringStatus.UNDER_COLLEGE_REVIEW:
            case = service.hr_approve(case, tenant_id=ctx.tenant_id)
        elif case.status == ExternalHiringStatus.UNDER_HR_REVIEW:
            case = service.school_approve(case, tenant_id=ctx.tenant_id)
        elif case.status == ExternalHiringStatus.APPROVED:
            case = service.wait_agreement(case, tenant_id=ctx.tenant_id)
        else:
            return error_response(request, "VERSION_CONFLICT", f"当前状态不可审批: {case.status}", 409)
    except Exception as exc:  # noqa: BLE001 —— 统一信封
        code = getattr(exc, "code", "VERSION_CONFLICT")
        return error_response(request, code, str(exc), 409 if code == "VERSION_CONFLICT" else 400)

    write_external_audit(
        tenant_id=ctx.tenant_id, action="ExternalHiringApproved", actor_user_id=ctx.user_id,
        business_id=str(case.id), source="api",
    )
    body = api_root(request)
    body["data"] = _case_row(case)
    return json_response(request, body)


@require_hr_external_permission("hr08.hiring.activate")
def hiring_activate(request, case_id):
    ctx, case, err = _get_case(request, case_id)
    if err:
        return err
    try:
        eng = HiringService().activate(
            case, tenant_id=ctx.tenant_id, actor_id=ctx.user_id
        )
    except (InvalidHiringState, AgreementNotReady) as exc:
        return error_response(request, getattr(exc, "code", "VERSION_CONFLICT"), str(exc), 409)

    write_external_audit(
        tenant_id=ctx.tenant_id, action="ExternalEngagementActivated", actor_user_id=ctx.user_id,
        business_type="HR08_ENGAGEMENT", business_id=str(eng.id), source="api",
    )
    body = api_root(request)
    body["data"] = {"caseId": str(case.id), "engagementId": str(eng.id), "status": case.status}
    return json_response(request, body)
