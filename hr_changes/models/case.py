"""
hr_changes/models/case.py —— HrPersonnelChangeCase 异动案件（总册 §9/§10/§11/§12）。

核心语义：
- 不是"修改当前字段"，而是有原因/批准/生效日/前后事实的正式人事事件；
- 状态机见 services/state_machine.py；禁止裸写 status；
- case_no tenant 唯一（并发安全生成见 services/case_number_service.py）；
- 同一人员未来事件冲突用 base_snapshot_version/base_effective_at 检测（总册 §12）。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_changes.constants import CaseStatus, ChangePriority


class HrPersonnelChangeCase(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    case_no = models.CharField(max_length=64)

    # ---- 人员/关系/任职锚点（HR03 权威，PROTECT）----
    staff_master_id = models.ForeignKey(
        "hr_staff.HrStaffMaster", on_delete=models.PROTECT, related_name="change_cases"
    )
    employment_relationship_id = models.ForeignKey(
        "hr_staff.HrEmploymentRelationship",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="change_cases",
    )
    source_assignment_id = models.ForeignKey(
        "hr_staff.HrStaffAssignment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="source_change_cases",
    )

    # ---- 动作/原因（HR06 自身字典）----
    action_id = models.ForeignKey(
        "hr_changes.HrChangeAction", on_delete=models.PROTECT, related_name="cases"
    )
    reason_id = models.ForeignKey(
        "hr_changes.HrChangeReason", on_delete=models.PROTECT, related_name="cases"
    )

    # ---- 生效日期 ----
    requested_effective_at = models.DateField()
    approved_effective_at = models.DateField(null=True, blank=True)  # 审批可能调整生效日

    # ---- 状态机（禁止裸写，走 services/state_machine.py）----
    status = models.CharField(
        max_length=32, choices=CaseStatus.choices, default=CaseStatus.DRAFT, db_index=True
    )

    # ---- 组织/岗位（HR02 权威，PROTECT；null=不涉及）----
    source_org_id = models.ForeignKey(
        "hr_structure.HrOrganization",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="hr06_source_org_cases",
    )
    target_org_id = models.ForeignKey(
        "hr_structure.HrOrganization",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="hr06_target_org_cases",
    )
    source_position_id = models.ForeignKey(
        "hr_structure.HrPosition",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="hr06_source_position_cases",
    )
    target_position_id = models.ForeignKey(
        "hr_structure.HrPosition",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="hr06_target_position_cases",
    )

    # ---- 审批/优先级 ----
    priority = models.CharField(
        max_length=16, choices=ChangePriority.choices, default=ChangePriority.NORMAL
    )
    approval_instance_id = models.CharField(max_length=64, blank=True, default="")

    # ---- Future Event 冲突/Rebase（总册 §12）----
    base_snapshot_version = models.BigIntegerField(default=0)
    base_effective_at = models.DateField(null=True, blank=True)
    rebase_result = models.CharField(max_length=24, blank=True, default="")

    # ---- 发起/归属 ----
    initiator_id = models.BigIntegerField(null=True, blank=True)  # 发起人 user id
    owner_id = models.BigIntegerField(null=True, blank=True)  # 当前处理人 user id

    # ---- 版本/时间戳 ----
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("HR Personnel Change Case")
        verbose_name_plural = _("HR Personnel Change Cases")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "case_no"],
                name="uniq_hr_change_case_tenant_no",
            ),
            # 提交后 effective_at 非空（由状态机强制；DB 兜底语义约束）
            models.CheckConstraint(
                check=models.Q(requested_effective_at__isnull=False),
                name="chk_hr_change_case_effective_not_null",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "status"]),
            models.Index(fields=["tenant_id", "staff_master_id", "requested_effective_at"]),
            models.Index(fields=["tenant_id", "action_id", "status"]),
            models.Index(fields=["tenant_id", "target_org_id", "status"]),
            models.Index(fields=["tenant_id", "requested_effective_at", "status"]),
            models.Index(fields=["staff_master_id", "requested_effective_at"]),
            models.Index(fields=["source_assignment_id", "status"]),
        ]

    def __str__(self):
        return f"{self.case_no} {self.action_id.code} [{self.status}]"
