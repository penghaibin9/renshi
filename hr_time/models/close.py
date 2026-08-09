"""
hr_time/models/close.py

S9 月结冻结（总册 §113-120、§193）。

- HrTimeClosePeriod：月结期间（OPEN/PRE_CLOSE/CLOSED/REOPENED）
- HrTimeCloseSnapshot：月结快照（版本引用 + 各类事实 hash，供 HR15/HR12 引用）
- HrTimeCorrectionBatch：重开更正批次
- HrPayrollTimeBasis：HR15 时间基础（不含金额）
- HrTimeRiskCase：风险中心（旷工阈值等）

铁律（总册 §113-117、§199）：
- 月结不是导出 Excel，是正式业务动作；
- 已 CLOSED 期间不得普通编辑；重开必须走 Correction Batch；
- Payroll basis 不包含工资金额；HR15 拿的是 basis，不是 raw；
- 旧 snapshot 保留（重开后生成新 snapshot）。
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_time.models.base import TimeTenantModel


class HrTimeClosePeriod(TimeTenantModel):
    """月结期间（§113）。"""

    period_type = models.CharField(
        max_length=16,
        choices=[("MONTHLY", _("月度")), ("CUSTOM", _("自定义"))],
        default="MONTHLY",
    )
    start_date = models.DateField(verbose_name=_("开始日期"))
    end_date = models.DateField(verbose_name=_("结束日期"))
    status = models.CharField(
        max_length=16,
        choices=[
            ("OPEN", _("开启")),
            ("PRE_CLOSE", _("预关闭")),
            ("CLOSED", _("已关闭")),
            ("REOPENED", _("已重开")),
        ],
        default="OPEN",
    )
    close_rule_version = models.CharField(max_length=32, blank=True, default="")
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        "horilla_auth.HorillaUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    snapshot_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = _("Time Close Period")
        verbose_name_plural = _("Time Close Periods")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "start_date", "end_date"],
                name="uniq_hr11_close_period",
            ),
        ]

    def clean(self):
        super().clean()
        if self.end_date < self.start_date:
            raise ValidationError(_("结束日期早于开始日期"))

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"[{self.tenant_id}] {self.start_date}~{self.end_date} {self.status}"


class HrTimeCloseSnapshot(TimeTenantModel):
    """月结快照（§115）：供 HR15/HR12 引用。"""

    period = models.ForeignKey(
        HrTimeClosePeriod, on_delete=models.PROTECT, related_name="snapshots"
    )
    metric_definition_version = models.CharField(max_length=32, default="1.0")
    policy_versions = models.JSONField(default=list, blank=True)
    calendar_versions = models.JSONField(default=list, blank=True)
    staff_count = models.PositiveIntegerField(default=0)
    attendance_fact_hash = models.CharField(max_length=64, blank=True, default="")
    leave_ledger_hash = models.CharField(max_length=64, blank=True, default="")
    overtime_fact_hash = models.CharField(max_length=64, blank=True, default="")
    close_summary_json = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = _("Time Close Snapshot")
        verbose_name_plural = _("Time Close Snapshots")

    def __str__(self):
        return f"[{self.tenant_id}] period={self.period_id} snapshot={self.pk}"


class HrTimeCorrectionBatch(TimeTenantModel):
    """重开更正批次（§117）。"""

    period = models.ForeignKey(
        HrTimeClosePeriod, on_delete=models.PROTECT, related_name="correction_batches"
    )
    reason = models.CharField(max_length=255, verbose_name=_("原因"))
    scope = models.JSONField(default=dict, blank=True)
    impacted_staff_ids = models.JSONField(default=list, blank=True)
    before_snapshot_id = models.BigIntegerField(null=True, blank=True)
    change_cases = models.JSONField(default=list, blank=True)
    after_snapshot_id = models.BigIntegerField(null=True, blank=True)
    approved_by = models.ForeignKey(
        "horilla_auth.HorillaUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    audit = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = _("Time Correction Batch")
        verbose_name_plural = _("Time Correction Batches")

    def __str__(self):
        return f"[{self.tenant_id}] period={self.period_id} batch={self.pk}"


class HrPayrollTimeBasis(TimeTenantModel):
    """HR15 时间基础（§119）：不包含工资金额。"""

    close_snapshot = models.ForeignKey(
        HrTimeCloseSnapshot, on_delete=models.PROTECT, related_name="payroll_bases"
    )
    staff_master_id = models.BigIntegerField(verbose_name=_("HR03 人员 id"))
    regular_work_minutes = models.PositiveIntegerField(default=0)
    payable_authorized_absence_minutes = models.PositiveIntegerField(default=0)
    unpaid_absence_minutes = models.PositiveIntegerField(default=0)
    verified_overtime_minutes = models.PositiveIntegerField(default=0)
    comp_time_minutes = models.PositiveIntegerField(default=0)
    unexcused_absence_minutes = models.PositiveIntegerField(default=0)
    basis_version = models.CharField(max_length=16, default="1.0")

    class Meta:
        verbose_name = _("Payroll Time Basis")
        verbose_name_plural = _("Payroll Time Bases")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "close_snapshot", "staff_master_id"],
                name="uniq_hr11_basis_snapshot_staff",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] snapshot={self.close_snapshot_id} staff={self.staff_master_id}"


class HrTimeRiskCase(TimeTenantModel):
    """风险中心（§123）。"""

    RISK_CODES = [
        ("UNEXCUSED_ABSENCE_THRESHOLD", _("旷工阈值")),
        ("DEVICE_DATA_GAP", _("设备数据缺口")),
        ("LEAVE_LEDGER_DRIFT", _("假期账户漂移")),
        ("POLICY_AMBIGUITY", _("规则歧义")),
        ("SCHEDULE_GAP", _("排班缺口")),
        ("CLOSE_OVERDUE", _("月结逾期")),
        ("OVERTIME_ANOMALY", _("加班异常")),
        ("MASS_LATE_PATTERN", _("集中迟到模式")),
        ("SOURCE_RECONCILIATION_FAILED", _("数据源对账失败")),
    ]

    risk_code = models.CharField(max_length=40, choices=RISK_CODES)
    staff_master_id = models.BigIntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=[
            ("OPEN", _("待处理")),
            ("ACKNOWLEDGED", _("已确认")),
            ("RESOLVED", _("已解决")),
        ],
        default="OPEN",
    )
    severity = models.CharField(
        max_length=16,
        choices=[
            ("LOW", _("低")),
            ("MEDIUM", _("中")),
            ("HIGH", _("高")),
            ("CRITICAL", _("严重")),
        ],
        default="MEDIUM",
    )
    owner_role = models.CharField(max_length=64, blank=True, default="")
    summary = models.TextField(blank=True, default="")
    evidence = models.JSONField(default=dict, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        verbose_name = _("Time Risk Case")
        verbose_name_plural = _("Time Risk Cases")
        indexes = [
            models.Index(
                fields=["tenant_id", "status", "severity"],
                name="hr11_risk_ten_status_sev",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] {self.risk_code} {self.status}"
