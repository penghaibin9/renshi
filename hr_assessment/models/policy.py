"""HR12 — Policy Authority 模型。

本文件与 ``hr_assessment/migrations/0001_initial.py`` 保持同一 schema 合同。
业务校验可以增强，但不允许通过“删模型/改表名”绕过 Django 接管与 MySQL Gate。
"""

from __future__ import annotations

import hashlib

from django.core.exceptions import ValidationError
from django.db import models
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
            models.UniqueConstraint(
                fields=("tenant_id", "code"),
                name="uniq_policy_pack_tenant_code",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class PolicyVersionManager(models.Manager):
    def get_by_tenant(self, tenant_id: int) -> QuerySet:
        return self.filter(tenant_id=tenant_id)

    def published(self, tenant_id: int, as_of: str) -> QuerySet:
        return (
            self.filter(
                tenant_id=tenant_id,
                status="PUBLISHED",
                effective_from__lte=as_of,
            )
            .exclude(effective_to__lt=as_of)
            .order_by("-version_no")
        )


class HrAssessmentPolicyVersion(VersionedModel):
    policy_pack = models.ForeignKey(
        HrAssessmentPolicyPack,
        on_delete=models.PROTECT,
        related_name="versions",
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
        indexes = [
            models.Index(
                fields=("tenant_id", "status"),
                name="idx_policy_ver_tenant_status",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if (
            self.status == "PUBLISHED"
            and self.pk
            and HrAssessmentPolicyVersion.objects.filter(
                pk=self.pk,
                status="PUBLISHED",
            ).exists()
        ):
            raise ValidationError(_("已发布版本不可修改 — 请创建新版本"))

    def save(self, *args, **kwargs) -> None:
        if self.status == "PUBLISHED" and not self.content_hash:
            raw = (
                f"{self.policy_pack_id}:{self.version_no}:"
                f"{self.effective_from}:{self.assessment_types}"
            )
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
            models.UniqueConstraint(
                fields=("tenant_id", "code"),
                name="uniq_indicator_tenant_code",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class HrIndicatorVersion(VersionedModel):
    indicator = models.ForeignKey(
        HrIndicatorDefinition,
        on_delete=models.PROTECT,
        related_name="versions",
    )
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

    def __str__(self) -> str:
        return f"{self.indicator.code} v{self.version_no}"


class HrIndicatorSetVersion(VersionedModel):
    name = models.CharField(max_length=200)
    total_weight = models.DecimalField(max_digits=5, decimal_places=2, default=1.00)

    class Meta:
        db_table = "hr_assessment_indicator_set_version"
        verbose_name = _("指标集版本")
        verbose_name_plural = _("指标集版本")

    def __str__(self) -> str:
        return f"{self.name} v{self.version_no}"


class HrIndicatorBinding(models.Model):
    id = models.UUIDField(primary_key=True)
    indicator_set = models.ForeignKey(
        HrIndicatorSetVersion,
        on_delete=models.CASCADE,
        related_name="bindings",
    )
    indicator_version = models.ForeignKey(
        HrIndicatorVersion,
        on_delete=models.PROTECT,
    )
    weight = models.DecimalField(max_digits=5, decimal_places=4)
    min_score = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    max_score = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    required = models.BooleanField(default=True)
    hard_gate = models.BooleanField(default=False)
    evidence_rule_json = models.JSONField(default=dict)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "hr_assessment_indicator_binding"
        verbose_name = _("指标绑定")
        verbose_name_plural = _("指标绑定")


class HrAssessmentWorkflowVersion(VersionedModel):
    name = models.CharField(max_length=200)

    class Meta:
        db_table = "hr_assessment_workflow_version"
        verbose_name = _("工作流版本")
        verbose_name_plural = _("工作流版本")

    def __str__(self) -> str:
        return f"{self.name} v{self.version_no}"


class HrWorkflowStep(models.Model):
    id = models.UUIDField(primary_key=True)
    workflow = models.ForeignKey(
        HrAssessmentWorkflowVersion,
        on_delete=models.CASCADE,
        related_name="steps",
    )
    step_code = models.CharField(max_length=50)
    step_name = models.CharField(max_length=200)
    actor_role = models.CharField(max_length=50)
    scope = models.CharField(max_length=50, default="ASSIGNED")
    required = models.BooleanField(default=True)
    deadline_rule_json = models.JSONField(default=dict)
    delegation_allowed = models.BooleanField(default=False)
    return_allowed = models.BooleanField(default=True)
    reopen_allowed = models.BooleanField(default=False)
    completion_rule_json = models.JSONField(default=dict)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "hr_assessment_workflow_step"
        verbose_name = _("工作流步骤")
        verbose_name_plural = _("工作流步骤")


class HrAssessmentClassificationProfileVersion(VersionedModel):
    name = models.CharField(max_length=200)
    job_family = models.CharField(max_length=50)
    position_category = models.CharField(max_length=50)
    discipline_category = models.CharField(max_length=50, default="", blank=True)
    teacher_category = models.CharField(max_length=50, default="", blank=True)
    management_level = models.CharField(max_length=50, default="", blank=True)
    student_affairs_role = models.CharField(max_length=50, default="", blank=True)
    research_role = models.CharField(max_length=50, default="", blank=True)
    applicable_indicator_set_id = models.UUIDField(null=True, blank=True)
    reviewer_structure_json = models.JSONField(default=dict)

    class Meta:
        db_table = "hr_assessment_classification_profile_version"
        verbose_name = _("岗位分类评价版本")
        verbose_name_plural = _("岗位分类评价版本")

    def __str__(self) -> str:
        return f"{self.name} v{self.version_no}"


class HrEvidenceRequirement(models.Model):
    id = models.UUIDField(primary_key=True)
    indicator_version = models.ForeignKey(
        HrIndicatorVersion,
        on_delete=models.PROTECT,
        related_name="evidence_requirements",
    )
    accepted_provider_types = models.JSONField(default=list)
    min_trust_level = models.CharField(max_length=30, default="SYSTEM_VERIFIED")
    required_period = models.CharField(max_length=30, default="WITHIN_CYCLE")
    required_fields = models.JSONField(default=list)
    document_required = models.BooleanField(default=False)
    manual_verification_required = models.BooleanField(default=False)
    fallback_mode = models.CharField(max_length=30, default="FAIL_CLOSED")

    class Meta:
        db_table = "hr_assessment_evidence_requirement"
        verbose_name = _("证据要求")
        verbose_name_plural = _("证据要求")


class HrGateRule(TenantScopedModel):
    code = models.CharField(max_length=50)
    name = models.CharField(max_length=200)
    gate_type = models.CharField(max_length=30)
    current_version_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "hr_assessment_gate_rule"
        verbose_name = _("硬门槛规则")
        verbose_name_plural = _("硬门槛规则")

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class HrGateRuleVersion(VersionedModel):
    gate_rule = models.ForeignKey(
        HrGateRule,
        on_delete=models.PROTECT,
        related_name="versions",
    )
    effect_code = models.CharField(max_length=30)
    source_refs = models.JSONField(default=list)
    condition_json = models.JSONField(default=dict)

    class Meta:
        db_table = "hr_assessment_gate_rule_version"
        verbose_name = _("硬门槛规则版本")
        verbose_name_plural = _("硬门槛规则版本")

    def __str__(self) -> str:
        return f"{self.gate_rule.code} v{self.version_no}"


class HrResultRuleVersion(VersionedModel):
    name = models.CharField(max_length=200)
    score_to_grade_mapping = models.JSONField(default=dict)
    gate_effects_json = models.JSONField(default=dict)
    excellent_quota_rule_json = models.JSONField(default=dict)
    no_rating_conditions_json = models.JSONField(default=dict)
    term_qualification_conditions_json = models.JSONField(default=dict)
    special_population_rules_json = models.JSONField(default=dict)
    collective_override_permission = models.BooleanField(default=True)
    override_reason_required = models.BooleanField(default=True)

    class Meta:
        db_table = "hr_assessment_result_rule_version"
        verbose_name = _("结果规则版本")
        verbose_name_plural = _("结果规则版本")

    def __str__(self) -> str:
        return f"{self.name} v{self.version_no}"


class HrExcellentQuotaPolicy(VersionedModel):
    name = models.CharField(max_length=200)
    quota_basis_population = models.CharField(max_length=50)
    max_excellent_ratio = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=0.20,
    )
    classification_factor_json = models.JSONField(default=dict)
    special_tilt_policy_json = models.JSONField(default=dict)
    over_quota_action = models.CharField(max_length=30, default="BLOCKER")
    rounding_rule = models.CharField(max_length=20, default="ROUND_DOWN")
    min_eligible_for_quota = models.PositiveIntegerField(default=5)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "hr_assessment_excellent_quota_policy"
        verbose_name = _("优秀比例政策")
        verbose_name_plural = _("优秀比例政策")

    def __str__(self) -> str:
        return f"{self.name} v{self.version_no}"
