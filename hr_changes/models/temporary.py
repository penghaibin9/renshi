"""
hr_changes/models/temporary.py —— HrTemporaryAssignmentLink 临时异动链接（总册 §27）。

借调/挂职不是"再改一次部门"：保留 source assignment、临时 assignment、
预计返岗日、return 关系；延期不直接覆盖 expected_return_at。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_changes.constants import SourceAssignmentPolicy


class HrTemporaryAssignmentExtension(models.Model):
    """临时异动延期（总册 §29）—— 不直接覆盖 expected_return_at。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    link_id = models.ForeignKey(
        "hr_changes.HrTemporaryAssignmentLink",
        on_delete=models.CASCADE,
        related_name="extensions",
    )
    old_return_at = models.DateField()
    new_return_at = models.DateField()
    reason = models.TextField(blank=True, default="")
    requested_by = models.BigIntegerField(null=True, blank=True)
    approved_by = models.BigIntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=(
            ("PENDING", _("Pending")),
            ("APPROVED", _("Approved")),
            ("REJECTED", _("Rejected")),
            ("APPLIED", _("Applied")),
        ),
        default="PENDING",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("HR Temporary Assignment Extension")
        verbose_name_plural = _("HR Temporary Assignment Extensions")
        indexes = [
            models.Index(fields=["tenant_id", "status", "created_at"]),
        ]

    def __str__(self):
        return f"{self.link_id.change_case_id.case_no} {self.old_return_at}→{self.new_return_at} [{self.status}]"


class HrTemporaryAssignmentLink(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", _("Active")
        EXTENDED = "EXTENDED", _("Extended")
        RETURNING = "RETURNING", _("Returning")
        RETURNED = "RETURNED", _("Returned")
        OVERDUE = "OVERDUE", _("Overdue")
        CANCELLED = "CANCELLED", _("Cancelled")
        RETURN_TARGET_INVALID = "RETURN_TARGET_INVALID", _("Return Target Invalid")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    change_case_id = models.ForeignKey(
        "hr_changes.HrPersonnelChangeCase",
        on_delete=models.PROTECT,
        related_name="temporary_links",
    )
    source_assignment_id = models.ForeignKey(
        "hr_staff.HrStaffAssignment",
        on_delete=models.PROTECT,
        related_name="hr06_temporary_source_links",
    )
    temporary_assignment_id = models.ForeignKey(
        "hr_staff.HrStaffAssignment",
        on_delete=models.PROTECT,
        related_name="hr06_temporary_links",
    )

    start_at = models.DateField()
    expected_return_at = models.DateField()
    return_case_id = models.ForeignKey(
        "hr_changes.HrPersonnelChangeCase",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="return_of_temporary",
    )

    # 原岗处理策略（总册 §27.4）
    source_assignment_status_policy = models.CharField(
        max_length=24,
        choices=SourceAssignmentPolicy.choices,
        default=SourceAssignmentPolicy.KEEP_ACTIVE,
    )
    return_policy_json = models.JSONField(default=dict, blank=True)

    status = models.CharField(max_length=24, choices=Status.choices, default=Status.ACTIVE)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Temporary Assignment Link")
        verbose_name_plural = _("HR Temporary Assignment Links")
        indexes = [
            models.Index(fields=["tenant_id", "status", "expected_return_at"]),
            models.Index(fields=["tenant_id", "source_assignment_id", "status"]),
        ]

    def __str__(self):
        return f"{self.change_case_id.case_no} temp[{self.start_at}~{self.expected_return_at}] {self.status}"
