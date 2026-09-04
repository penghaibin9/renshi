"""
hr_external/api/renewal_exit.py —— HR08-05 续聘与退出 API（S8）。

路由（总册 §86）：
- GET  /api/hr/v1/external-teachers/renewals
- POST /api/hr/v1/external-teachers/engagements/{id}/renewal-review
- POST /api/hr/v1/external-teachers/renewal-reviews/{id}/decide
- POST /api/hr/v1/external-teachers/engagements/{id}/exit
- GET  /api/hr/v1/external-teachers/exits/{id}
- POST /api/hr/v1/external-teachers/exits/{id}/complete
"""

from __future__ import annotations

import json

from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_POST

from hr_external.api.base import (
    api_root,
    error_response,
    json_response,
    make_external_context,
)
from hr_external.display_labels import (
    engagement_status_label,
    exit_reason_label,
    exit_status_label,
    renewal_status_label,
)
from hr_external.models import (
    HrExternalEngagement,
    HrExternalExitCase,
    HrExternalRenewalReview,
)
from hr_external.permissions import require_hr_external_permission

_RENEWAL_DECISION_LABELS = {
    "RENEW": "续聘",
    "RENEW_WITH_CHANGES": "调整后续聘",
    "CHANGE_CATEGORY": "变更类别",
    "CHANGE_HOST_ORG": "变更主办学院",
    "CONVERT_TO_REGULAR_HR_PROCESS": "转正式员工",
    "DO_NOT_RENEW": "不予续聘",
    "NEEDS_REVIEW": "需复核",
}
from hr_external.services.audit_service import write_external_audit
from hr_external.services.exit_service import ExitBlocked, ExitService, ExitStateConflict
from hr_external.services.renewal_service import RenewalService, RenewalStateConflict


def _ctx(request):
    try:
        return make_external_context(request), None
    except Exception as exc:  # noqa: BLE001
        code = getattr(exc, "code", "INVALID_REQUEST")
        status = 403 if code == "TENANT_CONTEXT_REQUIRED" else 400
        return None, error_response(request, code, str(exc), status)


@require_GET
@require_hr_external_permission("hr08.renewal.review")
def renewal_list(request):
    ctx, err = _ctx(request)
    if err:
        return err
    status = request.GET.get("status", "")
    qs = HrExternalRenewalReview.objects.filter(tenant_id=ctx.tenant_id).select_related(
        "engagement_id__external_profile_id__person_id"
    )
    if status:
        qs = qs.filter(status=status)
    qs = qs.order_by("review_due_at")[:200]
    body = api_root(request)
    body["data"] = {
        "items": [
            {
                "id": str(r.id),
                "engagementId": str(r.engagement_id_id),
                "engagementNo": r.engagement_id.engagement_no,
                "personName": r.engagement_id.external_profile_id.person_id.legal_name,
                "reviewDueAt": r.review_due_at.isoformat(),
                "status": r.status,
                "statusLabel": renewal_status_label(r.status),
                "decision": r.decision,
                "decisionLabel": _RENEWAL_DECISION_LABELS.get(r.decision, r.decision) if r.decision else "",
                "nextEngagementId": str(r.next_engagement_id_id) if r.next_engagement_id_id else None,
            }
            for r in qs
        ],
        "total": qs.count(),
    }
    return json_response(request, body)


@require_POST
@require_hr_external_permission("hr08.renewal.review")
def renewal_create(request, engagement_id):
    """POST .../engagements/{id}/renewal-review 创建到期评估（§59）。"""
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
    except json.JSONDecodeError:
        return error_response(request, "INVALID_REQUEST", "请求体必须是 JSON", 400)

    try:
        review = RenewalService().create_review(
            tenant_id=ctx.tenant_id,
            engagement_id=eng.id,
            review_due_at=parse_date(payload.get("reviewDueAt")) or eng.review_at or eng.end_at or eng.start_at,
            task_completion_summary=payload.get("taskCompletionSummary") or "",
            quality_summary=payload.get("qualitySummary") or "",
            agreement_status=payload.get("agreementStatus") or "",
            access_summary=payload.get("accessSummary") or "",
            requester_org_opinion=payload.get("requesterOrgOpinion") or "",
            person_willingness=payload.get("personWillingness") or "",
        )
    except RenewalStateConflict as exc:
        return error_response(request, exc.code, str(exc), 409)

    body = api_root(request)
    body["data"] = {"id": str(review.id), "status": review.status}
    return json_response(request, body, status=201)


@require_POST
@require_hr_external_permission("hr08.renewal.decide")
def renewal_decide(request, review_id):
    """POST .../renewal-reviews/{id}/decide body: {decision, nextStart?, nextEnd?}（§60/§61）。"""
    ctx, err = _ctx(request)
    if err:
        return err
    review = HrExternalRenewalReview.objects.filter(
        tenant_id=ctx.tenant_id, id=review_id
    ).first()
    if review is None:
        return error_response(request, "INVALID_REQUEST", "评估单不存在", 404)
    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return error_response(request, "INVALID_REQUEST", "请求体必须是 JSON", 400)

    try:
        decision = RenewalService().decide(
            review,
            tenant_id=ctx.tenant_id,
            decision=payload.get("decision") or "",
            decided_by=ctx.user_id,
            next_start=parse_date(payload["nextStart"]) if payload.get("nextStart") else None,
            next_end=parse_date(payload["nextEnd"]) if payload.get("nextEnd") else None,
            next_category_id=payload.get("nextCategoryId"),
            next_host_org_id=payload.get("nextHostOrgId"),
        )
    except RenewalStateConflict as exc:
        return error_response(request, exc.code, str(exc), 409)
    review.refresh_from_db()

    write_external_audit(
        tenant_id=ctx.tenant_id, action="ExternalEngagementRenewed", actor_user_id=ctx.user_id,
        engagement_id=review.engagement_id_id, business_id=str(review.id), reason=decision, source="api",
    )
    body = api_root(request)
    body["data"] = {
        "id": str(review.id),
        "decision": decision,
        "decisionLabel": _RENEWAL_DECISION_LABELS.get(decision, decision),
        "status": review.status,
        "statusLabel": renewal_status_label(review.status),
        "nextEngagementId": str(review.next_engagement_id_id) if review.next_engagement_id_id else None,
        "note": "续聘不直接改 end_at（§61）：RENEW 已创建新 Engagement（DRAFT，待 S5 审批链）",
    }
    return json_response(request, body)


@require_POST
@require_hr_external_permission("hr08.exit.manage")
def exit_create(request, engagement_id):
    """POST .../engagements/{id}/exit body: {exitReason, plannedEndAt?, clearancePolicy?}（§63）。"""
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
    except json.JSONDecodeError:
        return error_response(request, "INVALID_REQUEST", "请求体必须是 JSON", 400)

    try:
        case = ExitService().create_exit_case(
            tenant_id=ctx.tenant_id,
            engagement_id=eng.id,
            exit_reason=payload.get("exitReason") or "TERM_COMPLETED",
            planned_end_at=parse_date(payload.get("plannedEndAt")) or eng.end_at or eng.start_at,
            clearance_policy=payload.get("clearancePolicy") or "",
        )
    except ExitBlocked as exc:
        return error_response(request, exc.code, str(exc), 409)

    write_external_audit(
        tenant_id=ctx.tenant_id, action="ExternalExitCaseCreated", actor_user_id=ctx.user_id,
        engagement_id=eng.id, business_id=str(case.id), source="api",
    )
    body = api_root(request)
    body["data"] = {
        "id": str(case.id),
        "status": case.status,
        "statusLabel": exit_status_label(case.status),
    }
    return json_response(request, body, status=201)


@require_POST
@require_hr_external_permission("hr08.exit.manage")
def exit_prepare(request, exit_id):
    """POST advances the auditable pre-exit review one state at a time."""
    ctx, err = _ctx(request)
    if err:
        return err
    case = HrExternalExitCase.objects.filter(
        tenant_id=ctx.tenant_id, id=exit_id
    ).first()
    if case is None:
        return error_response(request, "INVALID_REQUEST", "退出单不存在", 404)
    service = ExitService()
    try:
        if case.status == "PLANNED":
            case = service.submit_review(case, tenant_id=ctx.tenant_id)
        elif case.status == "UNDER_REVIEW":
            case = service.approve_exit(case, tenant_id=ctx.tenant_id)
        else:
            raise ExitStateConflict("case cannot advance review from current state")
    except ExitStateConflict as exc:
        return error_response(request, exc.code, str(exc), 409)
    body = api_root(request)
    body["data"] = {
        "id": str(case.id),
        "status": case.status,
        "statusLabel": exit_status_label(case.status),
    }
    return json_response(request, body)


@require_GET
@require_hr_external_permission("hr08.exit.manage")
def exit_detail(request, exit_id):
    ctx, err = _ctx(request)
    if err:
        return err
    case = HrExternalExitCase.objects.filter(
        tenant_id=ctx.tenant_id, id=exit_id
    ).select_related("engagement_id").first()
    if case is None:
        return error_response(request, "INVALID_REQUEST", "退出单不存在", 404)
    body = api_root(request)
    body["data"] = {
        "id": str(case.id),
        "engagementId": str(case.engagement_id_id),
        "engagementStatus": case.engagement_id.status,
        "engagementStatusLabel": engagement_status_label(case.engagement_id.status),
        "exitReason": case.exit_reason,
        "exitReasonLabel": exit_reason_label(case.exit_reason),
        "plannedEndAt": case.planned_end_at.isoformat() if case.planned_end_at else None,
        "actualEndAt": case.actual_end_at.isoformat() if case.actual_end_at else None,
        "status": case.status,
        "statusLabel": exit_status_label(case.status),
        "clearanceItems": case.clearance_items,
        "agreementTerminationRef": case.agreement_termination_ref,
        "version": case.version,
    }
    return json_response(request, body)


@require_POST
@require_hr_external_permission("hr08.exit.manage")
def exit_complete(request, exit_id):
    """POST .../exits/{id}/complete body: {clearanceOk?, clearanceItems?[]}
    完成退出：Engagement ENDED + 权限回收请求（§66），历史保留（§70）。"""
    ctx, err = _ctx(request)
    if err:
        return err
    case = HrExternalExitCase.objects.filter(
        tenant_id=ctx.tenant_id, id=exit_id
    ).first()
    if case is None:
        return error_response(request, "INVALID_REQUEST", "退出单不存在", 404)
    try:
        payload = json.loads(request.body or b"{}")
        clearance_ok = bool(payload.get("clearanceOk", True))
        items = payload.get("clearanceItems") or []
    except json.JSONDecodeError:
        return error_response(request, "INVALID_REQUEST", "请求体必须是 JSON", 400)

    service = ExitService()
    if case.status == "READY_TO_EXIT":
        case = service.start_exit(case, tenant_id=ctx.tenant_id)
    try:
        case = service.finalize_exit(case, tenant_id=ctx.tenant_id)
    except ExitStateConflict as exc:
        return error_response(request, exc.code, str(exc), 409)

    if items:
        case = service.record_clearance(
            case, items, tenant_id=ctx.tenant_id, ok=clearance_ok
        )
    elif clearance_ok:
        case = service.close_exit(case, tenant_id=ctx.tenant_id)

    write_external_audit(
        tenant_id=ctx.tenant_id, action="ExternalEngagementEnded", actor_user_id=ctx.user_id,
        engagement_id=case.engagement_id_id, business_id=str(case.id), source="api",
    )
    body = api_root(request)
    body["data"] = {
        "id": str(case.id),
        "status": case.status,
        "statusLabel": exit_status_label(case.status),
        "note": "权限回收已进入可靠队列；以 IAM 回执确认最终撤权，历史任务、成果、评价和协议继续保留。",
    }
    return json_response(request, body)
