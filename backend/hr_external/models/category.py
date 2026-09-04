"""
hr_external/models/category.py —— HrExternalCategory 外聘类别配置（S1，总册 §18/§5）。

原则：
- 类别是 tenant 化配置（H0：权威配置显式 tenant_id）；内置默认集通过
  category_service.ensure_default_categories(tenant_id) 按 tenant 注入，不写跨校共享数据。
- Title ≠ Engagement ≠ Assignment：类别字段决定"该类别的可选项与策略"，不承载单次聘用状态。
- agreement_type_code / access_policy_code / settlement_policy_code 均为 HR07/权限/结算
  策略的引用编码；由 integrations 层映射 HR07 等正式领域对象。
- 不可配置掉：tenant 隔离、Engagement effective dates、Agreement gate、audit、
  access expiry、version、exit/revoke、历史不可变（§136）。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_external.constants import AgreementRequirement


class HrExternalCategory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    code = models.CharField(max_length=40)
    name = models.CharField(max_length=120)
    is_system_builtin = models.BooleanField(default=False)
    # ---- 聘用策略（§18 / §28）----
    requires_open_selection = models.BooleanField(default=False)
    requires_ethics_review = models.BooleanField(default=True)
    requires_teacher_qualification = models.BooleanField(default=False)
    requires_industry_experience = models.BooleanField(default=False)
    default_engagement_months = models.PositiveIntegerField(null=True, blank=True)
    allow_multiple_assignments = models.BooleanField(default=True)
    allow_teaching = models.BooleanField(default=False)
    allow_research = models.BooleanField(default=False)
    agreement_requirement = models.CharField(
        max_length=32,
        choices=AgreementRequirement.choices,
        default=AgreementRequirement.REQUIRED_BEFORE_ACTIVATION,
    )
    # ---- 跨域 Provider 引用（HR07/权限/结算）----
    agreement_type_code = models.CharField(max_length=64, blank=True, default="")
    access_policy_code = models.CharField(max_length=64, blank=True, default="")
    settlement_policy_code = models.CharField(max_length=64, blank=True, default="")
    # ---- 治理 ----
    is_active = models.BooleanField(default=True)
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR External Category")
        verbose_name_plural = _("HR External Categories")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "code"],
                name="uniq_hr_external_category_tenant_code",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="hex_category_version_gte_1",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "is_active"],
                name="hex_cat_tenant_active_idx",
            ),
            models.Index(
                fields=["tenant_id", "code"],
                name="hex_cat_tenant_code_idx",
            ),
        ]
        ordering = ["code"]

    def __str__(self):
        return f"[{self.tenant_id}] {self.code} {self.name}"
