"""
hr_recruitment/public/views.py

招聘公开门户 API（S5）。

A0 硬门：
- 公开入口由 campaign public_token 解析学校，禁止客户端传 tenant_id。
- public endpoint 不得枚举 ID 访问其他学校招聘。
- 候选人只能看到本人数据。
- public 候选账号与员工/HR 账号隔离（无需登录，用身份因子绑定本人申请）。

端点：
  GET  /recruit/{token}                           公开岗位列表
  GET  /recruit/{token}/positions/{position_slug} 岗位详情
  POST /recruit/{token}/apply                     提交申请（幂等，Idempotency-Key）
  GET  /recruit/my-applications                   按 email+mobile 查本人申请
"""

from __future__ import annotations

import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from hr_recruitment.api.base import (
    error,
    get_idempotency_key,
    ok,
)
from hr_recruitment.api.exceptions import Hr04ApiError
from hr_recruitment.constants import ApplicationCanonicalStatus, CampaignStatus
from hr_recruitment.models import HrJobApplication, HrRecruitmentCampaign, HrRecruitmentPosition
from hr_recruitment.services.application_service import ApplicationService
from hr_recruitment.services.candidate_service import CandidateService


def _resolve_campaign(token: str) -> HrRecruitmentCampaign | None:
    """A0：由公开 token 解析 campaign（含 tenant），禁止客户端传 tenant_id。"""
    return HrRecruitmentCampaign.objects.filter(
        public_token=token,
        status__in=[CampaignStatus.PUBLISHED, CampaignStatus.OPEN, CampaignStatus.RESULT_PROCESSING],
    ).first()


def _handle(request, exc):
    if isinstance(exc, Hr04ApiError):
        return error(request, exc.code, exc.message, exc.status_code)
    return error(request, "INTERNAL_ERROR", "服务器内部错误", 500)


@require_GET
def public_campaign(request, token):
    """公开门户岗位列表页（HTML 默认；?format=json 返回岗位 JSON 供 JS 加载）。"""
    campaign = _resolve_campaign(token)
    if campaign is None:
        return error(request, "CAMPAIGN_NOT_FOUND", "招聘项目不存在或未开放", 404)
    if request.GET.get("format") == "json":
        positions = HrRecruitmentPosition.objects.filter(
            tenant_id=campaign.tenant_id, campaign_id=campaign
        ).exclude(status__in=["CANCELLED"])
        return ok(
            request,
            {
                "campaign": {
                    "title": campaign.title,
                    "description": campaign.description,
                },
                "positions": [
                    {
                        "id": str(p.id),
                        "slug": p.public_slug,
                        "post_catalog_name": p.post_catalog_name,
                        "organization_name": p.organization_name,
                        "description": p.description,
                        "max_hires": p.max_hires,
                        "status": p.status,
                    }
                    for p in positions
                ],
            },
        )
    from django.shortcuts import render

    return render(
        request,
        "hr/recruitment/portal/campaign.html",
        {"token": token, "campaign": campaign},
    )


@require_GET
def public_position(request, token, position_slug):
    campaign = _resolve_campaign(token)
    if campaign is None:
        return error(request, "CAMPAIGN_NOT_FOUND", "招聘项目不存在或未开放", 404)
    position = HrRecruitmentPosition.objects.filter(
        tenant_id=campaign.tenant_id,
        campaign_id=campaign,
        public_slug=position_slug,
    ).first()
    if position is None:
        return error(request, "POSITION_NOT_FOUND", "岗位不存在", 404)
    return ok(
        request,
        {
            "id": str(position.id),
            "post_catalog_name": position.post_catalog_name,
            "organization_name": position.organization_name,
            "description": position.description,
            "planned_headcount": position.planned_headcount,
            "status": position.status,
        },
    )


@csrf_exempt
@require_http_methods(["POST"])
def public_apply(request, token):
    """
    公开提交申请（幂等）。

    A0：token 解析学校；body 不得含 tenant_id。
    流程：创建候选 → save draft → submit（冻结版本 + ledger + application_no）。
    """
    campaign = _resolve_campaign(token)
    if campaign is None:
        return error(request, "CAMPAIGN_NOT_FOUND", "招聘项目不存在或未开放", 404)
    try:
        body = json.loads(request.body or b"{}")
        position_id = body.get("position_id")
        position = HrRecruitmentPosition.objects.filter(
            tenant_id=campaign.tenant_id, id=position_id, campaign_id=campaign
        ).first()
        if position is None:
            return error(request, "POSITION_NOT_FOUND", "岗位不存在", 404)

        legal_name = body.get("legal_name")
        primary_email = body.get("primary_email")
        if not legal_name or not primary_email:
            return error(request, "INVALID_REQUEST", "姓名和邮箱必填", 422)

        candidate_service = CandidateService(tenant_id=campaign.tenant_id, actor="public")
        # 复用已有候选（按 email POSSIBLE_MATCH），避免重复创建
        match = candidate_service.identity_match(primary_email=primary_email)
        if match["match_result"] in ("POSSIBLE_MATCH", "EXACT_MATCH") and match["matches"]:
            from hr_recruitment.models import HrRecruitmentCandidate

            candidate = HrRecruitmentCandidate.objects.get(id=match["matches"][0]["id"])
        else:
            candidate = candidate_service.create_candidate(
                legal_name=legal_name,
                preferred_name=body.get("preferred_name", ""),
                primary_email=primary_email,
                primary_mobile=body.get("primary_mobile", ""),
                national_id=body.get("national_id"),
                source="PUBLIC_PORTAL",
            )

        application_service = ApplicationService(tenant_id=campaign.tenant_id, actor="")
        # 幂等重放：同候选+同岗位已有 active 申请 → 直接返回（不重复创建/不重复提交）
        existing = HrJobApplication.objects.filter(
            tenant_id=campaign.tenant_id,
            candidate_id_id=candidate.id,
            recruitment_position_id_id=position.id,
            is_active=True,
        ).first()
        if existing is not None:
            return ok(
                request,
                {
                    "application_no": existing.application_no,
                    "canonical_status": existing.canonical_status,
                    "candidate_uid": candidate.candidate_uid,
                    "replayed": True,
                },
                status=201,
            )
        draft = application_service.save_draft(
            candidate_id=str(candidate.id),
            recruitment_position_id=str(position.id),
            form_data=body.get("form_data"),
        )
        app = application_service.submit(
            application_id=str(draft.id),
            idempotency_key=get_idempotency_key(request),
        )
        return ok(
            request,
            {
                "application_no": app.application_no,
                "canonical_status": app.canonical_status,
                "candidate_uid": candidate.candidate_uid,
            },
            status=201,
        )
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@csrf_exempt
@require_http_methods(["POST"])
def public_my_applications(request):
    """
    候选人本人申请查询（self scope）。

    身份因子：email + mobile（候选账号体系与员工隔离）。
    只返回该候选本人的申请；不泄漏其他候选人。
    """
    try:
        body = json.loads(request.body or b"{}")
        primary_email = (body.get("primary_email") or "").strip().lower()
        primary_mobile = body.get("primary_mobile") or ""
        if not primary_email:
            return error(request, "INVALID_REQUEST", "邮箱必填", 422)
        from hr_recruitment.models import HrRecruitmentCandidate

        candidates = HrRecruitmentCandidate.objects.filter(
            primary_email__iexact=primary_email
        )
        if primary_mobile:
            candidates = candidates.filter(primary_mobile=primary_mobile)
        candidate = candidates.first()
        if candidate is None:
            return ok(request, {"applications": []})
        applications = HrJobApplication.objects.filter(
            tenant_id=candidate.tenant_id, candidate_id=candidate
        ).select_related("recruitment_position_id")
        return ok(
            request,
            {
                "candidate_uid": candidate.candidate_uid,
                "applications": [
                    {
                        "application_no": a.application_no,
                        "canonical_status": a.canonical_status,
                        "position": a.recruitment_position_id.post_catalog_name
                        if a.recruitment_position_id
                        else "",
                        "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
                    }
                    for a in applications
                ],
            },
        )
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)
