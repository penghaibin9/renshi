"""HR15 benefit and occupational-pension authorities."""

from __future__ import annotations

from django.db import models
from django.db.models import Q

from horilla.hr_domain_models import HrTenantScopedModel


class BenefitPlan(HrTenantScopedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PUBLISHED = "PUBLISHED", "Published"
        INACTIVE = "INACTIVE", "Inactive"

    plan_code = models.CharField(max_length=64)
    version_no = models.PositiveIntegerField(default=1)
    name = models.CharField(max_length=200)
    benefit_type = models.CharField(max_length=64)
    provider_name = models.CharField(max_length=200, blank=True, default="")
    currency_code = models.CharField(max_length=3, default="CNY")
    employer_rate = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    employee_rate = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    fixed_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    rule_snapshot_json = models.JSONField(default=dict)
    content_hash = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)

    class Meta:
        db_table = "hr15_benefit_plan"
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "plan_code", "version_no"), name="uq_hr15_benefit_plan_ver"),
            models.CheckConstraint(condition=Q(effective_to__isnull=True) | Q(effective_to__gt=models.F("effective_from")), name="ck_hr15_benefit_date"),
        ]
        indexes = [models.Index(fields=("tenant_id", "plan_code", "status"), name="idx_hr15_benefit_plan")]

    def save(self, *args, **kwargs):
        if self.pk:
            old = type(self)._base_manager.filter(pk=self.pk).values("status").first()
            if old and old["status"] in {self.Status.PUBLISHED, self.Status.INACTIVE}:
                raise ValueError("BENEFIT_PLAN_IMMUTABLE: publish a new plan version")
        return super().save(*args, **kwargs)


class BenefitEnrollmentFact(HrTenantScopedModel):
    enrollment_no = models.CharField(max_length=64)
    benefit_plan_id = models.UUIDField()
    staff_id = models.UUIDField()
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    employer_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    employee_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    snapshot_json = models.JSONField(default=dict)
    supersedes_enrollment_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "hr15_benefit_enrollment_fact"
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "enrollment_no"), name="uq_hr15_benefit_enroll_no"),
            models.UniqueConstraint(fields=("tenant_id", "supersedes_enrollment_id"), name="uq_hr15_benefit_supersede"),
            models.CheckConstraint(condition=Q(effective_to__isnull=True) | Q(effective_to__gt=models.F("effective_from")), name="ck_hr15_benefit_enroll_date"),
        ]
        indexes = [models.Index(fields=("tenant_id", "staff_id", "benefit_plan_id"), name="idx_hr15_benefit_staff")]

    def save(self, *args, **kwargs):
        if self.pk and type(self)._base_manager.filter(pk=self.pk).exists():
            raise ValueError("BENEFIT_ENROLLMENT_IMMUTABLE: append a superseding fact")
        return super().save(*args, **kwargs)


class OccupationalPensionPlan(HrTenantScopedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PUBLISHED = "PUBLISHED", "Published"
        INACTIVE = "INACTIVE", "Inactive"

    plan_code = models.CharField(max_length=64)
    version_no = models.PositiveIntegerField(default=1)
    name = models.CharField(max_length=200)
    employer_rate = models.DecimalField(max_digits=10, decimal_places=6)
    employee_rate = models.DecimalField(max_digits=10, decimal_places=6)
    contribution_basis_rule_json = models.JSONField(default=dict)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    content_hash = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)

    class Meta:
        db_table = "hr15_pension_plan"
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "plan_code", "version_no"), name="uq_hr15_pension_plan_ver"),
            models.CheckConstraint(condition=Q(employer_rate__gte=0) & Q(employee_rate__gte=0), name="ck_hr15_pension_rates"),
            models.CheckConstraint(condition=Q(effective_to__isnull=True) | Q(effective_to__gt=models.F("effective_from")), name="ck_hr15_pension_plan_date"),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            old = type(self)._base_manager.filter(pk=self.pk).values("status").first()
            if old and old["status"] in {self.Status.PUBLISHED, self.Status.INACTIVE}:
                raise ValueError("PENSION_PLAN_IMMUTABLE: publish a new plan version")
        return super().save(*args, **kwargs)


class OccupationalPensionPeriod(HrTenantScopedModel):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        CLOSED = "CLOSED", "Closed"

    plan_id = models.UUIDField()
    period_code = models.CharField(max_length=32)
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN, db_index=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "hr15_pension_period"
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "plan_id", "period_code"), name="uq_hr15_pension_period"),
            models.CheckConstraint(condition=Q(end_date__gt=models.F("start_date")), name="ck_hr15_pension_period_date"),
        ]
        indexes = [models.Index(fields=("tenant_id", "status", "period_code"), name="idx_hr15_pension_period")]

    def save(self, *args, **kwargs):
        if self.pk:
            old = type(self)._base_manager.filter(pk=self.pk).values("status").first()
            if old and old["status"] == self.Status.CLOSED:
                raise ValueError("PENSION_PERIOD_IMMUTABLE: closed period cannot be changed")
        return super().save(*args, **kwargs)


class OccupationalPensionContributionFact(HrTenantScopedModel):
    contribution_no = models.CharField(max_length=64)
    pension_period_id = models.UUIDField()
    pension_plan_id = models.UUIDField()
    staff_id = models.UUIDField()
    sequence_no = models.PositiveIntegerField(default=1)
    basis_amount = models.DecimalField(max_digits=18, decimal_places=2)
    employer_amount = models.DecimalField(max_digits=18, decimal_places=2)
    employee_amount = models.DecimalField(max_digits=18, decimal_places=2)
    total_amount = models.DecimalField(max_digits=18, decimal_places=2)
    supersedes_contribution_id = models.UUIDField(null=True, blank=True)
    snapshot_json = models.JSONField(default=dict)

    class Meta:
        db_table = "hr15_pension_contribution_fact"
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "contribution_no"), name="uq_hr15_pension_contrib_no"),
            models.UniqueConstraint(fields=("tenant_id", "pension_period_id", "staff_id", "sequence_no"), name="uq_hr15_pension_staff_seq"),
            models.UniqueConstraint(fields=("tenant_id", "supersedes_contribution_id"), name="uq_hr15_pension_supersede"),
            models.CheckConstraint(condition=Q(basis_amount__gte=0) & Q(employer_amount__gte=0) & Q(employee_amount__gte=0) & Q(total_amount__gte=0), name="ck_hr15_pension_amounts"),
        ]
        indexes = [models.Index(fields=("tenant_id", "pension_period_id", "staff_id"), name="idx_hr15_pension_contrib")]

    def save(self, *args, **kwargs):
        if self.pk and type(self)._base_manager.filter(pk=self.pk).exists():
            raise ValueError("PENSION_CONTRIBUTION_IMMUTABLE: append an adjustment fact")
        return super().save(*args, **kwargs)


class OccupationalPensionSettlementFact(HrTenantScopedModel):
    settlement_no = models.CharField(max_length=64)
    pension_period_id = models.UUIDField()
    pension_plan_id = models.UUIDField()
    contribution_count = models.PositiveIntegerField(default=0)
    staff_count = models.PositiveIntegerField(default=0)
    employer_total = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    employee_total = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    grand_total = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    snapshot_json = models.JSONField(default=dict)
    closed_at = models.DateTimeField()

    class Meta:
        db_table = "hr15_pension_settlement_fact"
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "settlement_no"), name="uq_hr15_pension_settle_no"),
            models.UniqueConstraint(fields=("tenant_id", "pension_period_id"), name="uq_hr15_pension_period_settle"),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self)._base_manager.filter(pk=self.pk).exists():
            raise ValueError("PENSION_SETTLEMENT_IMMUTABLE")
        return super().save(*args, **kwargs)


class HrPayrollAuthorityPermissionMeta(models.Model):
    class Meta:
        managed = False
        permissions = (
            ("hr.payroll.benefit.view", "HR15: View Benefit Authority"),
            ("hr.payroll.benefit.manage", "HR15: Manage Benefit Authority"),
            ("hr.payroll.pension.view", "HR15: View Occupational Pension"),
            ("hr.payroll.pension.manage", "HR15: Manage Occupational Pension"),
            ("hr.payroll.pension.close", "HR15: Close Occupational Pension Period"),
        )
