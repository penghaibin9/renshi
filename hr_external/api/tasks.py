"""
hr_external/api/tasks.py —— HR08-04 教学与服务任务 API（S7）。

路由（总册 §85）：
- GET  /api/hr/v1/external-teachers/tasks
- POST /api/hr/v1/external-teachers/tasks
- GET  /api/hr/v1/external-teachers/tasks/{id}
- POST /api/hr/v1/external-teachers/tasks/{id}/accept
- POST /api/hr/v1/external-teachers/tasks/{id}/submit
- POST /api/hr/v1/external-teachers/tasks/{id}/verify
- POST /api/hr/v1/external-teachers/tasks/{id}/return
- GET  /api/hr/v1/external-teachers/workload
- POST /api/hr/v1/external-teachers/workload/verify
- POST /api/hr/v1/external-teachers/engagements/{id}/settlement
"""

from __future__ import annotations

import json

from django.utils.dateparse import parse_date

from hr_external.api.base import (
    api_root,
    error_response,
    json_response,
    make_external_context,
)
from hr_external.models import (
    HrExternalEngagement,
    HrExternalServiceTask,
    HrExternalWorkloadRecord,
)
from hr_external.display_labels import (
    settlement_status_label,
    task_acceptance_label,
    task_status_label,
    workload_verification_label,
)
from hr_external.permissions import require_hr_external_permission
from hr_external.services.audit_service import write_external_audit
from hr_external.services.task_service import (
    TaskOutsideEngagement,
    TaskService,
    TaskStateConflict,
    WorkloadOverCap,
)

_TASK_TYPE_LABELS = {
    "TEACHING": "教学",
    "PRACTICE_GUIDANCE": "实训指导",
    "INDUSTRY_MENTOR": "产业导师",
    "PROGRAM_DEVELOPMENT": "专业建设",
    "RESEARCH_COLLABORATION": "科研合作",
    "SKILL_TRAINING": "技能培训",
    "FACULTY_DEVELOPMENT": "教师发展",
    "STUDENT_MENTORING": "学生指导",
    "OTHER": "其他",
}

_SOURCE_DOMAIN_LABELS = {
    "ACADEMIC": "教务",
    "HR08": "人事系统",
    "LEGACY_IMPORT": "历史导入",
    "OTHER": "其他",
}

_WORKLOAD_SOURCE_LABELS = {
    "ACADEMIC_VERIFIED": "教务核验",
    "SYSTEM_CALCULATED": "系统计算",
    "MANUAL_WITH_EVIDENCE": "人工申报（附证据）",
    "IMPORT_VERIFIED": "导入核验",
}


def _ctx(request):
    try:
        return make_external_context(request, authority_mode="LEGACY_EMPLOYEE_TAG_ONLY"), None
    except Exception as exc:  # noqa: BLE001
        code = getattr(exc, "code", "INVALID_REQUEST")
        status = 403 if code == "TENANT_CONTEXT_REQUIRED" else 400
        return None, error_response(request, code, str(exc), status)


def _task_row(t: HrExternalServiceTask) -> dict:
    return {
        "id": str(t.id),
        "engagementId": str(t.engagement_id_id),
        "engagementNo": t.engagement_id.engagement_no,
        "personName": t.engagement_id.external_profile_id.person_id.legal_name,
        "taskType": t.task_type,
        "taskTypeLabel": _TASK_TYPE_LABELS.get(t.task_type, t.task_type),
        "sourceDomain": t.source_domain,
        "sourceDomainLabel": _SOURCE_DOMAIN_LABELS.get(t.source_domain, t.source_domain),
        "sourceObjectType": t.source_object_type,
        "sourceObjectId": t.source_object_id,
        "title": t.title,
        "plannedQuantity": float(t.planned_quantity) if t.planned_quantity is not None else None,
        "plannedUnit": t.planned_unit,
        "plannedStart": t.planned_start.isoformat(),
        "plannedEnd": t.planned_end.isoformat() if t.planned_end else None,
        "ownerOrgId": t.owner_org_id,
        "status": t.status,
        "statusLabel": task_status_label(t.status),
        "acceptance": t.acceptance,
        "acceptanceLabel": task_acceptance_label(t.acceptance),
        "settlementEligible": t.settlement_eligible,
        "version": t.version,
    }


def _err_response(request, exc):
    code = getattr(exc, "code", "VERSION_CONFLICT")
    status = 409 if code == "VERSION_CONFLICT" else 400
    return error_response(request, code, str(exc), status)


def task_collection(request):
    """Canonical collection dispatcher: GET lists; POST creates."""
    if request.method == "GET":
        return task_list(request)
    if request.method == "POST":
        return task_create(request)
    return error_response(request, "METHOD_NOT_ALLOWED", "仅支持 GET 或 POST", 405)


@require_hr_external_permission("hr08.task.view")
def task_list(request):
    ctx, err = _ctx(request)
    if err:
        return err
    status = request.GET.get("status", "")
    qs = HrExternalServiceTask.objects.filter(tenant_id=ctx.tenant_id).select_related(
        "engagement_id__external_profile_id__person_id"
    )
    if status:
        qs = qs.filter(status=status)
    qs = qs.order_by("-updated_at")[:200]
    body = api_root(request)
    body["data"] = {"items": [_task_row(t) for t in qs], "total": qs.count()}
    return json_response(request, body)


@require_hr_external_permission("hr08.task.manage")
def task_create(request):
    ctx, err = _ctx(request)
    if err:
        return err
    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return error_response(request, "INVALID_REQUEST", "请求体必须是 JSON", 400)

    try:
        service = TaskService()
        t = service.create_task(
            tenant_id=ctx.tenant_id,
            engagement_id=payload.get("engagementId"),
            assignment_id=payload.get("assignmentId"),
            task_type=payload.get("taskType") or "OTHER",
            title=payload.get("title") or "",
            planned_start=parse_date(payload["plannedStart"]) if payload.get("plannedStart") else None,
            planned_end=parse_date(payload["plannedEnd"]) if payload.get("plannedEnd") else None,
            source_domain=payload.get("sourceDomain") or "HR08",
            source_object_type=payload.get("sourceObjectType") or "",
            source_object_id=payload.get("sourceObjectId") or "",
            description=payload.get("description") or "",
            planned_quantity=payload.get("plannedQuantity"),
            planned_unit=payload.get("plannedUnit") or "",
            owner_org_id=payload.get("ownerOrgId"),
            reviewer_id=payload.get("reviewerId"),
            settlement_eligible=bool(payload.get("settlementEligible", False)),
        )
        service.assign(t)
    except (TaskOutsideEngagement, ValueError) as exc:
        return _err_response(request, exc)

    write_external_audit(
        tenant_id=ctx.tenant_id, action="ExternalTaskAssigned", actor_user_id=ctx.user_id,
        task_id=t.id, engagement_id=t.engagement_id_id, source="api",
    )
    body = api_root(request)
    body["data"] = _task_row(t)
    return json_response(request, body, status=201)


@require_hr_external_permission("hr08.task.view")
def task_detail(request, task_id):
    ctx, err = _ctx(request)
    if err:
        return err
    t = HrExternalServiceTask.objects.filter(tenant_id=ctx.tenant_id, id=task_id).first()
    if t is None:
        return error_response(request, "EXTERNAL_TASK_NOT_FOUND", "任务不存在", 404)
    body = api_root(request)
    body["data"] = _task_row(t)
    return json_response(request, body)


def _get_task(request, task_id):
    ctx, err = _ctx(request)
    if err:
        return None, None, err
    t = HrExternalServiceTask.objects.filter(tenant_id=ctx.tenant_id, id=task_id).first()
    if t is None:
        return None, None, error_response(request, "EXTERNAL_TASK_NOT_FOUND", "任务不存在", 404)
    return ctx, t, None


@require_hr_external_permission("hr08.task.view")
def task_accept(request, task_id):
    """POST /tasks/{id}/accept  body: {action: ACCEPT|REQUEST_CLARIFICATION|DECLINE_WITH_REASON, reason?}"""
    ctx, t, err = _get_task(request, task_id)
    if err:
        return err
    try:
        payload = json.loads(request.body or b"{}")
        action = payload.get("action") or "ACCEPTED"
    except json.JSONDecodeError:
        return error_response(request, "INVALID_REQUEST", "请求体必须是 JSON", 400)

    try:
        TaskService().accept(t, action, payload.get("reason") or "")
    except TaskStateConflict as exc:
        return _err_response(request, exc)
    body = api_root(request)
    body["data"] = _task_row(t)
    return json_response(request, body)


@require_hr_external_permission("hr08.task.view")
def task_start(request, task_id):
    ctx, t, err = _get_task(request, task_id)
    if err:
        return err
    try:
        TaskService().start(t)
    except TaskStateConflict as exc:
        return _err_response(request, exc)
    body = api_root(request)
    body["data"] = _task_row(t)
    return json_response(request, body)


@require_hr_external_permission("hr08.task.view")
def task_submit(request, task_id):
    ctx, t, err = _get_task(request, task_id)
    if err:
        return err
    try:
        TaskService().submit(t)
    except TaskStateConflict as exc:
        return _err_response(request, exc)
    body = api_root(request)
    body["data"] = _task_row(t)
    return json_response(request, body)


@require_hr_external_permission("hr08.task.verify")
def task_verify(request, task_id):
    """POST /tasks/{id}/verify  body: {action: COMPLETE|REJECT}"""
    ctx, t, err = _get_task(request, task_id)
    if err:
        return err
    try:
        payload = json.loads(request.body or b"{}")
        action = payload.get("action") or "COMPLETE"
    except json.JSONDecodeError:
        return error_response(request, "INVALID_REQUEST", "请求体必须是 JSON", 400)

    try:
        svc = TaskService()
        svc.review(t)
        if action == "COMPLETE":
            svc.complete(t)
        else:
            svc.reject_for_correction(t)
    except TaskStateConflict as exc:
        return _err_response(request, exc)

    write_external_audit(
        tenant_id=ctx.tenant_id, action="ExternalTaskCompleted", actor_user_id=ctx.user_id,
        task_id=t.id, engagement_id=t.engagement_id_id, source="api",
    )
    body = api_root(request)
    body["data"] = _task_row(t)
    return json_response(request, body)


@require_hr_external_permission("hr08.task.view")
def workload_list(request):
    ctx, err = _ctx(request)
    if err:
        return err
    qs = HrExternalWorkloadRecord.objects.filter(tenant_id=ctx.tenant_id).order_by("-service_date")[:200]
    body = api_root(request)
    body["data"] = {
        "items": [
            {
                "id": str(r.id),
                "engagementId": str(r.engagement_id_id),
                "taskId": str(r.task_id_id) if r.task_id_id else None,
                "source": r.source,
                "sourceLabel": _WORKLOAD_SOURCE_LABELS.get(r.source, r.source),
                "quantity": float(r.quantity),
                "unit": r.unit,
                "serviceDate": r.service_date.isoformat(),
                "verificationStatus": r.verification_status,
                "verificationStatusLabel": workload_verification_label(r.verification_status),
                "settlementStatus": r.settlement_status,
                "settlementStatusLabel": settlement_status_label(r.settlement_status),
                "version": r.version,
            }
            for r in qs
        ],
        "total": qs.count(),
    }
    return json_response(request, body)


@require_hr_external_permission("hr08.workload.verify")
def workload_verify(request):
    """POST /api/hr/v1/external-teachers/workload/verify
    body: {engagementId, taskId?, source, quantity, unit?, serviceDate, verified?}"""
    ctx, err = _ctx(request)
    if err:
        return err
    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return error_response(request, "INVALID_REQUEST", "请求体必须是 JSON", 400)

    try:
        record = TaskService().add_workload(
            tenant_id=ctx.tenant_id,
            engagement_id=payload.get("engagementId"),
            task_id=payload.get("taskId"),
            source=payload.get("source") or "SYSTEM_CALCULATED",
            quantity=payload.get("quantity"),
            unit=payload.get("unit") or "",
            service_date=parse_date(payload["serviceDate"]) if payload.get("serviceDate") else None,
            verified=bool(payload.get("verified", False)),
        )
    except (TaskOutsideEngagement, WorkloadOverCap, ValueError) as exc:
        return _err_response(request, exc)

    write_external_audit(
        tenant_id=ctx.tenant_id, action="ExternalWorkloadVerified", actor_user_id=ctx.user_id,
        engagement_id=record.engagement_id_id, source="api",
    )
    body = api_root(request)
    body["data"] = {
        "id": str(record.id),
        "verificationStatus": record.verification_status,
        "verificationStatusLabel": workload_verification_label(record.verification_status),
        "settlementStatus": record.settlement_status,
        "settlementStatusLabel": settlement_status_label(record.settlement_status),
    }
    return json_response(request, body, status=201)


@require_hr_external_permission("hr08.workload.verify")
def settlement_create(request, engagement_id):
    """POST /api/hr/v1/external-teachers/engagements/{id}/settlement
    body: {period, policyRef?} —— 聚合 verified workload → SettlementBasis（§53）。"""
    ctx, err = _ctx(request)
    if err:
        return err
    eng = HrExternalEngagement.objects.filter(
        tenant_id=ctx.tenant_id, id=engagement_id
    ).first()
    if eng is None:
        return error_response(request, "EXTERNAL_ENGAGEMENT_NOT_FOUND", "聘期不存在", 404)
    try:
        payload = json.loads(request.body or b"{}")
        period = payload.get("period") or ""
    except json.JSONDecodeError:
        return error_response(request, "INVALID_REQUEST", "请求体必须是 JSON", 400)
    if not period:
        return error_response(request, "INVALID_REQUEST", "period 必填", 400)

    basis = TaskService().build_settlement_basis(
        tenant_id=ctx.tenant_id,
        engagement_id=eng.id,
        period=period,
        policy_ref=payload.get("policyRef") or "",
    )
    body = api_root(request)
    body["data"] = {
        "id": str(basis.id),
        "period": basis.period,
        "verifiedWorkload": float(basis.verified_workload),
        "eligibleItems": basis.eligible_items,
        "status": basis.status,
        "statusLabel": settlement_status_label(basis.status),
        "note": "HR15/财务负责实际金额（§138.9）",
    }
    return json_response(request, body)
