"""HR15 payroll authority roots.

The legacy ``payroll/`` app remains a technical source during migration.  These
models are the new authority roots for payroll identity, payroll periods and
finalized payroll facts.  Historical finalized facts are append-only; later
adjustments must create a new fact rather than overwrite an old one.
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q

from horilla.hr_domain_models import HrTenantScopedModel


class PayrollProfile(HrTenantScopedModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        ENDED = "ENDED", "Ended"

    staff_id = models.UUIDField()
    payroll_identity_no = models.CharField(max_length=64)
    pay_group_code = models.CharField(max_length=64)
    currency_code = models.CharField(max_length=3, default="CNY")
    payment_account_ref = models.CharField(max_length=128, blank=True, default="")
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE, db_index=True)

    class Meta:
        db_table = "hr15_payroll_profile"
        permissions = [("hr.payroll.view", "查看 HR15 薪酬福利工作区")]
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "payroll_identity_no"),
                name="uq_hr15_profile_tenant_identity",
            ),
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True) | Q(effective_to__gt=models.F("effective_from")),
                name="ck_hr15_profile_effective_range",
            ),
        ]
        indexes = [
            models.Index(fields=("tenant_id", "staff_id", "status"), name="idx_hr15_profile_tenant_staff"),
        ]


class PayrollPeriod(HrTenantScopedModel):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        INPUT_FROZEN = "INPUT_FROZEN", "Input frozen"
        CALCULATED = "CALCULATED", "Calculated"
        REVIEWED = "REVIEWED", "Reviewed"
        FINALIZED = "FINALIZED", "Finalized"
        CLOSED = "CLOSED", "Closed"

    period_code = models.CharField(max_length=32)
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.OPEN, db_index=True)
    finalized_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "hr15_payroll_period"
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "period_code"), name="uq_hr15_period_tenant_code"),
            models.CheckConstraint(condition=Q(end_date__gt=models.F("start_date")), name="ck_hr15_period_date_range"),
        ]
        indexes = [
            models.Index(fields=("tenant_id", "status", "start_date"), name="idx_hr15_period_tenant_status"),
        ]


class PayrollResultFact(HrTenantScopedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        FINALIZED = "FINALIZED", "Finalized"
        ADJUSTED = "ADJUSTED", "Adjusted"
        REVERSED = "REVERSED", "Reversed"

    result_no = models.CharField(max_length=64)
    payroll_period_id = models.UUIDField()
    staff_id = models.UUIDField()
    currency_code = models.CharField(max_length=3, default="CNY")
    gross_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    deduction_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    net_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)
    supersedes_result_id = models.UUIDField(null=True, blank=True)

    _IMMUTABLE_STATUSES = frozenset(
        {Status.FINALIZED, Status.ADJUSTED, Status.REVERSED}
    )
    _FACT_FIELDS = (
        "tenant_id",
        "result_no",
        "payroll_period_id",
        "staff_id",
        "currency_code",
        "gross_amount",
        "deduction_amount",
        "net_amount",
        "status",
        "supersedes_result_id",
    )

    class Meta:
        db_table = "hr15_payroll_result_fact"
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "result_no"), name="uq_hr15_result_tenant_no"),
        ]
        indexes = [
            models.Index(fields=("tenant_id", "payroll_period_id", "staff_id"), name="idx_hr15_result_period_staff"),
            models.Index(fields=("tenant_id", "staff_id", "status"), name="idx_hr15_result_tenant_staff"),
        ]

    def save(self, *args, **kwargs):
        """Keep persisted terminal payroll facts append-only.

        ``DRAFT -> FINALIZED`` is the legal finalization boundary. Once a fact
        has reached a terminal persisted state, its business payload and state
        cannot be edited in place. Retroactive corrections must append another
        fact linked through ``supersedes_result_id`` rather than mutate payroll
        history.
        """
        if self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                *self._FACT_FIELDS
            ).first()
            if persisted and persisted["status"] in self._IMMUTABLE_STATUSES:
                changed = [
                    field
                    for field in self._FACT_FIELDS
                    if getattr(self, field) != persisted[field]
                ]
                if changed:
                    raise ValueError(
                        "PAYROLL_FINAL_RESULT_IMMUTABLE: finalized payroll facts "
                        "must be corrected with an appended adjustment fact"
                    )
        return super().save(*args, **kwargs)
