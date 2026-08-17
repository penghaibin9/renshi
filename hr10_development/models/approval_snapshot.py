"""
hr10_development/models/approval_snapshot.py

审批快照（总册 §51）。
审批时保存 workflow_policy_version_id + step_no + object_version + snapshot_hash。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr10_development.models.base import DevelopmentTenantModel


class HrDevelopmentApprovalSnapshot(DevelopmentTenantModel):
    """不可变审批快照——审批时冻结的对象状态。"""

    case_type = models.CharField(
        max_length=64,
        db_index=True,
        verbose_name=_("case 类型"),
    )

    case_id = models.BigIntegerField(
        db_index=True,
        verbose_name=_("case ID"),
    )

    workflow_policy_version_id = models.CharField(
        max_length=128,
        verbose_name=_("工作流政策版本 ID"),
    )

    step_no = models.IntegerField(
        verbose_name=_("步骤号"),
    )

    role = models.CharField(
        max_length=64,
        verbose_name=_("审批角色"),
    )

    approver_id = models.BigIntegerField(
        verbose_name=_("审批人 ID"),
    )

    organization_scope = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name=_("组织范围"),
    )

    decision = models.CharField(
        max_length=32,
        verbose_name=_("决定"),
    )

    reason_code = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name=_("原因码"),
    )

    comment = models.TextField(
        blank=True,
        default="",
        verbose_name=_("备注"),
    )

    object_version = models.IntegerField(
        verbose_name=_("对象版本"),
    )

    snapshot_hash = models.CharField(
        max_length=128,
        verbose_name=_("快照哈希"),
    )

    decided_at = models.DateTimeField(
        verbose_name=_("决定时间"),
    )

    class Meta:
        db_table = "hr_development_approval_snapshot"
        verbose_name = _("审批快照")
        verbose_name_plural = verbose_name
        unique_together = [
            ("case_type", "case_id", "step_no"),
        ]
        indexes = [
            models.Index(fields=["approver_id", "created_at"]),
        ]
