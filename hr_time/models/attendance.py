"""
hr_time/models/attendance.py

S5 考勤事实（总册 §60、§64、§68、§189）。

- HrAttendanceDayFact：日考勤权威事实（评估器产物，不是 Raw Event）
- HrTimeBalanceLedger：工时账户 Ledger（禁止只存 running total）
- HrTimeSheetPeriod / HrTimeSheetEntry：工时申报（需要工时申报的人群）

铁律（总册 §60、§64、§199）：
- DayFact 是日考勤权威，Raw Event 不是；
- 禁止只用 P/A/L；状态语义见 AttendanceStatus（§61）；
- Ledger 必须有 credit/debit/source/reversal/balance_after，禁止只存余额数字；
- raw 事件永不 rounding；只有 evaluated/credited 时间才应用取整。
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from hr_time.enums import AttendanceStatus
from hr_time.models.base import TimeTenantModel


class HrAttendanceDayFact(TimeTenantModel):
    """日考勤事实（§60）。这是日考勤权威，不是打卡事件。"""

    staff_master_id = models.BigIntegerField(verbose_name=_("HR03 人员 id"))
    assignment_id = models.BigIntegerField(null=True, blank=True)
    business_date = models.DateField(verbose_name=_("班次业务日期"))
    policy_version_id = models.BigIntegerField(null=True, blank=True)
    calendar_version_id = models.BigIntegerField(null=True, blank=True)
    schedule_snapshot_json = models.JSONField(default=dict, blank=True)
    expected_minutes = models.PositiveIntegerField(
        default=0, verbose_name=_("期望工时（分钟）")
    )
    actual_minutes = models.PositiveIntegerField(
        default=0, verbose_name=_("实际工时（分钟）")
    )
    credited_minutes = models.PositiveIntegerField(
        default=0, verbose_name=_("记入工时（分钟）")
    )
    authorized_absence_minutes = models.PositiveIntegerField(
        default=0, verbose_name=_("授权缺勤（分钟）")
    )
    overtime_minutes_candidate = models.PositiveIntegerField(
        default=0, verbose_name=_("加班候选（分钟）")
    )
    status = models.CharField(
        max_length=32,
        choices=AttendanceStatus.choices,
        default=AttendanceStatus.MISSING_TIME,
    )
    evaluation_version = models.PositiveIntegerField(
        default=1, verbose_name=_("评估版本")
    )
    source_pair_ids = models.JSONField(
        default=list, blank=True, verbose_name=_("来源配对 id 列表")
    )
    finalized = models.BooleanField(default=False, verbose_name=_("是否终态"))

    class Meta:
        verbose_name = _("Attendance Day Fact")
        verbose_name_plural = _("Attendance Day Facts")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "staff_master_id", "business_date"],
                name="uniq_hr11_dayfact_staff_date",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "staff_master_id", "business_date"],
                name="hr11_dayfact_ten_staff_date",
            ),
            models.Index(
                fields=["tenant_id", "status", "business_date"],
                name="hr11_dayfact_ten_status_date",
            ),
        ]

    def clean(self):
        super().clean()
        if self.credited_minutes > self.actual_minutes + self.authorized_absence_minutes:
            raise ValidationError(
                _("credited_minutes 不能大于 actual + authorized_absence（禁止虚增记入工时）")
            )

    def delete(self, *args, **kwargs):
        # 已终态（含月结 closed 的投影事实）禁止删除；更正走 Correction Case
        if self.finalized:
            raise ValidationError(_("已终态考勤事实禁止删除；更正请走 Correction Case"))
        super().delete(*args, **kwargs)

    def __str__(self):
        return f"[{self.tenant_id}] staff={self.staff_master_id} {self.business_date} {self.status}"


class HrTimeBalanceLedger(TimeTenantModel):
    """工时账户 Ledger（§64）。余额 = ledger 求和，禁止只存 running total。"""

    ACCOUNT_TYPE = [
        ("WORK_HOURS", _("工时")),
        ("OVERTIME", _("加班")),
        ("COMP_TIME", _("调休")),
        ("PENDING", _("待补")),
    ]
    SOURCE_TYPE = [
        ("ATTENDANCE_DAY_FACT", _("日考勤事实")),
        ("OVERTIME_FACT", _("加班事实")),
        ("COMP_TIME", _("调休")),
        ("ADJUST", _("人工调整")),
        ("MIGRATION", _("迁移")),
        ("REVERSAL", _("冲正")),
    ]

    staff_master_id = models.BigIntegerField(verbose_name=_("HR03 人员 id"))
    account_type = models.CharField(max_length=32, choices=ACCOUNT_TYPE)
    credit_minutes = models.PositiveIntegerField(default=0, verbose_name=_("贷方（分钟）"))
    debit_minutes = models.PositiveIntegerField(default=0, verbose_name=_("借方（分钟）"))
    source_type = models.CharField(max_length=32, choices=SOURCE_TYPE)
    source_id = models.CharField(max_length=64, blank=True, default="")
    effective_date = models.DateField(verbose_name=_("生效日"))
    reversal_of = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    balance_after = models.IntegerField(default=0, verbose_name=_("变动后余额（分钟）"))

    class Meta:
        verbose_name = _("Time Balance Ledger")
        verbose_name_plural = _("Time Balance Ledgers")
        indexes = [
            models.Index(
                fields=["tenant_id", "staff_master_id", "account_type", "effective_date"],
                name="hr11_ledger_ten_staff_type_date",
            ),
        ]

    def clean(self):
        super().clean()
        if self.credit_minutes == 0 and self.debit_minutes == 0:
            raise ValidationError(_("ledger 条目 credit/debit 不能同时为 0"))
        if self.credit_minutes > 0 and self.debit_minutes > 0:
            raise ValidationError(_("ledger 条目不允许同一条目同时有 credit 和 debit"))

    def __str__(self):
        sign = "+" if self.credit_minutes else "-"
        amount = self.credit_minutes or self.debit_minutes
        return f"[{self.tenant_id}] staff={self.staff_master_id} {self.account_type} {sign}{amount}"


class HrTimeSheetPeriod(TimeTenantModel):
    """工时申报期间（§68）。"""

    staff_master_id = models.BigIntegerField(verbose_name=_("HR03 人员 id"))
    start_date = models.DateField(verbose_name=_("开始日期"))
    end_date = models.DateField(verbose_name=_("结束日期"))
    status = models.CharField(
        max_length=16,
        choices=[
            ("DRAFT", _("草稿")),
            ("SUBMITTED", _("已提交")),
            ("APPROVED", _("已批准")),
            ("RETURNED", _("退回")),
        ],
        default="DRAFT",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("Time Sheet Period")
        verbose_name_plural = _("Time Sheet Periods")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "staff_master_id", "start_date", "end_date"],
                name="uniq_hr11_tsp_period",
            ),
        ]

    def clean(self):
        super().clean()
        if self.end_date < self.start_date:
            raise ValidationError(_("结束日期早于开始日期"))

    def __str__(self):
        return f"[{self.tenant_id}] staff={self.staff_master_id} {self.start_date}~{self.end_date}"


class HrTimeSheetEntry(TimeTenantModel):
    """工时申报条目（§68）。Time Sheet 不覆盖 Raw Punch。"""

    period = models.ForeignKey(
        HrTimeSheetPeriod, on_delete=models.CASCADE, related_name="entries"
    )
    date = models.DateField(verbose_name=_("日期"))
    entry_type = models.CharField(
        max_length=32,
        choices=[
            ("ATTENDANCE_TIME", _("出勤时间")),
            ("DUTY_TIME", _("值班时间")),
            ("TRAINING", _("培训")),
            ("TRAVEL", _("出差")),
            ("OVERTIME", _("加班")),
        ],
    )
    minutes = models.PositiveIntegerField(verbose_name=_("时长（分钟）"))
    project_ref = models.CharField(max_length=64, blank=True, default="")
    note = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        verbose_name = _("Time Sheet Entry")
        verbose_name_plural = _("Time Sheet Entries")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "period", "date", "entry_type"],
                name="uniq_hr11_tse_period_date_type",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] {self.period_id} {self.date} {self.entry_type} {self.minutes}min"
