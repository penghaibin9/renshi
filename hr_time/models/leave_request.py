"""
hr_time/models/leave_request.py

S8 请假申请/审批/销假（总册 §98-107、§192）。

- HrLeaveRequest：申请 + 状态机（RETURNED≠REJECTED、WITHDRAW≠CANCEL）
- HrLeaveApprovalSnapshot：审批快照（workflow_version/approver_chain/提交 hash）
- HrAbsenceFact：缺勤事实（独立于打卡）
- HrReturnFromLeaveCase：销假 case（销假=case，不是改 status）
- HrLeaveEvidence：证明材料（私密存储 + 短期签名 URL）

铁律（总册 §99-105、§199）：
- RETURNED 可修改保留原版本；REJECTED 终局释放 reservation；
- 已批准请假不可直接 edit，变更走 ChangeCase；
- 取消已部分使用的申请必须计算已用 portion；
- 销假不是把 status 改成 DONE；
- 已销假 ≠ 已请假。
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from hr_time.enums import LeaveRequestStatus
from hr_time.models.base import TimeTenantModel
from hr_time.models.leave import HrLeaveAccount, HrLeaveLedgerEntry, HrLeaveType


class HrLeaveRequest(TimeTenantModel):
    """请假申请（§98）。"""

    staff_master_id = models.BigIntegerField(verbose_name=_("HR03 人员 id"))
    assignment_id = models.BigIntegerField(null=True, blank=True)
    leave_type = models.ForeignKey(
        HrLeaveType, on_delete=models.PROTECT, related_name="requests"
    )
    policy_version_id = models.BigIntegerField(null=True, blank=True)
    start_at = models.DateField(verbose_name=_("开始日期"))
    end_at = models.DateField(verbose_name=_("结束日期"))
    start_breakdown = models.CharField(
        max_length=16,
        choices=[
            ("FULL_DAY", _("全天")),
            ("HALF_DAY_AM", _("上午半天")),
            ("HALF_DAY_PM", _("下午半天")),
            ("HOURS", _("小时")),
        ],
        default="FULL_DAY",
    )
    end_breakdown = models.CharField(
        max_length=16,
        choices=[
            ("FULL_DAY", _("全天")),
            ("HALF_DAY_AM", _("上午半天")),
            ("HALF_DAY_PM", _("下午半天")),
            ("HOURS", _("小时")),
        ],
        default="FULL_DAY",
    )
    requested_amount = models.DecimalField(
        max_digits=8, decimal_places=2, verbose_name=_("申请数量")
    )
    calculated_amount = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True, verbose_name=_("计算数量")
    )
    unit = models.CharField(
        max_length=16,
        choices=[("DAYS", _("天")), ("HOURS", _("小时")), ("MINUTES", _("分钟"))],
        default="DAYS",
    )
    reason_category = models.CharField(max_length=32, blank=True, default="")
    reason_text = models.CharField(
        max_length=255, blank=True, default="", verbose_name=_("原因（敏感字段按假别受限）")
    )
    account = models.ForeignKey(
        HrLeaveAccount,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="requests",
    )
    reservation_id = models.BigIntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=32,
        choices=LeaveRequestStatus.choices,
        default=LeaveRequestStatus.DRAFT,
    )
    version = models.PositiveIntegerField(default=1, verbose_name=_("版本号"))
    return_reason = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        verbose_name = _("Leave Request")
        verbose_name_plural = _("Leave Requests")
        indexes = [
            models.Index(
                fields=["tenant_id", "staff_master_id", "status"],
                name="hr11_lreq_ten_staff_status",
            ),
        ]

    def clean(self):
        super().clean()
        if self.end_at < self.start_at:
            raise ValidationError(_("结束日期早于开始日期"))

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"[{self.tenant_id}] staff={self.staff_master_id} {self.leave_type.code} {self.status}"


class HrLeaveApprovalSnapshot(TimeTenantModel):
    """审批快照（§101）：流程配置变化不污染旧审批。"""

    leave_request = models.ForeignKey(
        HrLeaveRequest, on_delete=models.CASCADE, related_name="approval_snapshots"
    )
    workflow_version = models.CharField(max_length=32, verbose_name=_("流程版本"))
    approver_chain = models.JSONField(default=list, verbose_name=_("审批链"))
    approval_rules_snapshot = models.JSONField(default=dict, blank=True)
    submitted_data_hash = models.CharField(max_length=64, verbose_name=_("提交数据哈希"))
    decisions = models.JSONField(default=list, blank=True, verbose_name=_("决策链"))
    final_decision_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("Leave Approval Snapshot")
        verbose_name_plural = _("Leave Approval Snapshots")

    def __str__(self):
        return f"[{self.tenant_id}] request={self.leave_request_id} v{self.workflow_version}"


class HrAbsenceFact(TimeTenantModel):
    """缺勤事实（§107）：独立于打卡，Time Card 只是展示/投影。"""

    leave_request = models.ForeignKey(
        HrLeaveRequest, on_delete=models.PROTECT, related_name="absence_facts"
    )
    staff_master_id = models.BigIntegerField(verbose_name=_("HR03 人员 id"))
    start_at = models.DateField(verbose_name=_("开始日期"))
    end_at = models.DateField(verbose_name=_("结束日期"))
    scheduled_minutes_impacted = models.PositiveIntegerField(
        default=0, verbose_name=_("影响排班时长（分钟）")
    )
    chargeable_amount = models.DecimalField(
        max_digits=8, decimal_places=2, default=0, verbose_name=_("可扣数量")
    )
    paid_classification = models.CharField(
        max_length=16,
        choices=[
            ("PAID", _("带薪")),
            ("UNPAID", _("无薪")),
            ("POLICY_DEPENDENT", _("依政策")),
        ],
        default="POLICY_DEPENDENT",
    )
    policy_version_id = models.BigIntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=[
            ("ACTIVE", _("生效")),
            ("SUPERSEDED", _("被取代")),
            ("CANCELLED", _("已取消")),
        ],
        default="ACTIVE",
    )
    effective_snapshot = models.JSONField(default=dict, blank=True)
    fact_version = models.PositiveIntegerField(default=1, verbose_name=_("事实版本"))

    class Meta:
        verbose_name = _("Absence Fact")
        verbose_name_plural = _("Absence Facts")
        indexes = [
            models.Index(
                fields=["tenant_id", "staff_master_id", "start_at"],
                name="hr11_absfact_ten_staff_start",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] staff={self.staff_master_id} {self.start_at}~{self.end_at}"


class HrReturnFromLeaveCase(TimeTenantModel):
    """销假 case（§105）：销假不是改 status。"""

    leave_request = models.ForeignKey(
        HrLeaveRequest, on_delete=models.PROTECT, related_name="return_cases"
    )
    actual_return_at = models.DateField(verbose_name=_("实际返岗日期"))
    expected_return_at = models.DateField(verbose_name=_("预期返岗日期"))
    early_return = models.BooleanField(default=False, verbose_name=_("提前返岗"))
    evidence = models.CharField(max_length=255, blank=True, default="")
    resulting_usage_adjustment = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        verbose_name=_("用量调整"),
    )
    schedule_restore_status = models.CharField(max_length=16, default="PENDING")
    downstream_reconcile_status = models.CharField(max_length=16, default="PENDING")

    class Meta:
        verbose_name = _("Return From Leave Case")
        verbose_name_plural = _("Return From Leave Cases")

    def __str__(self):
        return f"[{self.tenant_id}] request={self.leave_request_id} return={self.actual_return_at}"


class HrLeaveEvidence(TimeTenantModel):
    """证明材料（§97）：私密存储 + 短期签名 URL + 下载前重新鉴权。"""

    leave_request = models.ForeignKey(
        HrLeaveRequest, on_delete=models.PROTECT, related_name="evidences"
    )
    document_id = models.CharField(max_length=64, verbose_name=_("文档 id"))
    evidence_type = models.CharField(max_length=32, blank=True, default="")
    verification_status = models.CharField(
        max_length=16,
        choices=[
            ("PENDING", _("待核验")),
            ("VERIFIED", _("已核验")),
            ("REJECTED", _("已拒绝")),
        ],
        default="PENDING",
    )
    verifier = models.ForeignKey(
        "horilla_auth.HorillaUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    sensitivity = models.CharField(
        max_length=16,
        choices=[
            ("NORMAL", _("普通")),
            ("MEDICAL", _("医疗")),
            ("RESTRICTED", _("受限")),
        ],
        default="NORMAL",
    )

    class Meta:
        verbose_name = _("Leave Evidence")
        verbose_name_plural = _("Leave Evidences")

    def __str__(self):
        return f"[{self.tenant_id}] request={self.leave_request_id} {self.evidence_type}"
