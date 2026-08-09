"""
hr10_development/models/session.py

培训 Session（总册 §46）。
多 session 组成一个 offering；总学时从 session 规则计算。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr10_development.constants import DeliveryMode
from hr10_development.models.base import DevelopmentTenantModel


class HrLearningSession(DevelopmentTenantModel):
    """培训课程节。"""

    offering_id = models.BigIntegerField(
        db_index=True,
        verbose_name=_("班次 ID"),
    )

    sequence = models.IntegerField(
        default=1,
        verbose_name=_("序号"),
    )

    start_at = models.DateTimeField(
        verbose_name=_("开始时间"),
    )

    end_at = models.DateTimeField(
        verbose_name=_("结束时间"),
    )

    venue = models.CharField(
        max_length=256,
        blank=True,
        default="",
        verbose_name=_("地点"),
    )

    delivery_mode = models.CharField(
        max_length=48,
        choices=DeliveryMode.choices,
        verbose_name=_("交付方式"),
    )

    attendance_required = models.BooleanField(
        default=True,
        verbose_name=_("需要签到"),
    )

    instructor_refs = models.JSONField(
        blank=True,
        default=list,
        verbose_name=_("讲师引用"),
    )

    content_ref = models.CharField(
        max_length=256,
        blank=True,
        default="",
        verbose_name=_("内容引用"),
    )

    class Meta:
        db_table = "hr_learning_session"
        verbose_name = _("培训课程节")
        verbose_name_plural = verbose_name
        ordering = ["offering_id", "sequence"]

    def __str__(self):
        return f"Session {self.sequence} of offering {self.offering_id}"
