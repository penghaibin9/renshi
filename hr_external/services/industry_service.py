"""
hr_external/services/industry_service.py —— 产业教授/技能大师专项服务（S4，总册 §27/§30/§31）。

- 专项 Profile 1:1 扩展（evidence-backed facts；不把"成果"只写一个大文本）。
- Contribution：DRAFT→SUBMITTED→UNDER_REVIEW→VERIFIED；VERIFIED 为正式结论，不原地改（00 §20）。
- Workspace：技能大师工作室 V1 作为 HR08-02 下级页面。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from django.db import transaction

from hr_external.constants import ContributionStatus
from hr_external.models import (
    HrExternalContribution,
    HrExternalEngagement,
    HrExternalIndustryProfile,
    HrExternalTeacherProfile,
    HrExternalWorkspace,
)


class CrossTenantReference(Exception):
    code = "CROSS_TENANT_REFERENCE"


class IndustryProfileAlreadyExists(Exception):
    code = "INDUSTRY_PROFILE_EXISTS"


class IndustryService:
    @transaction.atomic
    def create_industry_profile(
        self,
        *,
        tenant_id: int,
        profile_id,
        industry_experience_years: Optional[float] = None,
        current_employer: str = "",
        current_industry_role: str = "",
        major_projects: Optional[list] = None,
        patents_products: Optional[list] = None,
        technical_awards: Optional[list] = None,
        enterprise_training_experience: Optional[list] = None,
        industry_association_roles: Optional[list] = None,
        industry_domains: Optional[list] = None,
        skills: Optional[list] = None,
    ) -> HrExternalIndustryProfile:
        profile = HrExternalTeacherProfile.objects.filter(
            tenant_id=tenant_id, id=profile_id
        ).first()
        if profile is None:
            raise CrossTenantReference("EXTERNAL_PROFILE_NOT_FOUND")

        if HrExternalIndustryProfile.objects.filter(profile_id=profile).exists():
            raise IndustryProfileAlreadyExists("industry profile already exists")

        return HrExternalIndustryProfile.objects.create(
            tenant_id=tenant_id,
            profile_id=profile,
            industry_experience_years=industry_experience_years,
            current_employer=current_employer,
            current_industry_role=current_industry_role,
            major_projects=major_projects or [],
            patents_products=patents_products or [],
            technical_awards=technical_awards or [],
            enterprise_training_experience=enterprise_training_experience or [],
            industry_association_roles=industry_association_roles or [],
            industry_domains=industry_domains or [],
            skills=skills or [],
        )

    @transaction.atomic
    def create_contribution(
        self,
        *,
        tenant_id: int,
        engagement_id,
        contribution_type: str,
        title: str,
        period: str = "",
        evidence_ids: Optional[list] = None,
        related_task_ids: Optional[list] = None,
        quantitative_value: Optional[float] = None,
        qualitative_summary: str = "",
    ) -> HrExternalContribution:
        eng = HrExternalEngagement.objects.filter(
            tenant_id=tenant_id, id=engagement_id
        ).first()
        if eng is None:
            raise CrossTenantReference("EXTERNAL_ENGAGEMENT_NOT_FOUND")

        return HrExternalContribution.objects.create(
            tenant_id=tenant_id,
            engagement_id=eng,
            contribution_type=contribution_type,
            title=title,
            period=period,
            evidence_ids=evidence_ids or [],
            related_task_ids=related_task_ids or [],
            quantitative_value=quantitative_value,
            qualitative_summary=qualitative_summary,
            status=ContributionStatus.DRAFT,
        )

    def submit_contribution(self, contribution: HrExternalContribution) -> None:
        """DRAFT→SUBMITTED。之后进入核验流。"""
        if contribution.status != ContributionStatus.DRAFT:
            raise InvalidContributionState("contribution not in DRAFT")
        contribution.status = ContributionStatus.SUBMITTED
        contribution.save(update_fields=["status", "updated_at"])

    def verify_contribution(self, contribution: HrExternalContribution, *, verified: bool) -> None:
        """SUBMITTED/UNDER_REVIEW → VERIFIED/REJECTED。VERIFIED 后不可原地改（00 §20）。"""
        if contribution.status in (ContributionStatus.VERIFIED, ContributionStatus.REJECTED):
            raise InvalidContributionState("contribution already finalized")
        contribution.status = (
            ContributionStatus.VERIFIED if verified else ContributionStatus.REJECTED
        )
        contribution.verification_status = (
            "VERIFIED" if verified else "REJECTED"
        )
        contribution.save(update_fields=["status", "verification_status", "updated_at"])

    @transaction.atomic
    def create_workspace(
        self,
        *,
        tenant_id: int,
        name: str,
        workspace_type: str,
        organization_id: int,
        start_at: date,
        end_at: Optional[date] = None,
        leader_engagement_id=None,
        goals: Optional[list] = None,
        member_refs: Optional[list] = None,
        projects: Optional[list] = None,
    ) -> HrExternalWorkspace:
        if end_at and start_at >= end_at:
            raise InvalidWorkspaceDates("workspace dates invalid")
        return HrExternalWorkspace.objects.create(
            tenant_id=tenant_id,
            name=name,
            workspace_type=workspace_type,
            organization_id=organization_id,
            start_at=start_at,
            end_at=end_at,
            leader_engagement_id_id=leader_engagement_id,
            goals=goals or [],
            member_refs=member_refs or [],
            projects=projects or [],
            status="DRAFT",
        )


class InvalidContributionState(Exception):
    code = "EXTERNAL_TASK_ALREADY_FINALIZED"


class InvalidWorkspaceDates(Exception):
    code = "INVALID_REQUEST"
