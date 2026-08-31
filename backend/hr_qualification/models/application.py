"""
hr_qualification/models/application.py —— HrDoubleTeacherApplication（总册 §54-55）。

双师申报申请。
- 状态机 DRAFT→SUBMITTED→FORMAL_REVIEW→...→RECOGNIZED / NOT_RECOGNIZED
- 支持 NORMAL / EXCEPTION 两种申报路线
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_qualification.constants import ApplicationRoute, ApplicationStatus, RecognitionLevel


class HrDoubleTeacherApplication(models.Model):
    """双师型教师认定申请。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    application_no = models.CharField(max_length=64)
    batch_id = models.ForeignKey(
        "hr_qualification.HrDoubleTeacherRecognitionBatch",
        on_delete=models.PROTECT,
        related_name="applications",
    )
    person_id = models.ForeignKey(
        "hr_staff.HrPerson",
        on_delete=models.PROTECT,
        related_name="double_teacher_applications",
    )
    staff_master_id = models.ForeignKey(
        "hr_staff.HrStaffMaster",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="double_teacher_applications",
    )
    external_engagement_id = models.BigIntegerField(null=True, blank=True)
    target_level = models.CharField(max_length=32, choices=RecognitionLevel.choices)
    current_recognition_id = models.UUIDField(null=True, blank=True)  # 当前已有认定
    route = models.CharField(
        max_length=16,
        choices=ApplicationRoute.choices,
        default=ApplicationRoute.NORMAL,
    )
    status = models.CharField(
        max_length=24, choices=ApplicationStatus.choices, default=ApplicationStatus.DRAFT, db_index=True
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    applicant_statement = models.TextField(blank=True, default="")
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Double Teacher Application")
        verbose_name_plural = _("HR Double Teacher Applications")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "application_no"],
                name="uniq_app_tenant_no",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "batch_id", "status"]),
            models.Index(fields=["tenant_id", "target_level", "status"]),
        ]

    def __str__(self) -> str:
        return f"App {self.application_no} [{self.target_level}] {self.status}"
