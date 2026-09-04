"""
hr_staff/models/assignment.py —— 第四层：HrStaffAssignment 任职事实（总册 §7.4/§20.5）。

不变量：
- 同一 relationship 同一日期最多一个 PRIMARY（DB：开放 PRIMARY 条件唯一 + service 事务锁双重保障）；
- concurrent 可多个；
- FTE 上限按学校策略校验；
- organization/position 必须 tenant 相同且 as_of 有效；
- 历史区间不得无语义重叠；
- 关闭关系必须关闭或计划关闭未结束 assignment。

HR02 硬门：organization_id/position_id/post_catalog_id 直指 hr_structure 权威模型；
legacy_department_id/legacy_job_position_id 为只读映射列（不固化 legacy FK）。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_staff.constants import AssignmentStatus, AssignmentType


class HrStaffAssignment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    employment_relationship_id = models.ForeignKey(
        "hr_staff.HrEmploymentRelationship",
        on_delete=models.PROTECT,
        related_name="assignments",
    )
    # ---- HR02 权威引用（同 tenant；as_of 必须有效）----
    organization_id = models.ForeignKey(
        "hr_structure.HrOrganization",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="hr03_assignments",
    )
    position_id = models.ForeignKey(
        "hr_structure.HrPosition",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="hr03_assignments",
    )
    post_catalog_id = models.ForeignKey(
        "hr_structure.HrPostCatalogVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="hr03_assignments",
    )
    # ---- legacy 只读映射（HR02 数据未映射前 LEGACY_CURRENT_SNAPSHOT 预览）----
    legacy_department_id = models.BigIntegerField(null=True, blank=True)
    legacy_job_position_id = models.BigIntegerField(null=True, blank=True)
    # ---- 任职语义 ----
    assignment_type = models.CharField(
        max_length=16,
        choices=AssignmentType.choices,
        default=AssignmentType.PRIMARY,
    )
    assignment_role_code = models.CharField(max_length=64, blank=True, default="")
    location_code = models.CharField(max_length=128, blank=True, default="")
    fte = models.DecimalField(max_digits=5, decimal_places=2, default=1.00)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)  # 半开区间
    reporting_staff_id = models.ForeignKey(
        "hr_staff.HrStaffMaster",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reports_to_assignments",
    )
    source_business_type = models.CharField(max_length=64, blank=True, default="")
    source_business_id = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(
        max_length=16, choices=AssignmentStatus.choices, default=AssignmentStatus.ACTIVE
    )
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Staff Assignment")
        verbose_name_plural = _("HR Staff Assignments")
        constraints = [
            models.CheckConstraint(
                check=models.Q(effective_to__isnull=True)
                | models.Q(effective_to__gt=models.F("effective_from"))
                | models.Q(status="CANCELLED"),
                name="chk_hr_assignment_effective_to_gt_from",
            ),
            # 同关系最多一个开放结束的 PRIMARY（历史已关闭段用 effective_to 关闭，不受此限制）
            models.UniqueConstraint(
                fields=["tenant_id", "employment_relationship_id"],
                condition=models.Q(assignment_type="PRIMARY", effective_to__isnull=True),
                name="uniq_hr_assignment_open_primary_per_rel",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "employment_relationship_id", "effective_from"]),
            models.Index(fields=["tenant_id", "organization_id", "effective_from", "effective_to"]),
            models.Index(fields=["tenant_id", "position_id", "effective_from", "effective_to"]),
            models.Index(fields=["tenant_id", "status"]),
        ]

    def __str__(self):
        return f"{self.employment_relationship_id} {self.assignment_type} [{self.effective_from}~{self.effective_to or '∞'}]"
