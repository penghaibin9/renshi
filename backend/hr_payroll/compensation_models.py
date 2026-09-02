"""Effective-dated compensation change authority for HR15."""

from __future__ import annotations

from django.db import models
from django.db.models import Q

from horilla.hr_domain_models import HrTenantScopedModel


class CompensationChangeCaseQuerySet(models.QuerySet):
    _ERROR = "COMPENSATION_CHANGE_LEDGER_IMMUTABLE"

    def update(self, **kwargs):
        raise ValueError(self._ERROR)

    def delete(self):
        raise ValueError(self._ERROR)

    def bulk_update(self, objs, fields, **kwargs):
        raise ValueError(self._ERROR)

    def bulk_create(self, objs, **kwargs):
        raise ValueError(self._ERROR)


class CompensationChangeCaseManager(
    models.Manager.from_queryset(CompensationChangeCaseQuerySet)
):
    pass


class CompensationChangeCase(HrTenantScopedModel):
    """One auditable proposal that changes a payroll variable from a date."""

    class ChangeType(models.TextChoices):
        POSITION_PAY_CHANGE = "POSITION_PAY_CHANGE", "岗位工资变更"
        SALARY_STEP_CHANGE = "SALARY_STEP_CHANGE", "薪级变更"
        POLICY_STANDARD_CHANGE = "POLICY_STANDARD_CHANGE", "政策性调资"
        PERFORMANCE_ADJUSTMENT = "PERFORMANCE_ADJUSTMENT", "绩效工资调整"
        ALLOWANCE_START = "ALLOWANCE_START", "津补贴启用"
        ALLOWANCE_CHANGE = "ALLOWANCE_CHANGE", "津补贴变更"
        ALLOWANCE_STOP = "ALLOWANCE_STOP", "津补贴停发"
        BONUS = "BONUS", "一次性奖金"
        SPECIAL_REWARD = "SPECIAL_REWARD", "专项奖励"
        ARREARS = "ARREARS", "补发"
        RECOVERY = "RECOVERY", "追扣"
        CORRECTION = "CORRECTION", "更正"

    class AmountMode(models.TextChoices):
        SET = "SET", "设置金额"
        DELTA = "DELTA", "增减金额"

    class ProrationMode(models.TextChoices):
        NONE = "NONE", "不折算"
        CALENDAR_DAYS = "CALENDAR_DAYS", "按自然日折算"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "草稿"
        SUBMITTED = "SUBMITTED", "待审批"
        APPROVED = "APPROVED", "已批准"
        REJECTED = "REJECTED", "已拒绝"
        CANCELLED = "CANCELLED", "已取消"

    case_no = models.CharField(max_length=64)
    staff_id = models.UUIDField()
    change_type = models.CharField(max_length=32, choices=ChangeType.choices)
    payroll_variable_key = models.CharField(max_length=64)
    item_name = models.CharField(max_length=200)
    amount_mode = models.CharField(
        max_length=16, choices=AmountMode.choices, default=AmountMode.SET
    )
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency_code = models.CharField(max_length=3, default="CNY")
    proration_mode = models.CharField(
        max_length=24,
        choices=ProrationMode.choices,
        default=ProrationMode.NONE,
    )
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    review_date = models.DateField(null=True, blank=True)
    reason_code = models.CharField(max_length=64)
    note = models.TextField(blank=True, default="")
    source_domain = models.CharField(max_length=16, blank=True, default="")
    source_ref = models.CharField(max_length=128, blank=True, default="")
    source_version = models.CharField(max_length=64, blank=True, default="")
    source_snapshot_json = models.JSONField(default=dict, blank=True)
    evidence_refs_json = models.JSONField(default=list, blank=True)
    supersedes_case_id = models.UUIDField(null=True, blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    content_hash = models.CharField(max_length=64, blank=True, default="")
    submitted_by = models.PositiveBigIntegerField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.PositiveBigIntegerField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True, default="")

    objects = CompensationChangeCaseManager()

    _PAYLOAD_FIELDS = (
        "tenant_id",
        "case_no",
        "staff_id",
        "change_type",
        "payroll_variable_key",
        "item_name",
        "amount_mode",
        "amount",
        "currency_code",
        "proration_mode",
        "effective_from",
        "effective_to",
        "review_date",
        "reason_code",
        "note",
        "source_domain",
        "source_ref",
        "source_version",
        "source_snapshot_json",
        "evidence_refs_json",
        "supersedes_case_id",
        "content_hash",
    )

    class Meta:
        db_table = "hr15_compensation_change_case"
        permissions = (
            ("hr.payroll.change.view", "HR15: View compensation changes"),
            ("hr.payroll.change.manage", "HR15: Manage compensation changes"),
            ("hr.payroll.change.approve", "HR15: Approve compensation changes"),
        )
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "case_no"),
                name="uq_hr15_change_case_no",
            ),
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True)
                | Q(effective_to__gte=models.F("effective_from")),
                name="ck_hr15_change_effective_range",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "staff_id", "status", "effective_from"),
                name="idx_hr15_change_staff",
            ),
            models.Index(
                fields=("tenant_id", "payroll_variable_key", "effective_from"),
                name="idx_hr15_change_variable",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            persisted = type(self)._base_manager.filter(pk=self.pk).values(
                "status", *self._PAYLOAD_FIELDS
            ).first()
            if persisted and persisted["status"] != self.Status.DRAFT:
                changed = [
                    field
                    for field in self._PAYLOAD_FIELDS
                    if getattr(self, field) != persisted[field]
                ]
                if changed:
                    raise ValueError(
                        "COMPENSATION_CHANGE_IMMUTABLE: append a superseding case"
                    )
            if persisted and persisted["status"] in {
                self.Status.APPROVED,
                self.Status.REJECTED,
                self.Status.CANCELLED,
            } and self.status != persisted["status"]:
                raise ValueError("COMPENSATION_CHANGE_DECISION_IMMUTABLE")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("COMPENSATION_CHANGE_LEDGER_IMMUTABLE")
