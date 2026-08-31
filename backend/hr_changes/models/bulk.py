"""
hr_changes/models/bulk.py —— HrBulkChangeBatch/Item 批量异动（总册 §38/§39）。

禁止一个批量 SQL UPDATE：每个人仍独立产生 Change Case 或明确 item event。
默认 PREVALIDATE_ALL；执行策略 ATOMIC_BATCH / ITEMIZED_COMMIT（组织重构强关联优先 ATOMIC）。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class HrBulkChangeBatch(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", _("Draft")
        VALIDATING = "VALIDATING", _("Validating")
        PREVALIDATED = "PREVALIDATED", _("Prevalidated")
        SUBMITTED = "SUBMITTED", _("Submitted")
        APPROVED = "APPROVED", _("Approved")
        APPLYING = "APPLYING", _("Applying")
        COMPLETED = "COMPLETED", _("Completed")
        PARTIAL_FAILED = "PARTIAL_FAILED", _("Partial Failed")
        FAILED = "FAILED", _("Failed")
        CANCELLED = "CANCELLED", _("Cancelled")

    class Strategy(models.TextChoices):
        ATOMIC_BATCH = "ATOMIC_BATCH", _("Atomic Batch")
        ITEMIZED_COMMIT = "ITEMIZED_COMMIT", _("Itemized Commit")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    batch_no = models.CharField(max_length=64)
    title = models.CharField(max_length=200)
    reason = models.TextField(blank=True, default="")
    action_id = models.ForeignKey(
        "hr_changes.HrChangeAction", on_delete=models.PROTECT, related_name="bulk_batches"
    )
    requested_effective_at = models.DateField()

    # 公共目标（组织重组场景）；逐项可覆盖
    target_org_id = models.ForeignKey(
        "hr_structure.HrOrganization",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="hr06_bulk_batches",
    )
    target_position_id = models.ForeignKey(
        "hr_structure.HrPosition",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="hr06_bulk_batches",
    )

    strategy = models.CharField(
        max_length=16, choices=Strategy.choices, default=Strategy.ITEMIZED_COMMIT
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    created_by = models.BigIntegerField(null=True, blank=True)
    error_workbook_json = models.JSONField(default=dict, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Bulk Change Batch")
        verbose_name_plural = _("HR Bulk Change Batches")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "batch_no"],
                name="uniq_hr_bulk_batch_tenant_no",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "status", "requested_effective_at"]),
        ]

    def __str__(self):
        return f"{self.batch_no} {self.title} [{self.status}]"


class HrBulkChangeItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch_id = models.ForeignKey(
        HrBulkChangeBatch, on_delete=models.CASCADE, related_name="items"
    )
    tenant_id = models.BigIntegerField(db_index=True)
    staff_master_id = models.ForeignKey(
        "hr_staff.HrStaffMaster", on_delete=models.PROTECT, related_name="hr06_bulk_items"
    )
    # 每人独立 Case（生效走 Apply Service）
    change_case_id = models.ForeignKey(
        "hr_changes.HrPersonnelChangeCase",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bulk_items",
    )
    validation_status = models.CharField(max_length=16, default="PENDING")
    execution_status = models.CharField(max_length=16, default="PENDING")
    error_json = models.JSONField(default=dict, blank=True)
    sequence = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Bulk Change Item")
        verbose_name_plural = _("HR Bulk Change Items")
        indexes = [
            models.Index(fields=["tenant_id", "batch_id", "execution_status"]),
        ]

    def __str__(self):
        return f"{self.batch_id.batch_no} item#{self.sequence}"
