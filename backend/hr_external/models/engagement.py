"""
hr_external/models/engagement.py —— HrExternalEngagement 外聘聘用关系（S2，总册 §19/§20/§21/§93）。

等价成熟 HCM 的 Work Order/Contingent Engagement：
- 一个 Person 可多 Engagement（多学院并行，§21）；一个 Engagement 退出不能误杀另一个（§138.14）。
- agreement_id / agreement_status 只引用 HR07（§7），由正式 AgreementProvider 解析。
- review_at 提前触发续聘评估（§59）；到期只 Review 不自动续（§138.11）。
- 状态机见 constants.ExternalEngagementStatus。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_external.constants import (
    AgreementProviderStatus,
    AgreementRequirement,
    ExternalEngagementStatus,
    EngagementSourceType,
    RiskSeverity,
)


class HrExternalEngagement(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    engagement_no = models.CharField(max_length=32)
    # ---- 身份（§19）----
    person_id = models.ForeignKey(
        "hr_staff.HrPerson",
        on_delete=models.PROTECT,
        related_name="external_engagements",
    )
    external_profile_id = models.ForeignKey(
        "hr_external.HrExternalTeacherProfile",
        on_delete=models.PROTECT,
        related_name="engagements",
    )
    category_id = models.ForeignKey(
        "hr_external.HrExternalCategory",
        on_delete=models.PROTECT,
        related_name="engagements",
    )
    purpose = models.CharField(max_length=200, blank=True, default="")
    source_type = models.CharField(
        max_length=32,
        choices=EngagementSourceType.choices,
        default=EngagementSourceType.COLLEGE_RECOMMENDATION,
    )
    source_case_id = models.CharField(max_length=64, blank=True, default="")
    # ---- 组织/岗位（§8：引用 HR02；不占正式编制则不伪造空编）----
    host_organization_id = models.BigIntegerField(db_index=True)  # hr_structure.HrOrganization.id
    post_catalog_id = models.BigIntegerField(null=True, blank=True)  # hr_structure.HrPostCatalog.id
    external_position_pool_id = models.CharField(max_length=64, blank=True, default="")
    # ---- 聘期（半开区间 [start_at, end_at)，§19）----
    start_at = models.DateField()
    end_at = models.DateField(null=True, blank=True)
    review_at = models.DateField(null=True, blank=True)
    workload_cap = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    # ---- HR07 正式协议（§7/§93；Provider 投影）----
    agreement_id = models.CharField(max_length=64, blank=True, default="")
    agreement_status = models.CharField(
        max_length=32,
        choices=AgreementProviderStatus.choices,
        default=AgreementProviderStatus.UNAVAILABLE,
    )
    agreement_requirement = models.CharField(
        max_length=32,
        choices=AgreementRequirement.choices,
        default=AgreementRequirement.REQUIRED_BEFORE_ACTIVATION,
    )
    # ---- 状态/风险 ----
    status = models.CharField(
        max_length=32,
        choices=ExternalEngagementStatus.choices,
        default=ExternalEngagementStatus.DRAFT,
        db_index=True,
    )
    current_risk_level = models.CharField(
        max_length=16,
        choices=RiskSeverity.choices,
        default=RiskSeverity.INFO,
    )
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR External Engagement")
        verbose_name_plural = _("HR External Engagements")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "engagement_no"],
                name="uniq_hr_external_engagement_no",
            ),
            models.CheckConstraint(
                condition=models.Q(end_at__isnull=True)
                | models.Q(start_at__lt=models.F("end_at")),
                name="hex_engagement_dates_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="hex_engagement_version_gte_1",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "status"],
                name="hex_eng_tenant_status_idx",
            ),
            models.Index(
                fields=["tenant_id", "person_id", "start_at", "end_at"],
                name="hex_eng_person_period_idx",
            ),
            models.Index(
                fields=["tenant_id", "host_organization_id", "status"],
                name="hex_eng_host_org_idx",
            ),
            models.Index(
                fields=["tenant_id", "end_at", "status"],
                name="hex_eng_end_status_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] {self.engagement_no} ({self.status})"
