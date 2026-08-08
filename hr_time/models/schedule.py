"""
hr_time/models/schedule.py

S3 班次/轮班/排班（总册 §34-38、§187）。

- HrShiftDefinition / HrShiftVersion：班次逻辑身份 + 版本（跨午夜/宽限/最小工时）
- HrWorkPattern：轮班周期（做一休一/四班三运转/值班轮转/自定义）
- HrScheduleAssignment：个人/岗位排班（as-of 生效）
- HrScheduleException：排班例外（临时换班/培训/出差/教务任务 overlay）

铁律（总册 §46、§199）：
- 多 Assignment 人员：primary + authorized overlays + duty events，冲突必须形成 TimeConflict；
- 临时换班只生成 ScheduleException，不直接改历史排班；
- 排班变更走 ScheduleChangeRequest → 新 future assignment，不原地改。
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from hr_time.models.base import TimeTenantModel
from hr_time.models.calendar import HrWorkCalendarVersion


class HrShiftDefinition(TimeTenantModel):
    """班次逻辑身份。定义身份，不直接修改历史班次内容。"""

    code = models.CharField(max_length=64, verbose_name=_("Code"))
    name = models.CharField(max_length=128, verbose_name=_("Name"))
    shift_family = models.CharField(
        max_length=32, blank=True, default="", verbose_name=_("班次族")
    )
    current_version_id = models.BigIntegerField(
        null=True, blank=True, verbose_name=_("当前版本 id")
    )
    active = models.BooleanField(default=True, verbose_name=_("启用"))

    class Meta:
        verbose_name = _("Shift Definition")
        verbose_name_plural = _("Shift Definitions")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "code"], name="uniq_hr11_shift_code"
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] {self.code} - {self.name}"


class HrShiftVersion(TimeTenantModel):
    """班次版本（总册 §35）。"""

    shift = models.ForeignKey(
        HrShiftDefinition, on_delete=models.PROTECT, related_name="versions"
    )
    version_no = models.PositiveIntegerField(default=1, verbose_name=_("版本号"))
    start_time = models.TimeField(verbose_name=_("开始时间"))
    end_time = models.TimeField(verbose_name=_("结束时间"))
    cross_midnight = models.BooleanField(default=False, verbose_name=_("跨午夜"))
    break_policy_id = models.BigIntegerField(null=True, blank=True)
    minimum_minutes = models.PositiveIntegerField(default=0, verbose_name=_("最小工时（分钟）"))
    standard_minutes = models.PositiveIntegerField(default=480, verbose_name=_("标准工时（分钟）"))
    grace_in_minutes = models.PositiveIntegerField(default=0, verbose_name=_("签到宽限（分钟）"))
    grace_out_minutes = models.PositiveIntegerField(default=0, verbose_name=_("签退宽限（分钟）"))
    earliest_punch_minutes = models.PositiveIntegerField(
        default=0, verbose_name=_("最早打卡（分钟，班前）")
    )
    latest_punch_minutes = models.PositiveIntegerField(
        default=0, verbose_name=_("最晚打卡（分钟，班后）")
    )
    effective_from = models.DateField(verbose_name=_("生效日"))
    effective_to = models.DateField(null=True, blank=True, verbose_name=_("失效日"))
    published_at = models.DateTimeField(null=True, blank=True)
    content_hash = models.CharField(max_length=64, blank=True, editable=False)

    class Meta:
        verbose_name = _("Shift Version")
        verbose_name_plural = _("Shift Versions")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "shift", "version_no"],
                name="uniq_hr11_shiftver_no",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "shift", "effective_from"],
                name="hr11_shiftver_ten_sf",
            ),
        ]

    def save(self, *args, **kwargs):
        # 自动推导跨午夜
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            self.cross_midnight = True
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.shift.code} v{self.version_no} {self.start_time}-{self.end_time}"


class HrWorkPattern(TimeTenantModel):
    """轮班周期（总册 §36）。"""

    code = models.CharField(max_length=64, verbose_name=_("Code"))
    name = models.CharField(max_length=128, verbose_name=_("Name"))
    cycle_length_days = models.PositiveIntegerField(default=7, verbose_name=_("周期天数"))
    pattern_json = models.JSONField(
        default=list, verbose_name=_("周期模板（每日班次 code 或 null=休息）")
    )
    current_version = models.PositiveIntegerField(default=1, verbose_name=_("当前版本"))

    class Meta:
        verbose_name = _("Work Pattern")
        verbose_name_plural = _("Work Patterns")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "code"], name="uniq_hr11_pattern_code"
            ),
        ]

    def clean(self):
        super().clean()
        if not self.pattern_json:
            raise ValidationError(_("pattern_json 不能为空"))
        if len(self.pattern_json) != self.cycle_length_days:
            raise ValidationError(
                _("pattern_json 长度必须等于 cycle_length_days（%(len)s != %(cycle)s）")
                % {"len": len(self.pattern_json), "cycle": self.cycle_length_days}
            )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"[{self.tenant_id}] {self.code} - {self.name}"


class HrScheduleAssignment(TimeTenantModel):
    """
    个人/岗位排班（总册 §37）。

    任意时间点必须能 as-of 查询"当时应按哪套排班"。
    - staff_master_id / assignment_id 引用 HR03（HR11 不复制人员权威）
    - calendar_version_id / shift_version_id / work_pattern_version_id 引用版本
    - 同一时间点不允许重叠的生效排班（约束在 clean/service 层）
    """

    staff_master_id = models.BigIntegerField(verbose_name=_("HR03 人员 id"))
    assignment_id = models.BigIntegerField(
        null=True, blank=True, verbose_name=_("HR03 任职 id")
    )
    calendar_version = models.ForeignKey(
        HrWorkCalendarVersion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    shift_version = models.ForeignKey(
        HrShiftVersion, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    work_pattern = models.ForeignKey(
        HrWorkPattern, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    time_policy_version_id = models.BigIntegerField(
        null=True, blank=True, verbose_name=_("时间政策版本 id")
    )
    effective_from = models.DateField(verbose_name=_("生效日"))
    effective_to = models.DateField(null=True, blank=True, verbose_name=_("失效日"))
    source = models.CharField(max_length=32, default="MANUAL", verbose_name=_("来源"))
    version = models.PositiveIntegerField(default=1, verbose_name=_("版本号"))

    class Meta:
        verbose_name = _("Schedule Assignment")
        verbose_name_plural = _("Schedule Assignments")
        indexes = [
            models.Index(
                fields=["tenant_id", "staff_master_id", "effective_from"],
                name="hr11_sched_ten_staff_from",
            ),
            models.Index(
                fields=["tenant_id", "assignment_id", "effective_from"],
                name="hr11_sched_ten_asg_from",
            ),
        ]

    def clean(self):
        super().clean()
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValidationError(_("失效日早于生效日"))
        if not self.calendar_version_id and not self.shift_version_id and not self.work_pattern_id:
            raise ValidationError(_("排班必须至少绑定日历/班次/轮班之一"))

    def __str__(self):
        return f"[{self.tenant_id}] staff={self.staff_master_id} {self.effective_from}~{self.effective_to}"


class HrScheduleException(TimeTenantModel):
    """排班例外（总册 §38）：不直接改历史排班。"""

    EXCEPTION_TYPES = [
        ("TEMP_SHIFT_CHANGE", _("临时换班")),
        ("AUTHORIZED_TRAINING", _("授权培训")),
        ("ENTERPRISE_PRACTICE", _("企业实践")),
        ("OFFICIAL_DUTY", _("公务/外勤")),
        ("TRAVEL", _("出差")),
        ("SPECIAL_CLOSURE", _("特殊关闭")),
        ("MANUAL_CORRECTION", _("人工更正")),
    ]

    schedule_assignment = models.ForeignKey(
        HrScheduleAssignment, on_delete=models.PROTECT, related_name="exceptions"
    )
    date_from = models.DateField(verbose_name=_("开始日期"))
    date_to = models.DateField(verbose_name=_("结束日期"))
    exception_type = models.CharField(
        max_length=32, choices=EXCEPTION_TYPES, verbose_name=_("例外类型")
    )
    original_schedule_snapshot = models.JSONField(
        default=dict, blank=True, verbose_name=_("原排班快照")
    )
    replacement_schedule_snapshot = models.JSONField(
        default=dict, blank=True, verbose_name=_("替换排班快照")
    )
    reason = models.CharField(max_length=255, verbose_name=_("原因"))
    source_case_id = models.CharField(
        max_length=64, blank=True, default="", verbose_name=_("来源 case id")
    )
    approved_by = models.ForeignKey(
        "horilla_auth.HorillaUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = _("Schedule Exception")
        verbose_name_plural = _("Schedule Exceptions")
        indexes = [
            models.Index(
                fields=["tenant_id", "exception_type", "date_from"],
                name="hr11_schexc_ten_type_from",
            ),
        ]

    def clean(self):
        super().clean()
        if self.date_to < self.date_from:
            raise ValidationError(_("结束日期早于开始日期"))

    def __str__(self):
        return f"[{self.tenant_id}] {self.exception_type} {self.date_from}~{self.date_to}"
