"""
hr_staff/models/merge.py —— Person Merge/Unmerge 架构位（总册 §52.1）。

HrPersonMergeCase：治理流程，V1 不开放普通 UI merge，但模型必须预留。
合并规则：保留 source→target 的 alias/mapping，不 DELETE source；
支持错误合并的受控逆向处理设计。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class HrPersonMergeCase(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", _("Draft")
        SUBMITTED = "SUBMITTED", _("Submitted")
        APPROVED = "APPROVED", _("Approved")
        APPLIED = "APPLIED", _("Applied")
        REVERSED = "REVERSED", _("Reversed")
        REJECTED = "REJECTED", _("Rejected")
        CANCELLED = "CANCELLED", _("Cancelled")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    case_no = models.CharField(max_length=32)
    source_person_id = models.ForeignKey(
        "hr_staff.HrPerson", on_delete=models.PROTECT, related_name="merge_source_cases"
    )
    target_person_id = models.ForeignKey(
        "hr_staff.HrPerson", on_delete=models.PROTECT, related_name="merge_target_cases"
    )
    reason = models.CharField(max_length=512)
    evidence_material_id = models.UUIDField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    approved_by = models.BigIntegerField(null=True, blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    reversed_at = models.DateTimeField(null=True, blank=True)
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Person Merge Case")
        verbose_name_plural = _("HR Person Merge Cases")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "case_no"],
                name="uniq_hr_person_merge_tenant_case_no",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "source_person_id"]),
            models.Index(fields=["tenant_id", "status"]),
        ]

    def __str__(self):
        return f"{self.case_no}: {self.source_person_id.legal_name} → {self.target_person_id.legal_name}"


class HrPersonMergeAlias(models.Model):
    """合并后保留旧 Person ID 映射（§52.1：不 DELETE source）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    merge_case_id = models.ForeignKey(
        "hr_staff.HrPersonMergeCase", on_delete=models.PROTECT, related_name="aliases"
    )
    source_person_id = models.UUIDField(db_index=True)
    target_person_id = models.UUIDField(db_index=True)
    alias_status = models.CharField(max_length=16, default="ACTIVE")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Person Merge Alias")
        verbose_name_plural = _("HR Person Merge Aliases")
        indexes = [
            models.Index(fields=["tenant_id", "source_person_id"]),
        ]

    def __str__(self):
        return f"alias {self.source_person_id} → {self.target_person_id}"
