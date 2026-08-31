"""
hr10_development/models/enrollment.py

培训报名（总册 §52）。
同一 staff 对同一 offering 最多一个 active enrollment。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr10_development.constants import EnrollmentStatus, SeatStatus
from hr10_development.models.base import DevelopmentTenantModel


class HrLearningEnrollment(DevelopmentTenantModel):
    """培训报名记录。"""

    offering_id = models.BigIntegerField(
        db_index=True,
        verbose_name=_("班次 ID"),
    )

    staff_master_id = models.BigIntegerField(
        db_index=True,
        verbose_name=_("教职工 ID"),
    )

    request_id = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name=_("申请 ID"),
    )

    enrollment_source = models.CharField(
        max_length=32,
        default="MANUAL",
        verbose_name=_("报名来源"),
    )

    enrollment_status = models.CharField(
        max_length=32,
        choices=EnrollmentStatus.choices,
        default=EnrollmentStatus.PENDING,
        db_index=True,
        verbose_name=_("报名状态"),
    )

    seat_status = models.CharField(
        max_length=16,
        choices=SeatStatus.choices,
        blank=True,
        default="",
        verbose_name=_("名额状态"),
    )

    assigned_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("分配时间"),
    )

    due_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("截止时间"),
    )

    started_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("开始时间"),
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("完成时间"),
    )

    version = models.IntegerField(
        default=1,
        verbose_name=_("乐观锁版本"),
    )

    class Meta:
        db_table = "hr_learning_enrollment"
        verbose_name = _("培训报名")
        verbose_name_plural = verbose_name
        unique_together = [
            ("offering_id", "staff_master_id"),
        ]
        indexes = [
            models.Index(fields=["offering_id", "enrollment_status"]),
            models.Index(fields=["staff_master_id", "enrollment_status"]),
        ]
