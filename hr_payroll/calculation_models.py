"""HR15 calculation, review, payment, payslip and reconciliation authorities.

The models deliberately reference upstream and sibling facts by immutable UUID
instead of database foreign keys.  That keeps each authority deployable on its
own while every row remains tenant-scoped and auditable.
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q

from horilla.hr_domain_models import HrTenantScopedModel


class SalaryRuleVersion(HrTenantScopedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PUBLISHED = "PUBLISHED", "Published"
        RETIRED = "RETIRED", "Retired"

    class ItemType(models.TextChoices):
        EARNING = "EARNING", "Earning"
        DEDUCTION = "DEDUCTION", "Deduction"
        EMPLOYER = "EMPLOYER", "Employer contribution"

    rule_code = models.CharField(max_length=64)
    version_no = models.PositiveIntegerField(default=1)
    item_code = models.CharField(max_length=64)
    name = models.CharField(max_length=200)
    item_type = models.CharField(max_length=16, choices=ItemType.choices)
    priority = models.PositiveIntegerField(default=100)
    currency_code = models.CharField(max_length=3, default="CNY")
    formula_json = models.JSONField(default=dict)
    dependencies_json = models.JSONField(default=list, blank=True)
    rounding_mode = models.CharField(max_length=24, default="HALF_UP")
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    content_hash = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    published_at = models.DateTimeField(null=True, blank=True)

    _RULE_FIELDS = (
        "tenant_id",
        "rule_code",
        "version_no",
        "item_code",
        "name",
        "item_type",
        "priority",
        "currency_code",
        "formula_json",
        "dependencies_json",
        "rounding_mode",
        "effective_from",
        "effective_to",
        "content_hash",
    )

    class Meta:
        db_table = "hr15_salary_rule_version"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "rule_code", "version_no"),
                name="uq_hr15_salary_rule_ver",
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "item_code", "version_no"),
                name="uq_hr15_salary_item_ver",
            ),
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True)
                | Q(effective_to__gt=models.F("effective_from")),
                name="ck_hr15_salary_rule_date",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "status", "effective_from"),
                name="idx_hr15_rule_effective",
            )
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                "status", *self._RULE_FIELDS
            ).first()
            if persisted and persisted["status"] in {
                self.Status.PUBLISHED,
                self.Status.RETIRED,
            }:
                changed = [
                    field
                    for field in self._RULE_FIELDS
                    if getattr(self, field) != persisted[field]
                ]
                if changed:
                    raise ValueError(
                        "SALARY_RULE_IMMUTABLE: publish a new rule version"
                    )
        return super().save(*args, **kwargs)


class PayrollInputSnapshot(HrTenantScopedModel):
    payroll_period_id = models.UUIDField()
    staff_id = models.UUIDField()
    currency_code = models.CharField(max_length=3, default="CNY")
    source_versions_json = models.JSONField(default=dict)
    variables_json = models.JSONField(default=dict)
    content_hash = models.CharField(max_length=64)
    captured_at = models.DateTimeField()

    class Meta:
        db_table = "hr15_payroll_input_snapshot"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "payroll_period_id", "staff_id"),
                name="uq_hr15_input_period_staff",
            )
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "payroll_period_id", "staff_id"),
                name="idx_hr15_input_period_staff",
            )
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self)._base_manager.filter(pk=self.pk).exists():
            raise ValueError("PAYROLL_INPUT_IMMUTABLE: capture a new payroll period")
        return super().save(*args, **kwargs)


class PayrollCalculationBatch(HrTenantScopedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        RUNNING = "RUNNING", "Running"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"

    payroll_period_id = models.UUIDField()
    batch_no = models.CharField(max_length=64)
    idempotency_key = models.CharField(max_length=128)
    rule_set_hash = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    lease_token = models.CharField(max_length=64, blank=True, default="")
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    staff_count = models.PositiveIntegerField(default=0)
    result_count = models.PositiveIntegerField(default=0)
    gross_total = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    deduction_total = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    net_total = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    warning_json = models.JSONField(default=list, blank=True)
    failure_code = models.CharField(max_length=64, blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    _FACT_FIELDS = (
        "tenant_id",
        "payroll_period_id",
        "batch_no",
        "idempotency_key",
        "rule_set_hash",
        "status",
        "staff_count",
        "result_count",
        "gross_total",
        "deduction_total",
        "net_total",
        "warning_json",
        "failure_code",
        "started_at",
        "completed_at",
    )

    class Meta:
        db_table = "hr15_payroll_calculation_batch"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "batch_no"), name="uq_hr15_calc_batch_no"
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "idempotency_key"),
                name="uq_hr15_calc_idempotency",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "payroll_period_id", "status"),
                name="idx_hr15_calc_period",
            )
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                *self._FACT_FIELDS
            ).first()
            if persisted and persisted["status"] == self.Status.COMPLETED:
                changed = [
                    field
                    for field in self._FACT_FIELDS
                    if getattr(self, field) != persisted[field]
                ]
                if changed:
                    raise ValueError(
                        "PAYROLL_CALCULATION_BATCH_IMMUTABLE: completed calculation "
                        "batches cannot be edited"
                    )
        return super().save(*args, **kwargs)


class PayrollCalculationLine(HrTenantScopedModel):
    calculation_batch_id = models.UUIDField()
    payroll_result_id = models.UUIDField()
    staff_id = models.UUIDField()
    item_code = models.CharField(max_length=64)
    item_name = models.CharField(max_length=200)
    item_type = models.CharField(max_length=16, choices=SalaryRuleVersion.ItemType.choices)
    sequence_no = models.PositiveIntegerField()
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency_code = models.CharField(max_length=3, default="CNY")
    rule_version_id = models.UUIDField()
    explanation_json = models.JSONField(default=dict)

    class Meta:
        db_table = "hr15_payroll_calculation_line"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "calculation_batch_id", "staff_id", "item_code"),
                name="uq_hr15_calc_line_item",
            )
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "payroll_result_id", "sequence_no"),
                name="idx_hr15_calc_line_result",
            )
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self)._base_manager.filter(pk=self.pk).exists():
            raise ValueError("PAYROLL_CALCULATION_LINE_IMMUTABLE")
        return super().save(*args, **kwargs)


class PayrollReviewFact(HrTenantScopedModel):
    class Decision(models.TextChoices):
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    payroll_period_id = models.UUIDField()
    payroll_result_id = models.UUIDField()
    decision = models.CharField(max_length=16, choices=Decision.choices)
    note = models.TextField(blank=True, default="")
    reviewed_by = models.PositiveBigIntegerField()
    reviewed_at = models.DateTimeField()

    class Meta:
        db_table = "hr15_payroll_review_fact"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "payroll_result_id"),
                name="uq_hr15_review_result",
            )
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "payroll_period_id", "decision"),
                name="idx_hr15_review_period",
            )
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self)._base_manager.filter(pk=self.pk).exists():
            raise ValueError("PAYROLL_REVIEW_IMMUTABLE: append a new calculation run")
        return super().save(*args, **kwargs)


class PayrollPaymentInstruction(HrTenantScopedModel):
    class Status(models.TextChoices):
        CREATED = "CREATED", "Created"
        SENT = "SENT", "Sent"
        ACCEPTED = "ACCEPTED", "Accepted"
        REJECTED = "REJECTED", "Rejected"

    instruction_no = models.CharField(max_length=64)
    payroll_result_id = models.UUIDField()
    staff_id = models.UUIDField()
    currency_code = models.CharField(max_length=3)
    requested_amount = models.DecimalField(max_digits=18, decimal_places=2)
    account_ref_hash = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.CREATED, db_index=True
    )
    provider_code = models.CharField(max_length=64, blank=True, default="")
    provider_receipt_json = models.JSONField(default=dict, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)

    _IDENTITY_FIELDS = (
        "tenant_id",
        "instruction_no",
        "payroll_result_id",
        "staff_id",
        "currency_code",
        "requested_amount",
        "account_ref_hash",
        "provider_code",
    )
    _TERMINAL_FIELDS = _IDENTITY_FIELDS + (
        "status",
        "provider_receipt_json",
        "sent_at",
        "received_at",
    )

    class Meta:
        db_table = "hr15_payroll_payment_instruction"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "instruction_no"),
                name="uq_hr15_payment_instruction",
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "payroll_result_id"),
                name="uq_hr15_payment_result",
            ),
            models.CheckConstraint(
                condition=Q(requested_amount__gte=0), name="ck_hr15_payment_amount"
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "status", "created_at"),
                name="idx_hr15_payment_status",
            )
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                *self._TERMINAL_FIELDS
            ).first()
            if persisted:
                protected_fields = (
                    self._TERMINAL_FIELDS
                    if persisted["status"] in {self.Status.ACCEPTED, self.Status.REJECTED}
                    else self._IDENTITY_FIELDS
                )
                changed = [
                    field
                    for field in protected_fields
                    if getattr(self, field) != persisted[field]
                ]
                if changed:
                    raise ValueError(
                        "PAYROLL_PAYMENT_INSTRUCTION_IMMUTABLE: payment identity and "
                        "terminal receipts cannot be edited"
                    )
        return super().save(*args, **kwargs)


class PayrollPayslipFact(HrTenantScopedModel):
    payslip_no = models.CharField(max_length=64)
    payroll_result_id = models.UUIDField()
    payment_instruction_id = models.UUIDField()
    staff_id = models.UUIDField()
    content_hash = models.CharField(max_length=64)
    statement_json = models.JSONField(default=dict)
    published_at = models.DateTimeField()

    class Meta:
        db_table = "hr15_payroll_payslip_fact"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "payslip_no"), name="uq_hr15_payslip_no"
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "payroll_result_id"),
                name="uq_hr15_payslip_result",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "staff_id", "published_at"),
                name="idx_hr15_payslip_staff",
            )
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self)._base_manager.filter(pk=self.pk).exists():
            raise ValueError("PAYROLL_PAYSLIP_IMMUTABLE")
        return super().save(*args, **kwargs)


class PayrollFinanceReconciliationFact(HrTenantScopedModel):
    class Status(models.TextChoices):
        MATCHED = "MATCHED", "Matched"
        MISMATCH = "MISMATCH", "Mismatch"

    reconciliation_no = models.CharField(max_length=64)
    payment_instruction_id = models.UUIDField()
    expected_amount = models.DecimalField(max_digits=18, decimal_places=2)
    settled_amount = models.DecimalField(max_digits=18, decimal_places=2)
    difference_amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency_code = models.CharField(max_length=3)
    status = models.CharField(max_length=16, choices=Status.choices, db_index=True)
    receipt_snapshot_json = models.JSONField(default=dict)
    reconciled_by = models.PositiveBigIntegerField()
    reconciled_at = models.DateTimeField()

    class Meta:
        db_table = "hr15_payroll_finance_reconciliation"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "reconciliation_no"),
                name="uq_hr15_reconciliation_no",
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "payment_instruction_id"),
                name="uq_hr15_reconciliation_payment",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "status", "reconciled_at"),
                name="idx_hr15_reconciliation_status",
            )
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self)._base_manager.filter(pk=self.pk).exists():
            raise ValueError("PAYROLL_RECONCILIATION_IMMUTABLE")
        return super().save(*args, **kwargs)


class HrPayrollWorkflowPermissionMeta(models.Model):
    class Meta:
        managed = False
        permissions = (
            ("hr.payroll.rule.manage", "HR15: Manage salary rule versions"),
            ("hr.payroll.input.manage", "HR15: Freeze payroll input snapshots"),
            ("hr.payroll.calculate", "HR15: Run payroll calculations"),
            ("hr.payroll.review", "HR15: Review payroll calculations"),
            ("hr.payroll.finalize", "HR15: Finalize reviewed payroll"),
            ("hr.payroll.payment", "HR15: Issue and receive payroll payments"),
            ("hr.payroll.payslip.view_sensitive", "HR15: View sensitive payslips"),
            ("hr.payroll.reconcile", "HR15: Reconcile payroll with finance"),
        )
