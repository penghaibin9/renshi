"""
hr10_development/models/development_fact.py

发展事实 + 度量台账 + 合规规则 + 风险案例（总册 §111-122）。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _
from hr10_development.constants import FactType, RiskType, RiskCaseStatus, RiskSeverity
from hr10_development.models.base import DevelopmentTenantModel


class HrDevelopmentFact(DevelopmentTenantModel):
    staff_master_id = models.BigIntegerField(db_index=True)
    fact_type = models.CharField(max_length=32, choices=FactType.choices, db_index=True, verbose_name=_("事实类型"))
    source_case_type = models.CharField(max_length=64, verbose_name=_("来源 case 类型"))
    source_case_id = models.BigIntegerField()
    source_revision_no = models.IntegerField(default=0)
    activity_type = models.CharField(max_length=64, blank=True, default="")
    provider_org_id = models.BigIntegerField(null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    verified_hours = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True)
    verified_days = models.IntegerField(null=True, blank=True)
    verified_credits = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True)
    level_or_result = models.CharField(max_length=64, blank=True, default="")
    verification_status = models.CharField(max_length=48, db_index=True)
    evidence_package_hash = models.CharField(max_length=128, blank=True, default="")
    generated_at = models.DateTimeField()
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    supersedes_fact_id = models.BigIntegerField(null=True, blank=True)
    immutable_hash = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        db_table = "hr_development_fact"
        verbose_name = _("发展事实")
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=["staff_master_id", "fact_type", "valid_from"])]


class HrDevelopmentMetricLedger(DevelopmentTenantModel):
    staff_master_id = models.BigIntegerField(db_index=True)
    fact_id = models.BigIntegerField(db_index=True)
    metric_code = models.CharField(max_length=64, verbose_name=_("度量码"))
    raw_value = models.DecimalField(max_digits=10, decimal_places=2)
    raw_unit = models.CharField(max_length=16)
    normalized_value = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    normalized_unit = models.CharField(max_length=16, blank=True, default="")
    conversion_rule_version = models.CharField(max_length=64, blank=True, default="")
    eligibility_rule_version = models.CharField(max_length=64, blank=True, default="")
    window_key = models.CharField(max_length=64, blank=True, default="")
    calculated_at = models.DateTimeField()

    class Meta:
        db_table = "hr_development_metric_ledger"
        verbose_name = _("发展度量台账")
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=["staff_master_id", "metric_code", "window_key"])]


class HrDevelopmentComplianceRule(DevelopmentTenantModel):
    rule_pack_id = models.CharField(max_length=128, verbose_name=_("规则包 ID"))
    version = models.IntegerField(default=1)
    population_rule_json = models.JSONField(default=dict)
    metric_code = models.CharField(max_length=64)
    time_window_type = models.CharField(max_length=32)
    minimum_value = models.DecimalField(max_digits=10, decimal_places=2)
    unit = models.CharField(max_length=16)
    eligible_activity_types = models.JSONField(default=list)
    minimum_trust_level = models.IntegerField(default=3)
    exception_policy_json = models.JSONField(blank=True, default=dict)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, default="PUBLISHED", verbose_name=_("状态"))

    class Meta:
        db_table = "hr_development_compliance_rule"
        verbose_name = _("合规规则")
        verbose_name_plural = verbose_name
        unique_together = [("tenant_id", "rule_pack_id", "version")]


class HrDevelopmentRiskCase(DevelopmentTenantModel):
    risk_type = models.CharField(max_length=48, choices=RiskType.choices, db_index=True, verbose_name=_("风险类型"))
    staff_master_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    source_case_type = models.CharField(max_length=64, blank=True, default="")
    source_case_id = models.BigIntegerField(null=True, blank=True)
    severity = models.CharField(max_length=16, choices=RiskSeverity.choices, default=RiskSeverity.MEDIUM)
    status = models.CharField(max_length=32, choices=RiskCaseStatus.choices, default=RiskCaseStatus.OPEN, db_index=True)
    detected_rule_version = models.CharField(max_length=64, blank=True, default="")
    detected_at = models.DateTimeField()
    owner_id = models.BigIntegerField(null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    resolution_reason = models.TextField(blank=True, default="")
    resolution_evidence_refs = models.JSONField(blank=True, default=list)
    version = models.IntegerField(default=1)

    class Meta:
        db_table = "hr_development_risk_case"
        verbose_name = _("发展风险案例")
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=["tenant_id", "risk_type", "status", "due_at"])]
