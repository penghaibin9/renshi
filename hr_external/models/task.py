"""
hr_external/models/task.py —— 教学与服务任务（S7，总册 §45-53）。

- HrExternalTaskPlan：计划冻结（§45）；
- HrExternalServiceTask：服务任务（§46），source_domain/source_object_type/source_object_id
  引用教务事实（§48，不复制教务主表）；
- HrExternalTaskEvidence：证据（§50）；
- HrExternalWorkloadRecord：工作量（§51），source 四类，本人提交不自动成为正式数量（§52）；
- HrExternalSettlementBasis：结算依据（§53），HR15 算金额。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_external.constants import (
    ExternalTaskStatus,
    SettlementStatus,
    TaskAcceptance,
    TaskSourceDomain,
    TaskSourceObjectType,
    WorkloadSource,
    WorkloadVerificationStatus,
)


class HrExternalTaskPlan(models.Model):
    """任务计划（§45）。计划冻结，后续变更走新版本。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    engagement_id = models.ForeignKey(
        "hr_external.HrExternalEngagement",
        on_delete=models.PROTECT,
        related_name="task_plans",
    )
    period_start = models.DateField()
    period_end = models.DateField(null=True, blank=True)
    plan_version = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=16, default="DRAFT")  # DRAFT/FROZEN/SUPERSEDED
    approved_by = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR External Task Plan")
        verbose_name_plural = _("HR External Task Plans")
        constraints = [
            models.UniqueConstraint(
                fields=["engagement_id", "plan_version"],
                name="uniq_hr_external_task_plan_version",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "engagement_id"],
                name="hr_external_task_plan_eng_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] plan v{self.plan_version}"


class HrExternalServiceTask(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    engagement_id = models.ForeignKey(
        "hr_external.HrExternalEngagement",
        on_delete=models.PROTECT,
        related_name="service_tasks",
    )
    assignment_id = models.ForeignKey(
        "hr_external.HrExternalEngagementAssignment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="service_tasks",
    )
    task_type = models.CharField(max_length=40)
    # ---- 来源（§48：ACADEMIC 为教务权威，HR08 只存 reference）----
    source_domain = models.CharField(
        max_length=24,
        choices=TaskSourceDomain.choices,
        default=TaskSourceDomain.HR08,
    )
    source_object_type = models.CharField(
        max_length=32,
        choices=TaskSourceObjectType.choices,
        blank=True,
        default="",
    )
    source_object_id = models.CharField(max_length=64, blank=True, default="")
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True, default="")
    planned_quantity = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    planned_unit = models.CharField(max_length=32, blank=True, default="")
    planned_start = models.DateField()
    planned_end = models.DateField(null=True, blank=True)
    owner_org_id = models.BigIntegerField(db_index=True)
    reviewer_id = models.BigIntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=24,
        choices=ExternalTaskStatus.choices,
        default=ExternalTaskStatus.DRAFT,
        db_index=True,
    )
    acceptance = models.CharField(
        max_length=24,
        choices=TaskAcceptance.choices,
        default=TaskAcceptance.PENDING,
    )
    settlement_eligible = models.BooleanField(default=False)
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR External Service Task")
        verbose_name_plural = _("HR External Service Tasks")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(planned_end__isnull=True)
                | models.Q(planned_start__lt=models.F("planned_end")),
                name="hr_external_task_dates_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="hr_external_task_version_gte_1",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "engagement_id", "task_type", "status"],
                name="hr_external_task_eng_type_status_idx",
            ),
            models.Index(
                fields=["tenant_id", "owner_org_id", "status"],
                name="hr_external_task_org_status_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] {self.title} ({self.status})"


class HrExternalTaskEvidence(models.Model):
    """任务证据（§50）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    task_id = models.ForeignKey(
        HrExternalServiceTask,
        on_delete=models.PROTECT,
        related_name="evidences",
    )
    evidence_type = models.CharField(max_length=40)
    document_id = models.CharField(max_length=64, blank=True, default="")
    submitted_by = models.BigIntegerField(null=True, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    verified_by = models.BigIntegerField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=24, default="UPLOADED")  # UPLOADED/PENDING_VERIFICATION/VERIFIED/REJECTED
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR External Task Evidence")
        verbose_name_plural = _("HR External Task Evidences")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="hr_external_evidence_version_gte_1",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "task_id"],
                name="hr_external_evidence_task_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] {self.evidence_type} {self.status}"


class HrExternalWorkloadRecord(models.Model):
    """工作量（§51/§52）。本人提交不自动成为正式数量。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    engagement_id = models.ForeignKey(
        "hr_external.HrExternalEngagement",
        on_delete=models.PROTECT,
        related_name="workload_records",
    )
    task_id = models.ForeignKey(
        HrExternalServiceTask,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="workload_records",
    )
    source = models.CharField(
        max_length=32,
        choices=WorkloadSource.choices,
        default=WorkloadSource.SYSTEM_CALCULATED,
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    unit = models.CharField(max_length=32, blank=True, default="")
    service_date = models.DateField()
    verification_status = models.CharField(
        max_length=16,
        choices=WorkloadVerificationStatus.choices,
        default=WorkloadVerificationStatus.UNVERIFIED,
    )
    settlement_status = models.CharField(
        max_length=16,
        choices=SettlementStatus.choices,
        default=SettlementStatus.NOT_ELIGIBLE,
    )
    verified_by = models.BigIntegerField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR External Workload Record")
        verbose_name_plural = _("HR External Workload Records")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="hr_external_workload_version_gte_1",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "engagement_id", "service_date"],
                name="hr_external_workload_eng_date_idx",
            ),
            models.Index(
                fields=["tenant_id", "verification_status"],
                name="hr_external_workload_ver_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] {self.quantity}{self.unit} ({self.verification_status})"


class HrExternalSettlementBasis(models.Model):
    """结算依据（§53）。HR08 只输出 verified basis，HR15/财务算实际金额（§138.9）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    engagement_id = models.ForeignKey(
        "hr_external.HrExternalEngagement",
        on_delete=models.PROTECT,
        related_name="settlement_bases",
    )
    period = models.CharField(max_length=64)  # 如 2026-09
    verified_workload = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    eligible_items = models.JSONField(default=list, blank=True)
    policy_ref = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=SettlementStatus.choices,
        default=SettlementStatus.PENDING,
    )
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR External Settlement Basis")
        verbose_name_plural = _("HR External Settlement Bases")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "engagement_id", "period"],
                name="uniq_hr_external_settlement_period",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="hr_external_settlement_version_gte_1",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] {self.period} ({self.status})"
