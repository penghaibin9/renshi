"""
hr10_development/models/duration_ledger.py

实践时长台账模型（总册 §107）。

从 verified activity segments + verified attendance segments
→ dedup + 排除重叠 → eligible practice duration → ledger entry。

培训学时 / 企业实践小时 / 企业实践天数 分账，不混成一个 total。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr10_development.models.base import DevelopmentTenantModel


class HrDurationLedger(DevelopmentTenantModel):
    """
    实践时长台账。

    每条记录 = 一个已核验的时长片段，带原始单位与换算规则版本。
    最终 eligible duration 由 duration_service 聚合计算。
    """

    assignment_id = models.BigIntegerField(
        db_index=True,
        verbose_name=_("派出 ID"),
    )

    source_type = models.CharField(
        max_length=32,
        choices=[
            ("ACTIVITY", _("活动")),
            ("ATTENDANCE", _("出勤")),
            ("MENTOR_CONFIRMED", _("导师确认")),
            ("MANUAL_ADJUST", _("人工调整")),
        ],
        verbose_name=_("来源类型"),
    )

    source_id = models.BigIntegerField(
        verbose_name=_("来源记录 ID"),
    )

    raw_hours = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        verbose_name=_("原始小时数"),
    )

    raw_days = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        default=0,
        verbose_name=_("原始天数"),
    )

    eligible_hours = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=0,
        verbose_name=_("有效小时数"),
    )

    eligible_days = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        default=0,
        verbose_name=_("有效天数"),
    )

    conversion_rule_version = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name=_("换算规则版本"),
    )

    excluded_reason = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name=_("排除原因"),
    )

    calculated_at = models.DateTimeField(
        verbose_name=_("计算时间"),
    )

    class Meta:
        db_table = "hr_duration_ledger"
        verbose_name = _("时长台账")
        verbose_name_plural = verbose_name
        unique_together = [
            ("assignment_id", "source_type", "source_id"),
        ]
        indexes = [
            models.Index(fields=["assignment_id"]),
            models.Index(fields=["source_type"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(raw_hours__gte=0),
                name="duration_raw_hours_non_negative",
            ),
        ]

    def __str__(self):
        return f"Duration(assign={self.assignment_id} {self.source_type}={self.eligible_hours}h)"
