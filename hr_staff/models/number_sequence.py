"""
hr_staff/models/number_sequence.py —— 工号序列（P1-j）。

解决 next_staff_no 的两个并发/截断问题：
- 不再 `select_for_update()[:5000]`（>5000 人截断）；
- 序列行行锁 + (tenant_id, prefix) 唯一，分配 O(1)，并发安全。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class HrStaffNumberSequence(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    prefix = models.CharField(max_length=16)
    next_value = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Staff Number Sequence")
        verbose_name_plural = _("HR Staff Number Sequences")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "prefix"],
                name="uniq_hr_staff_number_sequence",
            ),
        ]

    def __str__(self):
        return f"tenant={self.tenant_id} prefix={self.prefix} next={self.next_value}"
