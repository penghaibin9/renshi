"""
hr_external/models/projection.py —— Legacy 投影状态（S9，总册 §112-113/§6.3）。

- Active External Engagement → External Worker Projection → Horilla Employee / WorkInformation；
- worker_kind = EXTERNAL 标记（投影状态表，不越界改 HR03/HrStaffMaster/legacy Employee 表结构）；
- 投影方向单向 authority → legacy（§55）；禁止 legacy 反向覆盖 authority。
- 投影副作用禁令（§113）：不得因投影自动进入正式 payroll/leave/attendance/编制/manager/benefits。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class ProjectionStatus(models.TextChoices):
    ACTIVE = "ACTIVE", _("Active")
    LEGACY_EMPLOYEE_MISSING = "LEGACY_EMPLOYEE_MISSING", _("Legacy Employee Missing")
    DRIFT = "DRIFT", _("Drift")
    SUPERSEDED = "SUPERSEDED", _("Superseded")


class HrExternalProjectionState(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    external_profile_id = models.ForeignKey(
        "hr_external.HrExternalTeacherProfile",
        on_delete=models.PROTECT,
        related_name="projection_states",
    )
    worker_kind = models.CharField(max_length=16, default="EXTERNAL")
    # 标记不落入正式 payroll/leave/attendance/编制（§113）
    regular_employee = models.BooleanField(default=False)
    benefits_eligible = models.BooleanField(default=False)
    payroll_regular = models.BooleanField(default=False)
    attendance_regular = models.BooleanField(default=False)
    legacy_employee_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    legacy_badge_id = models.CharField(max_length=64, blank=True, default="")
    projection_hash = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(
        max_length=32,
        choices=ProjectionStatus.choices,
        default=ProjectionStatus.ACTIVE,
    )
    last_projected_at = models.DateTimeField(null=True, blank=True)
    last_reconciled_at = models.DateTimeField(null=True, blank=True)
    mismatch_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR External Projection State")
        verbose_name_plural = _("HR External Projection States")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "external_profile_id"],
                name="uniq_hr_external_projection_profile",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "status"],
                name="hex_projection_status_idx",
            ),
            models.Index(
                fields=["tenant_id", "legacy_employee_id"],
                name="hex_projection_legacy_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] {self.external_profile_id_id} worker={self.worker_kind} ({self.status})"
