"""
hr_staff/models/staff.py —— 第二层：HrStaffMaster 学校教职工身份（总册 §7.2 / §20.3）。

约束：
- (tenant_id, staff_no) 唯一；
- 同一 tenant 同一 person 默认一份 StaffMaster（canonical）；特殊多身份需显式规则；
- legacy_employee_id 只是映射，不是 authority key；
- current_employment_status / primary_assignment_id 仅投影，由 ProjectionService 维护、可从权威事实重建。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_staff.constants import SourceCategory, StaffCategoryCode


class HrStaffMaster(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    staff_uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    person_id = models.ForeignKey(
        "hr_staff.HrPerson", on_delete=models.PROTECT, related_name="staff_masters"
    )
    staff_no = models.CharField(max_length=64)
    staff_category_code = models.CharField(
        max_length=32,
        choices=StaffCategoryCode.choices,
        default=StaffCategoryCode.TEACHER,
    )
    # ---- 以下仅投影（ProjectionService 维护，可从权威事实重建，禁止当历史来源）----
    current_employment_status = models.CharField(
        max_length=24, blank=True, default="", db_index=True
    )
    primary_assignment_id = models.UUIDField(null=True, blank=True)
    # ---- 溯源 ----
    legacy_employee_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    source = models.CharField(
        max_length=24, choices=SourceCategory.choices, default=SourceCategory.HR_ENTERED
    )
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Staff Master")
        verbose_name_plural = _("HR Staff Masters")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "staff_no"],
                name="uniq_hr_staff_tenant_staff_no",
            ),
            models.UniqueConstraint(
                fields=["tenant_id", "person_id"],
                name="uniq_hr_staff_tenant_person_canonical",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "current_employment_status"]),
            models.Index(fields=["tenant_id", "legacy_employee_id"]),
        ]

    def __str__(self):
        return f"{self.staff_no} ({self.person_id.legal_name})"
