"""
hr_changes/models/correction.py —— HrChangeCorrection 数据纠错（总册 §34/§35）。

Correction ≠ Change：发现原记录录错，走受控流程，不伪造成第二次业务异动。
高权限（hr.change.correct）；若影响下游历史事实必须执行 Impact Analysis。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class HrChangeCorrection(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", _("Draft")
        SUBMITTED = "SUBMITTED", _("Submitted")
        UNDER_REVIEW = "UNDER_REVIEW", _("Under Review")
        RETURNED = "RETURNED", _("Returned")
        APPROVED = "APPROVED", _("Approved")
        APPLYING = "APPLYING", _("Applying")
        APPLIED = "APPLIED", _("Applied")
        REJECTED = "REJECTED", _("Rejected")
        CANCELLED = "CANCELLED", _("Cancelled")
        FAILED = "FAILED", _("Failed")

    class CorrectionType(models.TextChoices):
        DATE = "DATE", _("Date")
        TARGET_VALUE = "TARGET_VALUE", _("Target Value")
        SOURCE_REF = "SOURCE_REF", _("Source Ref")
        OTHER = "OTHER", _("Other")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    change_case_id = models.ForeignKey(
        "hr_changes.HrPersonnelChangeCase",
        on_delete=models.CASCADE,
        related_name="corrections",
    )
    correction_type = models.CharField(
        max_length=24, choices=CorrectionType.choices, default=CorrectionType.TARGET_VALUE
    )
    requested_values_json = models.JSONField(default=dict, blank=True)
    reason = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    requested_by = models.BigIntegerField(null=True, blank=True)
    approved_by = models.BigIntegerField(null=True, blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    previous_snapshot_hash = models.CharField(max_length=64, blank=True, default="")
    new_snapshot_hash = models.CharField(max_length=64, blank=True, default="")
    authority_version = models.BigIntegerField(default=0)
    authority_snapshot_hash = models.CharField(max_length=64, blank=True, default="")
    provider_code = models.CharField(max_length=32, blank=True, default="")
    provider_case_id = models.UUIDField(null=True, blank=True)
    provider_case_version = models.BigIntegerField(null=True, blank=True)
    applied_fields_json = models.JSONField(default=list, blank=True)
    evidence_material_id = models.UUIDField(null=True, blank=True)
    create_idempotency_key = models.CharField(max_length=64)
    create_request_hash = models.CharField(max_length=64, blank=True, default="")
    apply_idempotency_key = models.CharField(max_length=64, blank=True, default="")
    apply_error = models.TextField(blank=True, default="")
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Change Correction")
        verbose_name_plural = _("HR Change Corrections")
        indexes = [
            models.Index(fields=["tenant_id", "status", "created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "create_idempotency_key"],
                name="uniq_hr_change_correction_create_key",
            ),
        ]

    def __str__(self):
        return f"{self.change_case_id.case_no} correction [{self.status}]"
