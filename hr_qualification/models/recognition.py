"""
hr_qualification/models/recognition.py —— HrDoubleTeacherRecognition（总册 §84-86）。

双师型认定结果。
- 一人可有多条历史记录（初/中/高级晋升轨迹）
- 升级时旧记录 SUPERSEDED，新记录 ACTIVE
- 状态机 PENDING_EFFECTIVE→ACTIVE→REVIEW_DUE→...→SUPERSEDED/REVOKED
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_qualification.constants import RecognitionLevel, RecognitionStatus


class HrDoubleTeacherRecognition(models.Model):
    """双师型教师认定结果。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    person_id = models.ForeignKey(
        "hr_staff.HrPerson",
        on_delete=models.PROTECT,
        related_name="double_teacher_recognitions",
    )
    staff_master_id = models.ForeignKey(
        "hr_staff.HrStaffMaster",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="double_teacher_recognitions",
    )
    external_engagement_id = models.BigIntegerField(null=True, blank=True)
    recognition_no = models.CharField(max_length=64)
    level = models.CharField(max_length=32, choices=RecognitionLevel.choices)
    rule_pack_version_id = models.ForeignKey(
        "hr_qualification.HrDoubleTeacherRulePackVersion",
        on_delete=models.PROTECT,
        related_name="recognitions",
    )
    batch_id = models.ForeignKey(
        "hr_qualification.HrDoubleTeacherRecognitionBatch",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="recognitions",
    )
    application_id = models.ForeignKey(
        "hr_qualification.HrDoubleTeacherApplication",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="recognitions",
    )
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    review_due_at = models.DateField(null=True, blank=True)  # 下次复核日
    status = models.CharField(
        max_length=24, choices=RecognitionStatus.choices, default=RecognitionStatus.PENDING_EFFECTIVE,
        db_index=True,
    )
    recognition_authority = models.CharField(max_length=200, blank=True, default="")
    result_document_id = models.UUIDField(null=True, blank=True)
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Double Teacher Recognition")
        verbose_name_plural = _("HR Double Teacher Recognitions")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "recognition_no"],
                name="uniq_recognition_tenant_no",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "person_id", "level"]),
            models.Index(fields=["tenant_id", "status"]),
            models.Index(fields=["person_id", "effective_from", "effective_to"]),
        ]

    def __str__(self) -> str:
        return f"Recognition {self.recognition_no} [{self.level}] {self.status}"
