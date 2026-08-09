"""
hr_staff/models/employment.py —— 第三层：HrEmploymentRelationship 聘用关系（总册 §7.3/§20.4）。

表达：正式聘用/合同制/人事代理/外聘/退休返聘/再次入职等；
- 同一 Person 可多关系（返聘/再次入职/外聘）；
- 时间段 [effective_from, effective_to)，NULL=开放结束；
- 禁止只保存一条当前入职日期。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_staff.constants import RelationshipStatus, RelationshipType


class HrEmploymentRelationship(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    staff_id = models.ForeignKey(
        "hr_staff.HrStaffMaster", on_delete=models.PROTECT, related_name="employment_relationships"
    )
    relationship_type = models.CharField(
        max_length=32, choices=RelationshipType.choices, default=RelationshipType.REGULAR_EMPLOYMENT
    )
    employment_type = models.CharField(max_length=32, blank=True, default="")
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)  # 半开区间 [from, to)，NULL=开放
    status = models.CharField(
        max_length=16, choices=RelationshipStatus.choices, default=RelationshipStatus.ACTIVE
    )
    source_business_type = models.CharField(max_length=64, blank=True, default="")
    source_business_id = models.CharField(max_length=64, blank=True, default="")
    reason_code = models.CharField(max_length=64, blank=True, default="")
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Employment Relationship")
        verbose_name_plural = _("HR Employment Relationships")
        constraints = [
            models.CheckConstraint(
                check=models.Q(effective_to__isnull=True)
                | models.Q(effective_to__gt=models.F("effective_from")),
                name="chk_hr_rel_effective_to_gt_from",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "staff_id", "effective_from"]),
            models.Index(fields=["tenant_id", "status"]),
        ]

    def __str__(self):
        return f"{self.staff_id.staff_no} {self.relationship_type} [{self.effective_from}~{self.effective_to or '∞'}]"
