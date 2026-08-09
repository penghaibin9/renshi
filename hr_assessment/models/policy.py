"""HR12 — Policy 模型层生产化：Managers + save() + clean() + admin。"""

from __future__ import annotations

import hashlib
import uuid as _uuid
from typing import Optional

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import QuerySet
from django.utils.translation import gettext_lazy as _

from hr_assessment.models.base import TenantScopedModel, VersionedModel


class PolicyPackManager(models.Manager):
    def get_by_tenant(self, tenant_id: int) -> QuerySet:
        return self.filter(tenant_id=tenant_id)


class HrAssessmentPolicyPack(TenantScopedModel):
    code = models.CharField(max_length=50, verbose_name=_("政策编码"))
    name = models.CharField(max_length=200, verbose_name=_("政策名称"))
    assessment_domain = models.CharField(max_length=50, verbose_name=_("考核域"))
    owner_org_id = models.UUIDField(null=True, blank=True, verbose_name=_("归属组织 ID"))
    current_published_version_id = models.UUIDField(null=True, blank=True)
    source_policy_refs = models.JSONField(default=dict, blank=True)

    objects = PolicyPackManager()

    class Meta:
        db_table = "hr_assessment_policy_pack"
        verbose_name = _("考核政策包")
        verbose_name_plural = _("考核政策包")
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "code"), name="uniq_polpack_tenant_code"),
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class PolicyVersionManager(models.Manager):
    def get_by_tenant(self, tenant_id: int) -> QuerySet:
        return self.filter(tenant_id=tenant_id)

    def published(self, tenant_id: int, as_of: str) -> QuerySet:
        return self.filter(
            tenant_id=tenant_id, status="PUBLISHED",
            effective_from__lte=as_of,
        ).exclude(effective_to__lt=as_of).order_by("-version_no")


class HrAssessmentPolicyVersion(VersionedModel):
    policy_pack = models.ForeignKey(
        HrAssessmentPolicyPack, on_delete=models.PROTECT, related_name="versions",
        verbose_name=_("所属政策包"),
    )
    effective_from = models.DateField(verbose_name=_("生效日期"))
    effective_to = models.DateField(null=True, blank=True)
    assessment_types = models.JSONField(default=list)
    eligibility_rule_json = models.JSONField(default=dict)
    cycle_rule_json = models.JSONField(default=dict)
    rating_scale_version_id = models.UUIDField()
    indicator_set_version_id = models.UUIDField()
    workflow_version_id = models.UUIDField()
    excellent_quota_policy_id = models.UUIDField(null=True, blank=True)
    ethics_gate_policy_id = models.UUIDField(null=True, blank=True)
    evidence_policy_id = models.UUIDField(null=True, blank=True)
    result_rule_version_id = models.UUIDField(null=True, blank=True)

    objects = PolicyVersionManager()

    class Meta:
        db_table = "hr_assessment_policy_version"
        verbose_name = _("考核政策版本")
        verbose_name_plural = _("考核政策版本")
        constraints = [
            models.UniqueConstraint(fields=("policy_pack", "version_no"), name="uniq_polver_pack_ver"),
        ]
        indexes = [
            models.Index(fields=("tenant_id", "status"), name="idx_polver_tenant_status"),
            models.Index(fields=("policy_pack", "effective_from"), name="idx_polver_pack_eff"),
        ]

    def clean(self) -> None:
        super().clean()
        if self.status == "PUBLISHED":
            if self.pk and HrAssessmentPolicyVersion.objects.filter(pk=self.pk, status="PUBLISHED").exists():
                raise ValidationError(_("已发布版本不可修改 — 请创建新版本"))

    def save(self, *args, **kwargs) -> None:
        if self.status == "PUBLISHED" and not self.content_hash:
            raw = f"{self.policy_pack_id}:{self.version_no}:{self.effective_from}:{self.assessment_types}"
            self.content_hash = hashlib.sha256(raw.encode()).hexdigest()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.policy_pack.code} v{self.version_no}"


class HrRatingScaleVersion(VersionedModel):
    scale_type = models.CharField(max_length=20)
    min_value = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    max_value = models.DecimalField(max_digits=10, decimal_places=2, default=100)
    levels = models.JSONField(default=list)
    rounding_rule = models.CharField(max_length=20, default="ROUND_HALF_UP")
    display_labels = models.JSONField(default=dict)
    normalization_rule = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "hr_assessment_rating_scale_version"
        verbose_name = _("评分尺度版本")
        verbose_name_plural = _("评分尺度版本")

    def __str__(self) -> str:
        return f"RatingScale v{self.version_no} ({self.scale_type})"


class HrIndicatorDefinition(TenantScopedModel):
    code = models.CharField(max_length=50, verbose_name=_("指标编码"))
    name = models.CharField(max_length=200, verbose_name=_("指标名称"))
    dimension = models.CharField(max_length=30)
    default_value_type = models.CharField(max_length=30, default="NUMBER")
    is_active = models.BooleanField(default=True)
    current_version_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "hr_assessment_indicator_definition"
        verbose_name = _("指标定义")
        verbose_name_plural = _("指标定义")
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "code"), name="uniq_ind_tenant_code"),
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class HrIndicatorVersion(VersionedModel):
    indicator = models.ForeignKey(HrIndicatorDefinition, on_delete=models.PROTECT, related_name="versions")
    name = models.CharField(max_length=200)
    description = models.TextField(default="", blank=True)
    dimension = models.CharField(max_length=30)
    value_type = models.CharField(max_length=30)
    source_provider = models.CharField(max_length=50)
    aggregation_method = models.CharField(max_length=30, default="DIRECT")
    evidence_requirement_json = models.JSONField(default=dict)
    calculation_formula = models.TextField(default="", blank=True)
    human_judgment_required = models.BooleanField(default=False)
    sensitivity = models.CharField(max_length=30, default="INTERNAL_METRIC")
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "hr_assessment_indicator_version"
        verbose_name = _("指标版本")
        verbose_name_plural = _("指标版本")
        constraints = [
            models.UniqueConstraint(fields=("indicator", "version_no"), name="uniq_indver_ind_ver"),
        ]

    def __str__(self) -> str:
        return f"{self.indicator.code} v{self.version_no}"
