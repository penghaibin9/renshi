"""
hr_recruitment/models/campaign.py

HR04-02 招聘项目与岗位（《04_HR04_总册》§9）。

HrRecruitmentCampaign
  ├─ HrRecruitmentPosition
  │    ├─ HrRecruitmentAnnouncementVersion
  │    ├─ HrQualificationRuleSetVersion
  │    └─ HrSelectionSchemeVersion
  └─ (公告挂在 campaign 层，§9.3)

硬规则：
- public_slug 是公开入口 tenant 解析键（§56.12），禁止客户端传 tenant_id。
- 公告/资格条件/评分方案发布后 immutable；修改走新版本 + amendment（§51）。
- vacancy 只作兼容展示值，额度权威在 HR02 Reservation（§9.7）。
- HR02 预占接口未稳定交付前 position_id/position_pool_id 保持 nullable（LEGACY_CURRENT_SNAPSHOT）。
"""

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_recruitment.constants import (
    CampaignStatus,
    CampaignType,
    RecruitmentPositionStatus,
)


class HrRecruitmentCampaign(models.Model):
    """招聘批次/项目。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    code = models.CharField(max_length=64)
    title = models.CharField(max_length=200)
    campaign_type = models.CharField(
        max_length=32, choices=CampaignType.choices, default=CampaignType.MULTI_POSITION
    )
    plan_cycle_id = models.UUIDField(
        null=True, blank=True, db_index=True
    )  # HrHiringPlanCycle（UUID），弱引用避免迁移耦合
    status = models.CharField(
        max_length=24, choices=CampaignStatus.choices, default=CampaignStatus.DRAFT
    )
    public_slug = models.SlugField(max_length=100, blank=True, default="")
    # 公开门户 token（A0：公开入口由 token 解析学校，禁止客户端传 tenant_id）
    public_token = models.CharField(max_length=64, unique=True, blank=True, default="")
    application_open_at = models.DateTimeField(null=True, blank=True)
    application_close_at = models.DateTimeField(null=True, blank=True)
    timezone = models.CharField(max_length=64, default="Asia/Shanghai")
    description = models.TextField(blank=True, default="")
    manager_employee_ids = models.JSONField(default=list, blank=True)
    legacy_recruitment_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    authority_mode = models.CharField(
        max_length=32, default="LEGACY_RECRUITING_ONLY"
    )
    version = models.PositiveIntegerField(default=1)
    created_by = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Recruitment Campaign")
        verbose_name_plural = _("Recruitment Campaigns")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "code"],
                name="uniq_hr_campaign_tenant_code",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "status"]),
            models.Index(fields=["tenant_id", "public_slug"]),
        ]

    def __str__(self):
        return f"{self.code} {self.title} [{self.status}]"


class HrRecruitmentPosition(models.Model):
    """招聘岗位（招聘域岗位，≠ HR02 岗位目录）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    campaign_id = models.ForeignKey(
        HrRecruitmentCampaign,
        on_delete=models.PROTECT,
        related_name="positions",
        verbose_name=_("Campaign"),
    )
    hiring_plan_line_id = models.UUIDField(null=True, blank=True, db_index=True)
    organization_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    organization_name = models.CharField(max_length=200, blank=True, default="")
    post_catalog_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    post_catalog_name = models.CharField(max_length=200, blank=True, default="")
    # HR02 岗位预占（S4 接入）
    position_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    position_pool_id = models.BigIntegerField(null=True, blank=True)
    reservation_id = models.CharField(max_length=128, blank=True, default="")
    reservation_no = models.CharField(max_length=64, blank=True, default="")
    planned_headcount = models.PositiveIntegerField(default=1)
    reserved_headcount = models.PositiveIntegerField(default=0)
    min_hires = models.PositiveIntegerField(default=1)
    max_hires = models.PositiveIntegerField(default=1)
    status = models.CharField(
        max_length=24,
        choices=RecruitmentPositionStatus.choices,
        default=RecruitmentPositionStatus.DRAFT,
    )
    public_slug = models.SlugField(max_length=100, blank=True, default="")
    position_scheme_version_id = models.UUIDField(null=True, blank=True, db_index=True)
    qualification_rule_version_id = models.UUIDField(null=True, blank=True, db_index=True)
    selection_scheme_version_id = models.UUIDField(null=True, blank=True, db_index=True)
    description = models.TextField(blank=True, default="")
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Recruitment Position")
        verbose_name_plural = _("Recruitment Positions")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(planned_headcount__gte=0)
                & models.Q(reserved_headcount__gte=0)
                & models.Q(min_hires__gte=0)
                & models.Q(max_hires__gte=1),
                name="ck_hr_position_headcount_nonneg",
            ),
            models.UniqueConstraint(
                fields=["tenant_id", "campaign_id", "public_slug"],
                name="uniq_hr_position_slug_per_campaign",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "campaign_id", "status"]),
            models.Index(fields=["tenant_id", "public_slug"]),
        ]

    def __str__(self):
        return f"{self.post_catalog_name} [{self.status}]"

    def scheme_tie_break_rule(self) -> dict | None:
        """当前 ACTIVE 评分方案的 tie-break 规则（§39 排名并列处理）。"""
        from hr_recruitment.models import HrSelectionSchemeVersion

        scheme = (
            HrSelectionSchemeVersion.objects.filter(
                tenant_id=self.tenant_id,
                recruitment_position_id=self,
                status="ACTIVE",
            )
            .order_by("-version_no")
            .first()
        )
        if scheme and scheme.tie_break_rule_json:
            return scheme.tie_break_rule_json
        return None


class HrRecruitmentAnnouncementVersion(models.Model):
    """招聘公告版本（发布后 immutable；amendment 新建版本）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    campaign_id = models.ForeignKey(
        HrRecruitmentCampaign,
        on_delete=models.PROTECT,
        related_name="announcement_versions",
        verbose_name=_("Campaign"),
    )
    version_no = models.PositiveIntegerField(default=1)
    title = models.CharField(max_length=300, default="")
    content = models.TextField(blank=True, default="")
    attachment_ids = models.JSONField(default=list, blank=True)
    effective_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    change_reason = models.TextField(blank=True, default="")
    supersedes_id = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="superseded_by",
    )
    immutable_after_publish = models.BooleanField(default=True)
    created_by = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Recruitment Announcement Version")
        verbose_name_plural = _("Recruitment Announcement Versions")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "campaign_id", "version_no"],
                name="uniq_hr_announcement_tenant_campaign_version",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "campaign_id", "version_no"]),
        ]

    def __str__(self):
        return f"{self.campaign_id} v{self.version_no}"


class HrQualificationRuleSetVersion(models.Model):
    """资格条件规则集版本（LOCKED 后不可变；版本变化不重写旧申请）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    recruitment_position_id = models.ForeignKey(
        HrRecruitmentPosition,
        on_delete=models.PROTECT,
        related_name="qualification_versions",
        verbose_name=_("Recruitment Position"),
    )
    version_no = models.PositiveIntegerField(default=1)
    status = models.CharField(
        max_length=16,
        choices=[("DRAFT", "Draft"), ("LOCKED", "Locked"), ("ACTIVE", "Active"), ("SUPERSEDED", "Superseded")],
        default="DRAFT",
    )
    published_at = models.DateTimeField(null=True, blank=True)
    supersedes_id = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="superseded_by",
    )
    change_reason = models.TextField(blank=True, default="")
    created_by = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Qualification Rule Set Version")
        verbose_name_plural = _("Qualification Rule Set Versions")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "recruitment_position_id", "version_no"],
                name="uniq_hr_qual_rule_tenant_position_version",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "recruitment_position_id", "version_no"]),
        ]

    def __str__(self):
        return f"QualRules v{self.version_no} [{self.status}]"


class HrSelectionSchemeVersion(models.Model):
    """选拔评分方案版本（LOCKED 后不可变；总分服务端计算）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    recruitment_position_id = models.ForeignKey(
        HrRecruitmentPosition,
        on_delete=models.PROTECT,
        related_name="selection_versions",
        verbose_name=_("Recruitment Position"),
    )
    version_no = models.PositiveIntegerField(default=1)
    total_score = models.DecimalField(max_digits=8, decimal_places=2, default=100)
    passing_rule = models.CharField(max_length=32, default="COMPOSITE")
    tie_break_rule_json = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=16,
        choices=[("DRAFT", "Draft"), ("LOCKED", "Locked"), ("ACTIVE", "Active"), ("SUPERSEDED", "Superseded")],
        default="DRAFT",
    )
    locked_at = models.DateTimeField(null=True, blank=True)
    supersedes_id = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="superseded_by",
    )
    change_reason = models.TextField(blank=True, default="")
    created_by = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Selection Scheme Version")
        verbose_name_plural = _("Selection Scheme Versions")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "recruitment_position_id", "version_no"],
                name="uniq_hr_sel_scheme_tenant_position_version",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "recruitment_position_id", "version_no"]),
        ]

    def __str__(self):
        return f"SelectionScheme v{self.version_no} [{self.status}]"
