"""
hr10_development/models/practice_attendance.py

企业实践出勤事实模型（总册 §89）。

独立于 Activity 模型：出勤是每天的时间事实，活动是任务内容。
4 source types + trust_level + anomaly flags。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr10_development.models.base import DevelopmentTenantModel


class HrEnterprisePracticeAttendanceFact(DevelopmentTenantModel):
    """
    企业实践出勤事实。

    与 HrEnterprisePracticeActivity 分离：
    - Activity = 任务内容（做了什么）
    - AttendanceFact = 时间事实（哪天到岗多久）

    来源信任等级：
      ENTERPRISE_SYSTEM > MENTOR > SCHOOL_CHECK > SELF_WITH_EVIDENCE > IMPORT
    """

    assignment_id = models.BigIntegerField(
        db_index=True,
        verbose_name=_("派出 ID"),
    )

    date = models.DateField(
        verbose_name=_("日期"),
    )

    start_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("开始时间"),
    )

    end_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("结束时间"),
    )

    duration_minutes = models.IntegerField(
        null=True,
        blank=True,
        verbose_name=_("时长(分钟)"),
    )

    source = models.CharField(
        max_length=32,
        choices=[
            ("ENTERPRISE_SYSTEM", _("企业系统")),
            ("MENTOR", _("企业导师")),
            ("SCHOOL_CHECK", _("学校检查")),
            ("SELF_WITH_EVIDENCE", _("教师自报+证据")),
            ("IMPORT", _("导入")),
        ],
        verbose_name=_("来源"),
    )

    source_ref = models.CharField(
        max_length=256,
        blank=True,
        default="",
        verbose_name=_("来源引用"),
    )

    trust_level = models.IntegerField(
        default=1,
        verbose_name=_("信任等级 1-5"),
        help_text="5=Authority核验, 4=Provider核验, 3=文档核验, 2=人工核验, 1=教师自报",
    )

    verification_status = models.CharField(
        max_length=48,
        default="SELF_REPORTED",
        db_index=True,
        verbose_name=_("核验状态"),
    )

    anomaly_flags_json = models.JSONField(
        blank=True,
        default=dict,
        verbose_name=_("异常标记"),
    )

    verified_by = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name=_("核验人"),
    )

    verified_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("核验时间"),
    )

    class Meta:
        db_table = "hr_practice_attendance_fact"
        verbose_name = _("企业实践出勤事实")
        verbose_name_plural = verbose_name
        unique_together = [
            ("assignment_id", "date", "source"),
        ]
        indexes = [
            models.Index(fields=["assignment_id", "date"]),
            models.Index(fields=["trust_level"]),
            models.Index(fields=["verification_status"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(duration_minutes__gte=0),
                name="attendance_duration_non_negative",
            ),
        ]

    def __str__(self):
        return f"Attendance(assign={self.assignment_id} date={self.date} mins={self.duration_minutes})"
