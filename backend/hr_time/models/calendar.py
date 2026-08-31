"""
hr_time/models/calendar.py

S3 工作日历与版本（总册 §29-33、§187）。

- HrWorkCalendar：日历逻辑身份（类型：国家/地方/学校行政/学校教师/轮班/自定义）
- HrWorkCalendarVersion：年度版本（同一年可发新版本，但已结算期间继续引用旧版本）
- HrCalendarDay：日类型（7 种，含 MAKEUP_WORKDAY 调休）

铁律（总册 §32、§199）：
- 调休通知更新 = 新 CalendarVersion，禁止 UPDATE 历史年度；
- 已结算期间保持原版本引用；
- 禁止 `weekday in [Mon..Fri] => working day`（中国调休必须用权威年度日历）。
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from hr_time.enums import CalendarDayType, CalendarType
from hr_time.models.base import TimeTenantModel


class HrWorkCalendar(TimeTenantModel):
    """工作日历逻辑身份。"""

    code = models.CharField(max_length=64, verbose_name=_("Code"))
    name = models.CharField(max_length=128, verbose_name=_("Name"))
    region_code = models.CharField(
        max_length=16, blank=True, default="", verbose_name=_("区域码")
    )
    calendar_type = models.CharField(
        max_length=32, choices=CalendarType.choices, default=CalendarType.SCHOOL_ADMIN
    )
    current_version_id = models.BigIntegerField(
        null=True, blank=True, verbose_name=_("当前版本 id")
    )
    active = models.BooleanField(default=True, verbose_name=_("启用"))

    class Meta:
        verbose_name = _("Work Calendar")
        verbose_name_plural = _("Work Calendars")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "code"], name="uniq_hr11_cal_code"
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] {self.code} - {self.name}"


class HrWorkCalendarVersion(TimeTenantModel):
    """年度日历版本。"""

    calendar = models.ForeignKey(
        HrWorkCalendar, on_delete=models.PROTECT, related_name="versions"
    )
    year = models.PositiveIntegerField(verbose_name=_("年度"))
    version_no = models.PositiveIntegerField(default=1, verbose_name=_("版本号"))
    source_type = models.CharField(
        max_length=32,
        blank=True,
        default="",
        verbose_name=_("来源类型（国务院/校历等）"),
    )
    source_ref = models.CharField(
        max_length=128, blank=True, default="", verbose_name=_("来源引用")
    )
    status = models.CharField(
        max_length=16,
        choices=[
            ("DRAFT", _("草稿")),
            ("PUBLISHED", _("已发布")),
            ("SUPERSEDED", _("已被取代")),
        ],
        default="DRAFT",
    )
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        "horilla_auth.HorillaUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    content_hash = models.CharField(max_length=64, blank=True, editable=False)
    supersedes_version_id = models.BigIntegerField(
        null=True, blank=True, verbose_name=_("取代的版本 id")
    )

    class Meta:
        verbose_name = _("Work Calendar Version")
        verbose_name_plural = _("Work Calendar Versions")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "calendar", "year", "version_no"],
                name="uniq_hr11_calver_year",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "calendar", "year"],
                name="hr11_calver_ten_cal_year",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] {self.calendar.code} {self.year} v{self.version_no} ({self.status})"

    def save(self, *args, **kwargs):
        if self.calendar_id and self.calendar.tenant_id != self.tenant_id:
            raise ValidationError(_("日历版本与日历必须属于同一租户"))
        if self.pk:
            old = HrWorkCalendarVersion._base_manager.filter(pk=self.pk).first()
            if old and old.status in {"PUBLISHED", "SUPERSEDED"}:
                immutable = (
                    "tenant_id", "calendar_id", "year", "version_no", "source_type",
                    "source_ref", "published_at", "published_by_id", "content_hash",
                    "supersedes_version_id",
                )
                if any(getattr(old, field) != getattr(self, field) for field in immutable):
                    raise ValidationError(_("已发布日历版本不可修改；请创建新版本"))
                if not (
                    self.status == old.status
                    or (old.status == "PUBLISHED" and self.status == "SUPERSEDED")
                ):
                    raise ValidationError(_("日历版本状态转换非法"))
        super().save(*args, **kwargs)


class HrCalendarDay(TimeTenantModel):
    """日历日（属于版本；一天在版本内唯一）。"""

    calendar_version = models.ForeignKey(
        HrWorkCalendarVersion, on_delete=models.CASCADE, related_name="days"
    )
    date = models.DateField(verbose_name=_("日期"))
    day_type = models.CharField(
        max_length=32, choices=CalendarDayType.choices, verbose_name=_("日类型")
    )
    statutory_holiday_code = models.CharField(
        max_length=32, null=True, blank=True, verbose_name=_("法定节假日编码")
    )
    is_working_day = models.BooleanField(default=True, verbose_name=_("是否工作日"))
    expected_work_minutes = models.PositiveIntegerField(
        null=True, blank=True, verbose_name=_("期望工时（分钟）")
    )
    makeup_for_date = models.DateField(
        null=True, blank=True, verbose_name=_("调休对应日期")
    )
    note = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        verbose_name = _("Calendar Day")
        verbose_name_plural = _("Calendar Days")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "calendar_version", "date"],
                name="uniq_hr11_calday_date",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "calendar_version", "day_type"],
                name="hr11_calday_ten_ver_type",
            ),
        ]

    def clean(self):
        super().clean()
        # 调休工作日必须关联被调休的日期
        if self.day_type == CalendarDayType.MAKEUP_WORKDAY and not self.makeup_for_date:
            raise ValidationError(_("调休工作日必须填写 makeup_for_date"))
        # 法定节假日编码应与 day_type 一致
        if self.day_type == CalendarDayType.STATUTORY_HOLIDAY and not self.statutory_holiday_code:
            raise ValidationError(_("法定节假日必须填写 statutory_holiday_code"))
        if self.calendar_version_id:
            if self.calendar_version.tenant_id != self.tenant_id:
                raise ValidationError(_("日历日与日历版本必须属于同一租户"))
            if self.calendar_version.status != "DRAFT":
                raise ValidationError(_("已发布日历版本的日历日不可修改"))

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.calendar_version.status != "DRAFT":
            raise ValidationError(_("已发布日历版本的日历日不可删除"))
        super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.calendar_version.calendar.code} {self.date} {self.get_day_type_display()}"
