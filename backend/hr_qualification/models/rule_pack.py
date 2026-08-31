"""
hr_qualification/models/rule_pack.py —— HrDoubleTeacherRulePack + RulePackVersion（总册 §36）。

四层规则体系：
  NATIONAL_BASELINE  → 国家基本标准（教师厅〔2022〕2号）
       ↓ inherits / strengthens
  PROVINCIAL         → 省级标准（不低于国家）
       ↓
  SCHOOL             → 学校实施细则（不低于省级）
       ↓ frozen
  BATCH_OVERRIDE     → 批次冻结版本

HrDoubleTeacherRulePack 使用简单 ACTIVE/INACTIVE 状态；
HrDoubleTeacherRulePackVersion 使用完整发布状态机（DRAFT→VALIDATING→...→ACTIVE→RETIRED）。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_qualification.constants import JurisdictionLevel, RulePackVersionStatus


class RulePackStatus(models.TextChoices):
    """规则包自身状态（不是版本状态）。"""
    ACTIVE = "ACTIVE", _("Active")
    INACTIVE = "INACTIVE", _("Inactive")
    RETIRED = "RETIRED", _("Retired")


class HrDoubleTeacherRulePack(models.Model):
    """双师型教师认定规则包。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(null=True, blank=True, db_index=True)  # NULL=国家级
    jurisdiction_level = models.CharField(
        max_length=24,
        choices=JurisdictionLevel.choices,
        default=JurisdictionLevel.SCHOOL,
    )
    jurisdiction_code = models.CharField(max_length=16, blank=True, default="")  # CN/HUN/etc.
    code = models.CharField(max_length=64, db_index=True)
    name = models.CharField(max_length=200)
    parent_rule_pack_id = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="child_packs",
    )
    status = models.CharField(
        max_length=16,
        choices=RulePackStatus.choices,
        default=RulePackStatus.ACTIVE,
    )
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Double Teacher Rule Pack")
        verbose_name_plural = _("HR Double Teacher Rule Packs")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "code"],
                name="uniq_rulepack_tenant_code",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "jurisdiction_level"]),
        ]

    def __str__(self) -> str:
        scope = "System" if self.tenant_id is None else f"T{self.tenant_id}"
        return f"[{scope}] {self.name}"


class HrDoubleTeacherRulePackVersion(models.Model):
    """双师规则版本（冻结后不可变）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rule_pack_id = models.ForeignKey(
        HrDoubleTeacherRulePack,
        on_delete=models.PROTECT,
        related_name="versions",
    )
    version_no = models.PositiveIntegerField()
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    policy_document_ids = models.JSONField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=RulePackVersionStatus.choices,
        default=RulePackVersionStatus.DRAFT,
        db_index=True,
    )
    checksum = models.CharField(max_length=128, blank=True, default="")
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Double Teacher Rule Pack Version")
        verbose_name_plural = _("HR Double Teacher Rule Pack Versions")
        constraints = [
            models.UniqueConstraint(
                fields=["rule_pack_id", "version_no"],
                name="uniq_rulepackversion_pack_ver",
            ),
        ]
        indexes = [
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"{self.rule_pack_id.code} v{self.version_no} [{self.status}]"
