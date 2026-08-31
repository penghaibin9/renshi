"""Versioned statutory social-insurance and housing-fund payroll facts."""

from __future__ import annotations

from django.db import models
from django.db.models import Q

from horilla.hr_domain_models import HrTenantScopedModel


class StatutoryContributionRuleVersion(HrTenantScopedModel):
    class Group(models.TextChoices):
        SOCIAL_INSURANCE = "SOCIAL_INSURANCE", "Social insurance"
        HOUSING_FUND = "HOUSING_FUND", "Housing fund"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PUBLISHED = "PUBLISHED", "Published"
        RETIRED = "RETIRED", "Retired"

    rule_code = models.CharField(max_length=64)
    version_no = models.PositiveIntegerField(default=1)
    contribution_group = models.CharField(max_length=32, choices=Group.choices)
    contribution_code = models.CharField(max_length=32)
    name = models.CharField(max_length=200)
    jurisdiction_code = models.CharField(max_length=32)
    base_variable_key = models.CharField(max_length=64)
    base_floor = models.DecimalField(max_digits=18, decimal_places=2)
    base_ceiling = models.DecimalField(max_digits=18, decimal_places=2)
    employee_rate = models.DecimalField(max_digits=10, decimal_places=6)
    employer_rate = models.DecimalField(max_digits=10, decimal_places=6)
    employee_item_code = models.CharField(max_length=64)
    employer_item_code = models.CharField(max_length=64)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    policy_evidence_json = models.JSONField(default=dict)
    content_hash = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    published_at = models.DateTimeField(null=True, blank=True)

    _RULE_FIELDS = (
        "tenant_id",
        "rule_code",
        "version_no",
        "contribution_group",
        "contribution_code",
        "name",
        "jurisdiction_code",
        "base_variable_key",
        "base_floor",
        "base_ceiling",
        "employee_rate",
        "employer_rate",
        "employee_item_code",
        "employer_item_code",
        "effective_from",
        "effective_to",
        "policy_evidence_json",
        "content_hash",
    )

    class Meta:
        db_table = "hr15_statutory_contribution_rule"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "rule_code", "version_no"),
                name="uq_hr15_stat_rule_ver",
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "employee_item_code", "version_no"),
                name="uq_hr15_stat_employee_item_ver",
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "employer_item_code", "version_no"),
                name="uq_hr15_stat_employer_item_ver",
            ),
            models.CheckConstraint(
                condition=Q(base_floor__gte=0) & Q(base_ceiling__gte=models.F("base_floor")),
                name="ck_hr15_stat_base_range",
            ),
            models.CheckConstraint(
                condition=Q(employee_rate__gte=0)
                & Q(employee_rate__lte=1)
                & Q(employer_rate__gte=0)
                & Q(employer_rate__lte=1),
                name="ck_hr15_stat_rates",
            ),
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True)
                | Q(effective_to__gt=models.F("effective_from")),
                name="ck_hr15_stat_effective_range",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "status", "effective_from"),
                name="idx_hr15_stat_effective",
            )
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                "status", *self._RULE_FIELDS
            ).first()
            if persisted and persisted["status"] in {self.Status.PUBLISHED, self.Status.RETIRED}:
                changed = [
                    field for field in self._RULE_FIELDS if getattr(self, field) != persisted[field]
                ]
                if changed:
                    raise ValueError(
                        "STATUTORY_RULE_IMMUTABLE: publish a new contribution rule version"
                    )
        return super().save(*args, **kwargs)


class StatutoryContributionFact(HrTenantScopedModel):
    class Status(models.TextChoices):
        CALCULATED = "CALCULATED", "Calculated"
        REVIEWED = "REVIEWED", "Reviewed"
        SEALED = "SEALED", "Sealed"

    payroll_period_id = models.UUIDField()
    payroll_result_id = models.UUIDField()
    calculation_batch_id = models.UUIDField()
    staff_id = models.UUIDField()
    rule_version_id = models.UUIDField()
    contribution_group = models.CharField(
        max_length=32, choices=StatutoryContributionRuleVersion.Group.choices
    )
    contribution_code = models.CharField(max_length=32)
    requested_base = models.DecimalField(max_digits=18, decimal_places=2)
    contribution_base = models.DecimalField(max_digits=18, decimal_places=2)
    employee_rate = models.DecimalField(max_digits=10, decimal_places=6)
    employer_rate = models.DecimalField(max_digits=10, decimal_places=6)
    employee_amount = models.DecimalField(max_digits=18, decimal_places=2)
    employer_amount = models.DecimalField(max_digits=18, decimal_places=2)
    employee_item_code = models.CharField(max_length=64)
    employer_item_code = models.CharField(max_length=64)
    input_snapshot_id = models.UUIDField()
    input_content_hash = models.CharField(max_length=64)
    rule_content_hash = models.CharField(max_length=64)
    evidence_hash = models.CharField(max_length=64)
    review_evidence_hash = models.CharField(max_length=64, blank=True, default="")
    reviewed_by = models.PositiveBigIntegerField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    sealed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.CALCULATED, db_index=True
    )

    _FACT_FIELDS = (
        "tenant_id",
        "payroll_period_id",
        "payroll_result_id",
        "calculation_batch_id",
        "staff_id",
        "rule_version_id",
        "contribution_group",
        "contribution_code",
        "requested_base",
        "contribution_base",
        "employee_rate",
        "employer_rate",
        "employee_amount",
        "employer_amount",
        "employee_item_code",
        "employer_item_code",
        "input_snapshot_id",
        "input_content_hash",
        "rule_content_hash",
        "evidence_hash",
        "review_evidence_hash",
        "reviewed_by",
        "reviewed_at",
        "sealed_at",
        "status",
    )
    _BUSINESS_FIELDS = _FACT_FIELDS[:20]
    _REVIEW_FIELDS = ("review_evidence_hash", "reviewed_by", "reviewed_at")

    class Meta:
        db_table = "hr15_statutory_contribution_fact"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "payroll_result_id", "rule_version_id"),
                name="uq_hr15_stat_result_rule",
            ),
            models.CheckConstraint(
                condition=Q(requested_base__gte=0)
                & Q(contribution_base__gte=0)
                & Q(employee_amount__gte=0)
                & Q(employer_amount__gte=0),
                name="ck_hr15_stat_fact_amounts",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "payroll_period_id", "status"),
                name="idx_hr15_stat_period_status",
            ),
            models.Index(
                fields=("tenant_id", "staff_id", "payroll_period_id"),
                name="idx_hr15_stat_staff_period",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                *self._FACT_FIELDS
            ).first()
            if persisted:
                changed_business = [
                    field
                    for field in self._BUSINESS_FIELDS
                    if getattr(self, field) != persisted[field]
                ]
                if changed_business:
                    raise ValueError(
                        "STATUTORY_CONTRIBUTION_IMMUTABLE: calculation facts cannot be edited"
                    )
                changed_review = [
                    field
                    for field in self._REVIEW_FIELDS
                    if getattr(self, field) != persisted[field]
                ]
                if persisted["status"] in {self.Status.REVIEWED, self.Status.SEALED} and changed_review:
                    raise ValueError(
                        "STATUTORY_CONTRIBUTION_REVIEW_IMMUTABLE: append a payroll correction"
                    )
                if persisted["status"] == self.Status.SEALED and any(
                    getattr(self, field) != persisted[field] for field in self._FACT_FIELDS
                ):
                    raise ValueError(
                        "STATUTORY_CONTRIBUTION_IMMUTABLE: sealed payroll contribution cannot change"
                    )
        return super().save(*args, **kwargs)


class HrPayrollStatutoryPermissionMeta(models.Model):
    class Meta:
        managed = False
        permissions = (
            ("hr.payroll.statutory.view", "HR15: View social insurance and housing fund"),
            ("hr.payroll.statutory.manage", "HR15: Manage statutory contribution rules"),
        )
