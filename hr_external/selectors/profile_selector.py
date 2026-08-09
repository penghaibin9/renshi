"""
hr_external/selectors/profile_selector.py —— 外聘教师库列表查询（S3，总册 §120）。

硬合同（§120）：
- WHERE → COUNT → ORDER → PAGE；禁止先分页再 Python 过滤或全表拉内存。
- 敏感字段不进普通列表（§91/§127）；身份证等 HIGH_SENSITIVE 由独立受控 endpoint 提供。
- scope 服务端裁剪（§89）：actor scope ∩ assignment scope；不能因 Person 归人才库就全校任意查看。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from django.db.models import Q

from hr_external.constants import ExternalEngagementStatus, ExternalScopeType
from hr_external.models import HrExternalEngagement, HrExternalTeacherProfile

_ACTIVE_ENG_STATUSES = [
    ExternalEngagementStatus.ACTIVE,
    ExternalEngagementStatus.REVIEW_DUE,
    ExternalEngagementStatus.RENEWAL_IN_PROGRESS,
    ExternalEngagementStatus.SIGNED_WAITING_EFFECTIVE,
    ExternalEngagementStatus.SUSPENDED,
]


@dataclass
class ProfileFilterSpec:
    tenant_id: int
    keyword: str = ""
    category_code: str = ""
    source_organization: str = ""
    industry_domain: str = ""
    professional_title: str = ""
    skill_level: str = ""
    has_teacher_qualification: Optional[bool] = None
    pool_status: str = ""  # AVAILABLE/ENGAGED/UNDER_REVIEW/TEMPORARILY_UNAVAILABLE/DO_NOT_ENGAGE/ARCHIVED
    currently_engaged: Optional[bool] = None
    host_organization_id: Optional[int] = None
    page: int = 1
    page_size: int = 50
    order_by: str = "-updated_at"


def _apply_scope(qs, ctx):
    """数据范围裁剪（§89）。S3 支持 SCHOOL/COLLEGE/ORGANIZATION；ENGAGEMENT/SELF 由上层传入。"""
    scope_type = ctx.scope.scope_type if ctx else ExternalScopeType.SCHOOL
    org_id = getattr(ctx.scope, "org_id", None) if ctx else None
    if scope_type in (ExternalScopeType.COLLEGE, ExternalScopeType.ORGANIZATION) and org_id:
        # 学院范围：通过该学院存在 active/planned engagement 的 profile 可见（§89）
        qs = qs.filter(
            id__in=HrExternalEngagement.objects.filter(
                tenant_id=ctx.tenant_id,
                host_organization_id=org_id,
            ).values("external_profile_id")
        )
    return qs


def list_external_profiles(
    spec: ProfileFilterSpec,
    ctx=None,
) -> tuple[int, list[dict]]:
    """返回 (total, items)。WHERE→COUNT→ORDER→PAGE。"""
    qs = HrExternalTeacherProfile.objects.filter(tenant_id=spec.tenant_id).select_related(
        "person_id", "primary_category"
    )

    if spec.keyword:
        qs = qs.filter(
            Q(person_id__legal_name__icontains=spec.keyword)
            | Q(external_teacher_no__icontains=spec.keyword)
        )
    if spec.category_code:
        qs = qs.filter(primary_category__code=spec.category_code)
    if spec.source_organization:
        qs = qs.filter(source_organization_name__icontains=spec.source_organization)
    if spec.industry_domain:
        qs = qs.filter(industry_domain__icontains=spec.industry_domain)
    if spec.professional_title:
        qs = qs.filter(highest_professional_title__icontains=spec.professional_title)
    if spec.skill_level:
        qs = qs.filter(highest_skill_level__icontains=spec.skill_level)
    if spec.has_teacher_qualification is not None:
        if spec.has_teacher_qualification:
            qs = qs.exclude(teacher_qualification_ref="")
        else:
            qs = qs.filter(teacher_qualification_ref="")
    if spec.pool_status:
        qs = qs.filter(candidate_pool_status=spec.pool_status)
    if spec.currently_engaged is not None:
        eng_sub = HrExternalEngagement.objects.filter(
            tenant_id=spec.tenant_id,
            status__in=_ACTIVE_ENG_STATUSES,
        ).values("external_profile_id")
        if spec.currently_engaged:
            qs = qs.filter(id__in=eng_sub)
        else:
            qs = qs.exclude(id__in=eng_sub)

    # scope 裁剪（§89）
    qs = _apply_scope(qs, ctx)

    total = qs.count()
    order_map = {
        "-updated_at": "-updated_at",
        "updated_at": "updated_at",
        "external_teacher_no": "external_teacher_no",
        "-external_teacher_no": "-external_teacher_no",
        "legal_name": "person_id__legal_name",
    }
    order = order_map.get(spec.order_by, "-updated_at")
    qs = qs.order_by(order)
    page = max(1, spec.page)
    page_size = min(200, max(1, spec.page_size))
    offset = (page - 1) * page_size
    rows = qs[offset : offset + page_size]

    items = [_profile_row(p) for p in rows]
    return total, items


def _profile_row(profile: HrExternalTeacherProfile) -> dict:
    """单行序列化（不包含 HIGH_SENSITIVE 字段，§91）。
    DO_NOT_ENGAGE 为敏感业务结论（§25）：普通列表不展示该状态值，返回 "受限" 以免污名化。"""
    category = profile.primary_category
    pool_status = profile.candidate_pool_status
    if pool_status == "DO_NOT_ENGAGE":
        pool_status = "RESTRICTED"
    return {
        "id": str(profile.id),
        "externalTeacherNo": profile.external_teacher_no,
        "personId": str(profile.person_id_id),
        "legalName": profile.person_id.legal_name,
        "preferredName": profile.person_id.preferred_name,
        "category": {"code": category.code if category else "", "name": category.name if category else ""},
        "sourceOrganization": profile.source_organization_name,
        "industryDomain": profile.industry_domain,
        "expertiseTags": profile.expertise_tags or [],
        "highestProfessionalTitle": profile.highest_professional_title,
        "highestSkillLevel": profile.highest_skill_level,
        "poolStatus": pool_status,
        "currentEngagementStatus": profile.current_engagement_status,
        "ethicsStatus": profile.ethics_status,
        "identityVerificationStatus": profile.identity_verification_status,
        "version": profile.version,
        "updatedAt": profile.updated_at.isoformat() if profile.updated_at else None,
    }
