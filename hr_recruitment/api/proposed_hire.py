"""
hr_recruitment/api/proposed_hire.py

HR04-06 录用 API（总册 13）。

  GET  /api/hr/v1/recruitment/proposed-hires            拟录用工作台
  POST /api/hr/v1/recruitment/proposed-hires            创建拟录用
  POST /api/hr/v1/recruitment/proposed-hires/{id}/decide 决策（APPROVE/REJECT/WITHDRAW）
  POST /api/hr/v1/recruitment/notices                   发布公示
  POST /api/hr/v1/recruitment/notices/{id}/close        关闭公示
  POST /api/hr/v1/recruitment/notices/{id}/objections   接收异议
  POST /api/hr/v1/recruitment/offers                    创建 Offer
  POST /api/hr/v1/recruitment/offers/{id}/accept        接受（幂等）
  POST /api/hr/v1/recruitment/proposed-hires/{id}/handoff-to-hr05   HR05 handoff（Idempotency-Key）

硬规则：handoff 前置条件 + 幂等；Offer 接受幂等；公示白名单字段。
"""

from __future__ import annotations

import json

from django.views.decorators.http import require_GET, require_http_methods, require_POST

from hr_recruitment.api.base import (
    error,
    get_idempotency_key,
    make_hr04_context,
    ok,
)
from hr_recruitment.api.exceptions import Hr04ApiError
from hr_recruitment.labels import PROPOSED_HIRE_STATUS_LABELS, status_label
from hr_recruitment.permissions import require_hr04_permission
from hr_recruitment.services.handoff_service import HandoffService, HandoffServiceError
from hr_recruitment.services.notice_service import NoticeService, NoticeServiceError
from hr_recruitment.services.offer_service import OfferService, OfferServiceError
from hr_recruitment.services.proposed_hire_service import (
    ProposedHireService,
    ProposedHireServiceError,
)


def _handle(request, exc):
    from django.core.exceptions import ObjectDoesNotExist

    if isinstance(exc, ObjectDoesNotExist):
        return error(request, "NOT_FOUND", "资源不存在", 404)
    if isinstance(
        exc,
        (Hr04ApiError, ProposedHireServiceError, NoticeServiceError, OfferServiceError, HandoffServiceError),
    ):
        return error(request, exc.code, exc.message, getattr(exc, "http_status", exc.status_code if hasattr(exc, "status_code") else 422))
    return error(request, "INTERNAL_ERROR", "服务器内部错误", 500)


@require_GET
def proposed_hire_list(request):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.proposed_hire.manage")):
        return error(request, "PERMISSION_DENIED", "无查看拟录用权限", 403)
    from hr_recruitment.models import HrProposedHire

    items = HrProposedHire.objects.filter(
        tenant_id=ctx.tenant_id
    ).select_related("application_id__candidate_id", "recruitment_position_id").order_by(
        "-created_at"
    )[:100]
    return ok(
        request,
        {
            "items": [
                {
                    "id": str(p.id),
                    "rank": p.rank,
                    "final_score": str(p.final_score),
                    "approval_status": p.approval_status,
                    "approvalStatusLabel": status_label(PROPOSED_HIRE_STATUS_LABELS, p.approval_status),
                    "candidate_name": p.application_id.candidate_id.legal_name if p.application_id and p.application_id.candidate_id else "",
                    "position": p.recruitment_position_id.post_catalog_name if p.recruitment_position_id else "",
                    "reservation_id": p.reservation_id or "",
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                }
                for p in items
            ]
        },
        status=200,
    )


@require_http_methods(["POST"])
def create_proposed_hire(request):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.proposed_hire.manage")):
        return error(request, "PERMISSION_DENIED", "无创建拟录用权限", 403)
    try:
        body = json.loads(request.body or b"{}")
        service = ProposedHireService(tenant_id=ctx.tenant_id, actor=str(request.user.id))
        proposed = service.create(
            application_id=body.get("application_id"),
            rank=body.get("rank"),
            reservation_id=body.get("reservation_id", ""),
            reservation_no=body.get("reservation_no", ""),
            decision_reason=body.get("decision_reason", ""),
        )
        return ok(request, {"id": str(proposed.id), "approval_status": proposed.approval_status}, status=201)
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_http_methods(["POST"])
def decide_proposed_hire(request, proposed_hire_id):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.proposed_hire.manage")):
        return error(request, "PERMISSION_DENIED", "无审批拟录用权限", 403)
    try:
        body = json.loads(request.body or b"{}")
        service = ProposedHireService(tenant_id=ctx.tenant_id, actor=str(request.user.id))
        proposed = service.decide(
            proposed_hire_id=proposed_hire_id,
            decision=body.get("decision"),
            reason=body.get("reason", ""),
            approving_user=body.get("approving_user", ""),
        )
        return ok(request, {"id": str(proposed.id), "approval_status": proposed.approval_status})
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_http_methods(["POST"])
def publish_notice(request):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.public_notice.publish")):
        return error(request, "PERMISSION_DENIED", "无发布公示权限", 403)
    try:
        body = json.loads(request.body or b"{}")
        service = NoticeService(tenant_id=ctx.tenant_id, actor=str(request.user.id))
        notice = service.publish_notice(
            campaign_id=body.get("campaign_id"),
            notice_no=body.get("notice_no"),
            entries=body.get("entries"),
        )
        return ok(request, {"id": str(notice.id), "status": notice.status}, status=201)
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_http_methods(["POST"])
def close_notice(request, notice_id):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.public_notice.publish")):
        return error(request, "PERMISSION_DENIED", "无关闭公示权限", 403)
    try:
        body = json.loads(request.body or b"{}")
        service = NoticeService(tenant_id=ctx.tenant_id, actor=str(request.user.id))
        notice = service.close_notice(notice_id=notice_id, has_blocker=body.get("has_blocker", False))
        return ok(request, {"id": str(notice.id), "status": notice.status})
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_http_methods(["POST"])
def receive_objection(request, notice_id):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.proposed_hire.manage")):
        return error(request, "PERMISSION_DENIED", "无接收异议权限", 403)
    try:
        body = json.loads(request.body or b"{}")
        service = NoticeService(tenant_id=ctx.tenant_id, actor=str(request.user.id))
        objection = service.receive_objection(
            notice_id=notice_id,
            proposed_hire_id=body.get("proposed_hire_id"),
            source=body.get("source", ""),
            category=body.get("category", ""),
            content=body.get("content", ""),
            evidence=body.get("evidence", ""),
        )
        return ok(request, {"id": str(objection.id), "status": objection.status}, status=201)
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_http_methods(["POST"])
def create_offer(request):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.offer.manage")):
        return error(request, "PERMISSION_DENIED", "无创建 Offer 权限", 403)
    try:
        body = json.loads(request.body or b"{}")
        service = OfferService(tenant_id=ctx.tenant_id, actor=str(request.user.id))
        offer = service.create_offer(
            proposed_hire_id=body.get("proposed_hire_id"),
            offer_no=body.get("offer_no"),
            employment_type=body.get("employment_type", ""),
            expected_report_date=body.get("expected_report_date"),
            expires_in_days=body.get("expires_in_days", 7),
        )
        return ok(request, {"id": str(offer.id), "status": offer.status}, status=201)
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_http_methods(["POST"])
def accept_offer(request, offer_id):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.offer.manage")):
        return error(request, "PERMISSION_DENIED", "无接受 Offer 权限", 403)
    try:
        service = OfferService(tenant_id=ctx.tenant_id, actor=str(request.user.id))
        offer = service.accept(offer_id=offer_id)
        return ok(request, {"id": str(offer.id), "status": offer.status})
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_POST
def handoff_to_hr05(request, proposed_hire_id):
    """
    POST /api/hr/v1/recruitment/proposed-hires/{id}/handoff-to-hr05
    Idempotency-Key 必须；重复调用返回同一 HR05 case。
    """
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.handoff_hr05")):
        return error(request, "PERMISSION_DENIED", "无 HR05 交接权限", 403)
    idempotency_key = get_idempotency_key(request)
    if not idempotency_key:
        return error(request, "IDEMPOTENCY_KEY_REQUIRED", "handoff 必须携带 Idempotency-Key", 422)
    try:
        service = HandoffService(tenant_id=ctx.tenant_id, actor=str(request.user.id))
        handoff = service.handoff(
            proposed_hire_id=proposed_hire_id,
            idempotency_key=idempotency_key,
        )
        return ok(
            request,
            {
                "handoff_id": str(handoff.id),
                "handoff_at": handoff.handoff_at.isoformat() if handoff.handoff_at else None,
                "hr05_case_id": handoff.hr05_case_id,
                "status": handoff.status,
            },
            status=201,
        )
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)
