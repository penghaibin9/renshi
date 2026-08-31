"""
hr_external/models/industry.py —— 产业教授/技能大师专项事实（S4，总册 §27/§30/§31）。

§27.3：除普通 External Profile 外，增加 evidence-backed 产业背景事实：
industry_experience_years / current_employer / current_industry_role / major_projects /
patents_products / technical_awards / enterprise_training_experience /
industry_association_roles / industry_domains / skills。

§30：专项成果 HrExternalContribution 结构化（不把"成果"只写一个大文本）。
§31：技能大师工作室 HrExternalWorkspace（V1 作为 HR08-02 下级页面，不新增三级菜单）。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_external.constants import (
    ContributionStatus,
    ContributionType,
    EvidenceVerificationStatus,
    WorkspaceStatus,
    WorkspaceType,
)


class HrExternalIndustryProfile(models.Model):
    """产业/技能大师专项 Profile（§27.3）。1:1 扩展 HrExternalTeacherProfile。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    profile_id = models.OneToOneField(
        "hr_external.HrExternalTeacherProfile",
        on_delete=models.PROTECT,
        related_name="industry_profile",
    )
    industry_experience_years = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True
    )
    current_employer = models.CharField(max_length=200, blank=True, default="")
    current_industry_role = models.CharField(max_length=200, blank=True, default="")
    major_projects = models.JSONField(default=list, blank=True)
    patents_products = models.JSONField(default=list, blank=True)
    technical_awards = models.JSONField(default=list, blank=True)
    enterprise_training_experience = models.JSONField(default=list, blank=True)
    industry_association_roles = models.JSONField(default=list, blank=True)
    industry_domains = models.JSONField(default=list, blank=True)
    skills = models.JSONField(default=list, blank=True)
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR External Industry Profile")
        verbose_name_plural = _("HR External Industry Profiles")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="hex_industry_profile_version_gte_1",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] industry profile {self.profile_id_id}"


class HrExternalContribution(models.Model):
    """专项成果（§30）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    engagement_id = models.ForeignKey(
        "hr_external.HrExternalEngagement",
        on_delete=models.PROTECT,
        related_name="contributions",
    )
    contribution_type = models.CharField(
        max_length=40,
        choices=ContributionType.choices,
        default=ContributionType.OTHER,
    )
    title = models.CharField(max_length=300)
    period = models.CharField(max_length=64, blank=True, default="")
    # 证据文件引用（horilla_documents / 安全存储 ticket 由 S9 文档集成接管）
    evidence_ids = models.JSONField(default=list, blank=True)
    verification_status = models.CharField(
        max_length=24,
        choices=EvidenceVerificationStatus.choices,
        default=EvidenceVerificationStatus.UPLOADED,
    )
    related_task_ids = models.JSONField(default=list, blank=True)
    quantitative_value = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    qualitative_summary = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=ContributionStatus.choices,
        default=ContributionStatus.DRAFT,
    )
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR External Contribution")
        verbose_name_plural = _("HR External Contributions")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="hex_contribution_version_gte_1",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "engagement_id", "verification_status"],
                name="hex_contrib_eng_ver_idx",
            ),
            models.Index(
                fields=["tenant_id", "contribution_type", "status"],
                name="hex_contrib_type_status_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] {self.title} ({self.status})"


class HrExternalWorkspace(models.Model):
    """技能大师/产业工作室（§31）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    name = models.CharField(max_length=200)
    workspace_type = models.CharField(
        max_length=32,
        choices=WorkspaceType.choices,
        default=WorkspaceType.SKILL_MASTER_WORKSHOP,
    )
    leader_engagement_id = models.ForeignKey(
        "hr_external.HrExternalEngagement",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="led_workspaces",
    )
    organization_id = models.BigIntegerField(db_index=True)
    start_at = models.DateField()
    end_at = models.DateField(null=True, blank=True)
    goals = models.JSONField(default=list, blank=True)
    member_refs = models.JSONField(default=list, blank=True)
    projects = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=16,
        choices=WorkspaceStatus.choices,
        default=WorkspaceStatus.DRAFT,
    )
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR External Workspace")
        verbose_name_plural = _("HR External Workspaces")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_at__isnull=True)
                | models.Q(start_at__lt=models.F("end_at")),
                name="hex_workspace_dates_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="hex_workspace_version_gte_1",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "workspace_type", "status"],
                name="hex_workspace_type_status_idx",
            ),
            models.Index(
                fields=["tenant_id", "organization_id", "status"],
                name="hex_workspace_org_status_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] {self.name} ({self.status})"
