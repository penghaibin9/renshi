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
from hr_recruitment.constants import HandoffStatus
from hr_recruitment.integrations.hr05 import Hr05OnboardingConsumer
from hr_recruitment.labels import PROPOSED_HIRE_STATUS_LABELS, status_label
from hr_recruitment.permissions import require_hr04_permission
from hr_recruitment.services.handoff_service import HandoffService, HandoffServiceError
from hr_recruitment.services.hiring_authority_service import (
    HiringAuthorityError,
    HiringAuthorityService,
    HiringRevisionInput,
    effective_hiring_decision_snapshot,
)
from hr_recruitment.services.notice_service import NoticeService, NoticeServiceError
from hr_recruitment.services.offer_service import OfferService, OfferServiceError, offer_snapshot
from hr_recruitment.services.proposed_hire_service import (
    ProposedHireService,
    ProposedHireServiceError,
)


def _handle(request, exc):
    from django.core.exceptions import ObjectDoesNotExist

    if isinstance(exc, json.JSONDecodeError):
        return error(request, "INVALID_JSON", "请求体不是有效 JSON", 400)
    if isinstance(exc, ObjectDoesNotExist):
        return error(request, "NOT_FOUND", "资源不存在", 404)
    if isinstance(
        exc,
        (
            Hr04ApiError,
            ProposedHireServiceError,
            NoticeServiceError,
            OfferServiceError,
            HandoffServiceError,
            HiringAuthorityError,
        ),
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
    from hr_recruitment.constants import ApplicationCanonicalStatus as S
    from hr_recruitment.models import (
        HrJobApplication,
        HrProposedHire,
        HrPublicNoticeEntry,
        HrRecruitmentHandoff,
        HrRecruitmentOffer,
        HrSelectionResultSnapshot,
    )

    from django.core.paginator import Paginator
    from django.db.models import Q, F, OuterRef, Subquery, Exists
    try:
        page_no = max(1, int(request.GET.get("page", 1)))
        eligible_page = max(1, int(request.GET.get("eligiblePage", 1)))
        page_size = max(1, min(100, int(request.GET.get("pageSize", 20))))
    except (ValueError, TypeError):
        return error(request, "PAGINATION_INVALID", "分页参数必须为整数", 422)
    keyword = request.GET.get("keyword", "").strip()[:200]
    query = HrProposedHire.objects.filter(
        tenant_id=ctx.tenant_id, application_id__tenant_id=ctx.tenant_id,
        application_id__candidate_id__tenant_id=ctx.tenant_id, recruitment_position_id__tenant_id=ctx.tenant_id,
        application_id__recruitment_position_id=F("recruitment_position_id"),
    )
    if keyword:
        query = query.filter(Q(application_id__candidate_id__legal_name__icontains=keyword)
            | Q(application_id__application_no__icontains=keyword) | Q(recruitment_position_id__post_catalog_name__icontains=keyword))
    pager = Paginator(query.select_related("application_id__candidate_id", "recruitment_position_id").order_by("-created_at", "-id"), page_size)
    selected = pager.get_page(page_no)
    items = list(selected)
    ids = [x.id for x in items]
    # At most three child queries for the current page (not 3 queries per row).
    notices, offers, handoffs = {}, {}, {}
    for n in HrPublicNoticeEntry.objects.filter(tenant_id=ctx.tenant_id, proposed_hire_id_id__in=ids,
            notice_id__tenant_id=ctx.tenant_id).select_related("notice_id").order_by("-notice_id__published_at", "-id"):
        notices.setdefault(n.proposed_hire_id_id, n)
    for o in HrRecruitmentOffer.objects.filter(tenant_id=ctx.tenant_id, proposed_hire_id_id__in=ids).order_by("-created_at", "-id"):
        offers.setdefault(o.proposed_hire_id_id, o)
    for h in HrRecruitmentHandoff.objects.filter(tenant_id=ctx.tenant_id, proposed_hire_id_id__in=ids).order_by("-handoff_at", "-id"):
        handoffs.setdefault(h.proposed_hire_id_id, h)
    # Exclude ALL existing proposals, not only those on the displayed page.
    existing = HrProposedHire.objects.filter(tenant_id=ctx.tenant_id, application_id_id=OuterRef("application_id_id"))
    latest = HrSelectionResultSnapshot.objects.filter(tenant_id=ctx.tenant_id,
        application_id_id=OuterRef("application_id_id")).order_by("-snapshot_version", "-calculated_at", "-id")
    snapshots = HrSelectionResultSnapshot.objects.filter(tenant_id=ctx.tenant_id,
        application_id__tenant_id=ctx.tenant_id, application_id__candidate_id__tenant_id=ctx.tenant_id,
        recruitment_position_id__tenant_id=ctx.tenant_id, application_id__canonical_status=S.QUALIFIED,
        application_id__recruitment_position_id=F("recruitment_position_id"),
    ).annotate(already_proposed=Exists(existing), latest_id=Subquery(latest.values("id")[:1])).filter(
        already_proposed=False, id=F("latest_id"))
    if keyword:
        snapshots=snapshots.filter(Q(application_id__candidate_id__legal_name__icontains=keyword)
            | Q(application_id__application_no__icontains=keyword) | Q(recruitment_position_id__post_catalog_name__icontains=keyword))
    ep = Paginator(snapshots.select_related("application_id__candidate_id", "recruitment_position_id").order_by("-calculated_at", "-id"), page_size)
    es = ep.get_page(eligible_page)
    eligible = [{"application_id": str(x.application_id_id), "application_no": x.application_id.application_no,
        "candidate_name": x.application_id.candidate_id.legal_name, "position": x.recruitment_position_id.post_catalog_name,
        "rank": x.rank, "final_score": str(x.final_score), "reservation_id": x.recruitment_position_id.reservation_id,
        "reservation_no": x.recruitment_position_id.reservation_no} for x in es]
    can_offer = request.user.is_superuser or request.user.has_perm("hr04.offer.manage")
    rows=[]
    for p in items:
        n,o,h=notices.get(p.id),offers.get(p.id),handoffs.get(p.id)
        rows.append({"id":str(p.id), "application_id":str(p.application_id_id),
            "application_no":p.application_id.application_no, "campaign_id":str(p.recruitment_position_id.campaign_id_id),
            "rank":p.rank, "final_score":str(p.final_score), "approval_status":p.approval_status,
            "approvalStatusLabel":status_label(PROPOSED_HIRE_STATUS_LABELS,p.approval_status),
            "candidate_name":p.application_id.candidate_id.legal_name, "position":p.recruitment_position_id.post_catalog_name,
            "reservation_id":p.reservation_id or "", "notice_id":str(n.notice_id_id) if n else "",
            "notice_status":n.notice_id.status if n else "", "offer_id":str(o.id) if o else "",
            "offer_status":o.status if o else "", "offer_snapshot":offer_snapshot(o) if o and can_offer else None,
            "handoff_id":str(h.id) if h else "", "handoff_status":h.status if h else "",
            "hr05_case_id":h.hr05_case_id if h else "", "created_at":p.created_at.isoformat()})
    return ok(request, {"items":rows, "eligible_applications":eligible,
        "page":selected.number, "pageSize":page_size, "total":pager.count, "hasNext":selected.has_next(),
        "eligiblePage":es.number, "eligibleTotal":ep.count, "eligibleHasNext":es.has_next(), "can_manage_offer":bool(can_offer)})


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


@require_http_methods(["POST"])
def transition_offer(request, offer_id):
    """Advance an Offer through its explicit approved/issued/viewed lifecycle."""
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.offer.manage")):
        return error(request, "PERMISSION_DENIED", "无推进 Offer 状态权限", 403)
    try:
        body = json.loads(request.body or b"{}")
        if not isinstance(body, dict): return error(request, "INVALID_JSON", "请求必须为对象", 422)
        fingerprint = request.headers.get("If-Match", "").strip('"')
        if not fingerprint: return error(request, "OFFER_VERSION_REQUIRED", "请读取并核对通知内容后再提交", 422)
        offer = OfferService(tenant_id=ctx.tenant_id, actor=str(request.user.id)).transition(
            offer_id=offer_id, target=body.get("target"), expected_fingerprint=fingerprint,
        )
        return ok(request, {"id": str(offer.id), "status": offer.status, "offer_snapshot": offer_snapshot(offer)})
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_http_methods(["GET", "POST"])
def hiring_decision_revisions(request, fact_id):
    """Read the effective fact or append a controlled correction/revocation."""

    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if request.method == "GET":
        if not (
            request.user.is_superuser
            or request.user.has_perm("hr04.offer.manage")
        ):
            return error(request, "PERMISSION_DENIED", "无查看录用事实权限", 403)
        from hr_recruitment.models import HrHiringDecisionFact

        fact = HrHiringDecisionFact.objects.filter(
            id=fact_id,
            tenant_id=ctx.tenant_id,
        ).first()
        if fact is None:
            return error(request, "HIRING_FACT_NOT_FOUND", "录用事实不存在", 404)
        return ok(
            request,
            {
                "factId": str(fact.id),
                "contentHash": fact.content_hash,
                "sealedAt": fact.sealed_at.isoformat(),
                "effective": effective_hiring_decision_snapshot(fact),
            },
        )

    try:
        body = json.loads(request.body or b"{}")
        revision_type = str(body.get("revisionType") or "").strip().upper()
        required_permission = (
            "hr04.hiring_decision.revoke"
            if revision_type == "REVOCATION"
            else "hr04.hiring_decision.correct"
        )
        if not (
            request.user.is_superuser
            or request.user.has_perm(required_permission)
        ):
            return error(request, "PERMISSION_DENIED", "无录用事实更正/撤销权限", 403)
        revision = HiringAuthorityService(
            tenant_id=ctx.tenant_id,
            actor_id=str(request.user.id),
        ).append_revision(
            fact_id=fact_id,
            payload=HiringRevisionInput(
                correction_no=body.get("correctionNo", ""),
                expected_version=body.get("expectedVersion"),
                revision_type=revision_type,
                reason=body.get("reason", ""),
                changes=body.get("changes", {}),
                evidence_ref=body.get("evidenceRef", ""),
            ),
        )
        return ok(
            request,
            {
                "factId": str(revision.fact_id),
                "revisionId": str(revision.id),
                "previousVersion": revision.previous_version,
                "newVersion": revision.new_version,
                "revisionType": revision.revision_type,
                "contentHash": revision.content_hash,
                "sealedAt": revision.sealed_at.isoformat(),
                "effective": revision.after_snapshot_json,
            },
            status=201,
        )
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
        consumer = Hr05OnboardingConsumer(actor_user_id=request.user.id)
        handoff = service.handoff(
            proposed_hire_id=proposed_hire_id,
            idempotency_key=idempotency_key,
            hr05_consumer=consumer,
        )
        if handoff.status != HandoffStatus.CREATED:
            return error(
                request,
                "HANDOFF_NOT_COMPLETED",
                "HR05 交接未完成，招聘申请未进入交接终态",
                409,
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
