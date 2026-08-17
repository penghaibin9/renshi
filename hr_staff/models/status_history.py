"""
hr_staff/models/status_history.py —— 人员状态段（总册 §22）。

原则：Staff current status 是关系/任职段推导投影；
HrStatusHistory 记录 HR16 等业务域写入的显式状态变化（离职/退休/停职），
历史不删除；DEPARTED/RETIRED 不是 is_active 翻转。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_staff.constants import StaffStatus


class HrStatusHistory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    staff_id = models.ForeignKey(
        "hr_staff.HrStaffMaster", on_delete=models.PROTECT, related_name="status_history"
    )
    status_code = models.CharField(max_length=24, choices=StaffStatus.choices)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)  # 半开区间
    reason_code = models.CharField(max_length=64, blank=True, default="")
    source_business_type = models.CharField(max_length=64, blank=True, default="")
    source_business_id = models.CharField(max_length=64, blank=True, default="")
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Status History")
        verbose_name_plural = _("HR Status Histories")
        constraints = [
            models.CheckConstraint(
                check=models.Q(effective_to__isnull=True)
                | models.Q(effective_to__gt=models.F("effective_from")),
                name="chk_hr_status_effective_to_gt_from",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "staff_id", "effective_from"]),
        ]

    def __str__(self):
        return f"{self.staff_id.staff_no} {self.status_code} [{self.effective_from}~{self.effective_to or '∞'}]"
