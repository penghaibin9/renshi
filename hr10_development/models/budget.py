"""
hr10_development/models/budget.py

发展预算计划（总册 §34）。
HR10 管"计划/预留/承诺"，最终支付由 HR15 财务权威。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr10_development.models.base import DevelopmentTenantModel


class HrDevelopmentBudgetPlan(DevelopmentTenantModel):
    """发展预算计划。plan_version→预算条目。"""

    plan_version_id = models.BigIntegerField(
        db_index=True,
        verbose_name=_("计划版本 ID"),
    )

    funding_source_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name=_("经费来源 ID"),
    )

    currency = models.CharField(
        max_length=8,
        default="CNY",
        verbose_name=_("币种"),
    )

    planned_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name=_("计划金额"),
    )

    reserved_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        verbose_name=_("已预留金额"),
    )

    committed_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        verbose_name=_("已承诺金额"),
    )

    actual_paid_projection = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        verbose_name=_("实际支付投影"),
    )

    organization_id = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name=_("归属组织 ID"),
    )

    activity_type = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_index=True,
        verbose_name=_("活动类型"),
    )

    budget_period = models.CharField(
        max_length=32,
        blank=True,
        default="",
        verbose_name=_("预算期间"),
    )

    external_budget_ref = models.CharField(
        max_length=256,
        blank=True,
        default="",
        verbose_name=_("外部预算引用"),
    )

    version = models.IntegerField(
        default=1,
        verbose_name=_("乐观锁版本"),
    )

    class Meta:
        db_table = "hr_development_budget_plan"
        verbose_name = _("发展预算计划")
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=["plan_version_id", "activity_type"]),
            models.Index(fields=["plan_version_id", "organization_id"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(planned_amount__gte=0),
                name="budget_planned_non_negative",
            ),
            models.CheckConstraint(
                check=models.Q(reserved_amount__gte=0),
                name="budget_reserved_non_negative",
            ),
            models.CheckConstraint(
                check=models.Q(committed_amount__gte=0),
                name="budget_committed_non_negative",
            ),
        ]

    def __str__(self):
        return f"Budget {self.planned_amount} {self.currency} (plan_v{self.plan_version_id})"
