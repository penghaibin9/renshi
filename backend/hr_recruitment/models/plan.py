"""
hr_recruitment/models/plan.py

HR04-01 年度用人计划（《04_HR04_总册》§8）。

HrHiringPlanCycle
  └─ HrHiringPlanRequest
       └─ HrHiringPlanLine
            └─ HR02 HrPositionReservation（S4 接入）

硬规则：
- 全表 tenant_id；无 tenant 上下文 fail-closed。
- RETURNED ≠ REJECTED；RETURNED 可改重提，REJECTED 不可直接重提。
- 批准时必须事务重查 HR02 可用额度（§8.6 并发），禁止按页面打开时快照直接批准。
- 不把当前人数当编制；编制/额度权威在 HR02。
"""

import uuid

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from hr_recruitment.constants import (
    NeedType,
    PlanCycleStatus,
    PlanLineStatus,
    PlanRequestStatus,
)


class HrHiringPlanCycle(models.Model):
    """年度用人计划周期。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    year = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=24, choices=PlanCycleStatus.choices, default=PlanCycleStatus.DRAFT
    )
    version = models.PositiveIntegerField(default=1)
    notes = models.TextField(blank=True, default="")
    created_by = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Hiring Plan Cycle")
        verbose_name_plural = _("Hiring Plan Cycles")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "year"],
                name="uniq_hr_hiring_plan_cycle_tenant_year",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "status"]),
            models.Index(fields=["tenant_id", "year", "status"]),
        ]

    def __str__(self):
        return f"{self.year} {self.title} [{self.status}]"


class HrHiringPlanRequest(models.Model):
    """学院/单位用人需求申请（含审批时间线状态）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    cycle_id = models.ForeignKey(
        HrHiringPlanCycle,
        on_delete=models.PROTECT,
        related_name="requests",
        verbose_name=_("Plan Cycle"),
    )
    organization_id = models.BigIntegerField(
        null=True, blank=True, db_index=True
    )  # HR02 HrOrganization stable id
    organization_name = models.CharField(
        max_length=200, blank=True, default=""
    )  # 展示快照，非权威
    requested_by = models.CharField(max_length=128, blank=True, default="")
    status = models.CharField(
        max_length=24, choices=PlanRequestStatus.choices, default=PlanRequestStatus.DRAFT
    )
    total_requested = models.PositiveIntegerField(default=0)
    total_approved = models.PositiveIntegerField(default=0)
    submitted_at = models.DateTimeField(null=True, blank=True)
    returned_reason = models.TextField(blank=True, default="")
    approved_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_by = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Hiring Plan Request")
        verbose_name_plural = _("Hiring Plan Requests")
        indexes = [
            models.Index(fields=["tenant_id", "cycle_id", "status"]),
            models.Index(fields=["tenant_id", "organization_id"]),
        ]

    def __str__(self):
        return f"{self.organization_name or self.organization_id} {self.status}"


class HrHiringPlanLine(models.Model):
    """需求行：岗位目录 + 需求额度 + 审批额度 + 到岗计划。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    request_id = models.ForeignKey(
        HrHiringPlanRequest,
        on_delete=models.PROTECT,
        related_name="lines",
        verbose_name=_("Plan Request"),
    )
    post_catalog_id = models.BigIntegerField(
        null=True, blank=True, db_index=True
    )  # HR02 HrPostCatalog stable id
    post_catalog_name = models.CharField(
        max_length=200, blank=True, default=""
    )  # 展示快照
    position_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    position_pool_id = models.BigIntegerField(null=True, blank=True)
    need_type = models.CharField(
        max_length=16, choices=NeedType.choices, default=NeedType.NEW
    )
    requested_headcount = models.PositiveIntegerField(default=0)
    approved_headcount = models.PositiveIntegerField(default=0)
    requested_fte = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    approved_fte = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    target_onboard_date = models.DateField(null=True, blank=True)
    reason = models.TextField(blank=True, default="")
    qualification_summary = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=24, choices=PlanLineStatus.choices, default=PlanLineStatus.REQUESTED
    )
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Hiring Plan Line")
        verbose_name_plural = _("Hiring Plan Lines")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(requested_headcount__gte=0)
                & models.Q(approved_headcount__gte=0),
                name="ck_hr_plan_line_headcount_nonneg",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "request_id", "status"]),
            models.Index(fields=["tenant_id", "post_catalog_id"]),
        ]

    def __str__(self):
        return f"{self.post_catalog_name} ×{self.requested_headcount} [{self.status}]"
