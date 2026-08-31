"""
hr_external/api/industry.py —— HR08-02 产业教授与技能大师 API（S4）。

路由（总册 §27.1/§124）：
- GET  /api/hr/v1/external-teachers/industry                列表（产业类别 profile + 专项）
- GET  /api/hr/v1/external-teachers/industry/{engagement_id} 产业专家详情
- GET  /api/hr/v1/external-teachers/industry/workspaces     工作室列表
- POST /api/hr/v1/external-teachers/industry/workspaces     创建工作室
- POST /api/hr/v1/external-teachers/industry/profiles/{profile_id}  创建专项 Profile
- POST /api/hr/v1/external-teachers/engagements/{id}/contributions  创建成果
- POST /api/hr/v1/external-teachers/contributions/{id}/submit   提交核验
- POST /api/hr/v1/external-teachers/contributions/{id}/verify   核验（maker-checker 语义）
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
    HrExternalContribution,
    HrExternalEngagement,
    HrExternalIndustryProfile,
    HrExternalTeacherProfile,
    HrExternalWorkspace,
)
from hr_external.permissions import require_hr_external_permission
from hr_external.services.audit_service import write_external_audit
from hr_external.services.industry_service import (
    CrossTenantReference,
    IndustryProfileAlreadyExists,
    IndustryService,
    InvalidContributionState,
    InvalidWorkspaceDates,
)


def _ctx(request):
    try:
        return make_external_context(request, authority_mode="LEGACY_EMPLOYEE_TAG_ONLY"), None
    except Exception as exc:  # noqa: BLE001
        code = getattr(exc, "code", "INVALID_REQUEST")
        status = 403 if code == "TENANT_CONTEXT_REQUIRED" else 400
        return None, error_response(request, code, str(exc), status)


@require_hr_external_permission("hr08.industry.view")
def industry_list(request):
    """产业类别人才列表。"""
    ctx, err = _ctx(request)
    if err:
        return err

    profiles = (
        HrExternalTeacherProfile.objects.filter(
            tenant_id=ctx.tenant_id,
            primary_category__code__in=[
                "INDUSTRY_PROFESSOR",
                "INDUSTRY_ADJUNCT",
                "SKILL_MASTER",
                "INDUSTRY_MENTOR",
            ],
        )
        .select_related("person_id", "primary_category", "industry_profile")
        .order_by("-updated_at")[:100]
    )

    items = []
    for p in profiles:
        ind = p.industry_profile if hasattr(p, "industry_profile") else None
        items.append(
            {
                "profileId": str(p.id),
                "legalName": p.person_id.legal_name,
                "category": p.primary_category.name if p.primary_category else "",
                "currentEmployer": ind.current_employer if ind else "",
                "currentIndustryRole": ind.current_industry_role if ind else "",
                "industryExperienceYears": float(ind.industry_experience_years) if ind and ind.industry_experience_years is not None else None,
                "industryDomains": ind.industry_domains if ind else [],
                "skills": ind.skills if ind else [],
                "poolStatus": p.candidate_pool_status,
            }
        )

    body = api_root(request)
    body["data"] = {"items": items, "total": len(items)}
    return json_response(request, body)


@require_hr_external_permission("hr08.industry.view")
def industry_engagement_detail(request, engagement_id):
    """产业专家详情：专项 profile + 成果 + 工作室。"""
    ctx, err = _ctx(request)
    if err:
        return err

    eng = (
        HrExternalEngagement.objects.filter(tenant_id=ctx.tenant_id, id=engagement_id)
        .select_related("external_profile_id", "external_profile_id__person_id")
        .first()
    )
    if eng is None:
        return error_response(request, "EXTERNAL_ENGAGEMENT_NOT_FOUND", "聘期不存在", 404)

    ind = HrExternalIndustryProfile.objects.filter(
        tenant_id=ctx.tenant_id, profile_id=eng.external_profile_id
    ).first()
    contributions = HrExternalContribution.objects.filter(
        tenant_id=ctx.tenant_id, engagement_id=eng
    ).order_by("-updated_at")

    body = api_root(request)
    body["data"] = {
        "engagementId": str(eng.id),
        "engagementNo": eng.engagement_no,
        "status": eng.status,
        "person": {
            "profileId": str(eng.external_profile_id_id),
            "legalName": eng.external_profile_id.person_id.legal_name,
        },
        "industryProfile": {
            "currentEmployer": ind.current_employer if ind else "",
            "currentIndustryRole": ind.current_industry_role if ind else "",
            "industryExperienceYears": float(ind.industry_experience_years) if ind and ind.industry_experience_years is not None else None,
            "majorProjects": ind.major_projects if ind else [],
            "patentsProducts": ind.patents_products if ind else [],
            "technicalAwards": ind.technical_awards if ind else [],
            "industryDomains": ind.industry_domains if ind else [],
            "skills": ind.skills if ind else [],
        } if ind else None,
        "contributions": [
            {
                "id": str(c.id),
                "contributionType": c.contribution_type,
                "title": c.title,
                "period": c.period,
                "verificationStatus": c.verification_status,
                "status": c.status,
                "quantitativeValue": float(c.quantitative_value) if c.quantitative_value is not None else None,
            }
            for c in contributions
        ],
    }
    return json_response(request, body)


@require_hr_external_permission("hr08.industry.manage")
def industry_profile_create(request, profile_id):
    """POST /industry/profiles/{profile_id} 创建专项 Profile（§27.3）。"""
    ctx, err = _ctx(request)
    if err:
        return err
    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return error_response(request, "INVALID_REQUEST", "请求体必须是 JSON", 400)

    try:
        ind = IndustryService().create_industry_profile(
            tenant_id=ctx.tenant_id,
            profile_id=profile_id,
            industry_experience_years=payload.get("industryExperienceYears"),
            current_employer=payload.get("currentEmployer") or "",
            current_industry_role=payload.get("currentIndustryRole") or "",
            major_projects=payload.get("majorProjects") or [],
            patents_products=payload.get("patentsProducts") or [],
            technical_awards=payload.get("technicalAwards") or [],
            enterprise_training_experience=payload.get("enterpriseTrainingExperience") or [],
            industry_association_roles=payload.get("industryAssociationRoles") or [],
            industry_domains=payload.get("industryDomains") or [],
            skills=payload.get("skills") or [],
        )
    except (CrossTenantReference, IndustryProfileAlreadyExists) as exc:
        return error_response(request, getattr(exc, "code", "INVALID_REQUEST"), str(exc), 400)

    write_external_audit(
        tenant_id=ctx.tenant_id,
        action="ExternalIndustryProfileCreated",
        actor_user_id=ctx.user_id,
        external_profile_id=profile_id,
        source="api",
    )
    body = api_root(request)
    body["data"] = {"industryProfileId": str(ind.id)}
    return json_response(request, body, status=201)


@require_hr_external_permission("hr08.industry.view")
def workspace_list(request):
    ctx, err = _ctx(request)
    if err:
        return err
    ws = HrExternalWorkspace.objects.filter(tenant_id=ctx.tenant_id).order_by("-updated_at")[:100]
    body = api_root(request)
    body["data"] = {
        "items": [
            {
                "id": str(w.id),
                "name": w.name,
                "workspaceType": w.workspace_type,
                "organizationId": w.organization_id,
                "startAt": w.start_at.isoformat(),
                "endAt": w.end_at.isoformat() if w.end_at else None,
                "status": w.status,
            }
            for w in ws
        ],
        "total": ws.count(),
    }
    return json_response(request, body)


@require_hr_external_permission("hr08.industry.manage")
def workspace_create(request):
    ctx, err = _ctx(request)
    if err:
        return err
    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return error_response(request, "INVALID_REQUEST", "请求体必须是 JSON", 400)

    try:
        ws = IndustryService().create_workspace(
            tenant_id=ctx.tenant_id,
            name=payload.get("name") or "",
            workspace_type=payload.get("workspaceType") or "SKILL_MASTER_WORKSHOP",
            organization_id=payload.get("organizationId"),
            start_at=parse_date(payload["startAt"]) if payload.get("startAt") else None,
            end_at=parse_date(payload["endAt"]) if payload.get("endAt") else None,
            leader_engagement_id=payload.get("leaderEngagementId"),
            goals=payload.get("goals") or [],
            member_refs=payload.get("memberRefs") or [],
            projects=payload.get("projects") or [],
        )
    except (InvalidWorkspaceDates, ValueError) as exc:
        return error_response(request, "INVALID_REQUEST", str(exc), 400)

    write_external_audit(
        tenant_id=ctx.tenant_id,
        action="ExternalWorkspaceCreated",
        actor_user_id=ctx.user_id,
        source="api",
    )
    body = api_root(request)
    body["data"] = {"id": str(ws.id), "name": ws.name, "status": ws.status}
    return json_response(request, body, status=201)


@require_hr_external_permission("hr08.industry.manage")
def contribution_create(request, engagement_id):
    ctx, err = _ctx(request)
    if err:
        return err
    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return error_response(request, "INVALID_REQUEST", "请求体必须是 JSON", 400)

    try:
        c = IndustryService().create_contribution(
            tenant_id=ctx.tenant_id,
            engagement_id=engagement_id,
            contribution_type=payload.get("contributionType") or "OTHER",
            title=payload.get("title") or "",
            period=payload.get("period") or "",
            evidence_ids=payload.get("evidenceIds") or [],
            related_task_ids=payload.get("relatedTaskIds") or [],
            quantitative_value=payload.get("quantitativeValue"),
            qualitative_summary=payload.get("qualitativeSummary") or "",
        )
    except CrossTenantReference as exc:
        return error_response(request, exc.code, str(exc), 400)

    body = api_root(request)
    body["data"] = {"id": str(c.id), "status": c.status}
    return json_response(request, body, status=201)


@require_hr_external_permission("hr08.industry.manage")
def contribution_submit(request, contribution_id):
    ctx, err = _ctx(request)
    if err:
        return err
    c = HrExternalContribution.objects.filter(
        tenant_id=ctx.tenant_id, id=contribution_id
    ).first()
    if c is None:
        return error_response(request, "INVALID_REQUEST", "成果不存在", 404)
    try:
        c = IndustryService().submit_contribution(c, tenant_id=ctx.tenant_id)
    except InvalidContributionState as exc:
        return error_response(request, exc.code, str(exc), 409)
    body = api_root(request)
    body["data"] = {"id": str(c.id), "status": c.status}
    return json_response(request, body)


@require_hr_external_permission("hr08.industry.manage")
def contribution_verify(request, contribution_id):
    ctx, err = _ctx(request)
    if err:
        return err
    try:
        payload = json.loads(request.body or b"{}")
        verified = bool(payload.get("verified", True))
    except json.JSONDecodeError:
        return error_response(request, "INVALID_REQUEST", "请求体必须是 JSON", 400)

    c = HrExternalContribution.objects.filter(
        tenant_id=ctx.tenant_id, id=contribution_id
    ).first()
    if c is None:
        return error_response(request, "INVALID_REQUEST", "成果不存在", 404)
    try:
        c = IndustryService().verify_contribution(
            c, tenant_id=ctx.tenant_id, verified=verified
        )
    except InvalidContributionState as exc:
        return error_response(request, exc.code, str(exc), 409)

    write_external_audit(
        tenant_id=ctx.tenant_id,
        action="ExternalContributionVerified",
        actor_user_id=ctx.user_id,
        business_type="HR08_CONTRIBUTION",
        business_id=str(c.id),
        reason="verify" if verified else "reject",
        source="api",
    )
    body = api_root(request)
    body["data"] = {"id": str(c.id), "status": c.status, "verificationStatus": c.verification_status}
    return json_response(request, body)
