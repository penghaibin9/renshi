"""
hr_changes/models/snapshot.py —— 审批快照 + 生效快照（总册 §20/§33）。

- HrChangeApprovalSnapshot：审批流程配置变化不能改变已提交案件（workflow_version 冻结）；
- HrChangeEffectiveSnapshot：生效后不可变（checksum；correction 走受控流程，不原地改）。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class HrChangeApprovalSnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    change_case_id = models.ForeignKey(
        "hr_changes.HrPersonnelChangeCase",
        on_delete=models.CASCADE,
        related_name="approval_snapshots",
    )
    workflow_version = models.PositiveIntegerField(default=1)
    steps_json = models.JSONField(default=list, blank=True)  # [{step_no, approver_role, org_id, required, ...}]
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Change Approval Snapshot")
        verbose_name_plural = _("HR Change Approval Snapshots")
        constraints = [
            models.UniqueConstraint(
                fields=["change_case_id", "workflow_version"],
                name="uniq_hr_change_approval_case_version",
            ),
        ]

    def __str__(self):
        return f"{self.change_case_id.case_no} approval v{self.workflow_version}"


class HrChangeEffectiveSnapshot(models.Model):
    """生效快照（不可变，用于审计/重放/对账）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    change_case_id = models.OneToOneField(
        "hr_changes.HrPersonnelChangeCase",
        on_delete=models.CASCADE,
        related_name="effective_snapshot",
    )
    applied_at = models.DateTimeField()
    effective_at = models.DateField()

    before_json = models.JSONField(default=dict, blank=True)
    after_json = models.JSONField(default=dict, blank=True)
    source_fact_ids_json = models.JSONField(default=list, blank=True)
    target_fact_ids_json = models.JSONField(default=list, blank=True)
    position_changes_json = models.JSONField(default=dict, blank=True)
    downstream_plan_version = models.PositiveIntegerField(default=1)

    # 内容校验和（禁原地改：correction 生成新版本而非改本行）
    checksum = models.CharField(max_length=64, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Change Effective Snapshot")
        verbose_name_plural = _("HR Change Effective Snapshots")

    def __str__(self):
        return f"{self.change_case_id.case_no} effective@{self.effective_at}"
