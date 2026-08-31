"""
hr_qualification/models/objection.py —— HrDoubleTeacherObjection（总册 §81）。

公示异议处理。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_qualification.constants import ObjectionStatus


class HrDoubleTeacherObjection(models.Model):
    """双师公示异议。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application_id = models.ForeignKey(
        "hr_qualification.HrDoubleTeacherApplication",
        on_delete=models.PROTECT,
        related_name="objections",
    )
    submitted_by = models.CharField(max_length=200, blank=True, default="")
    content = models.TextField()
    status = models.CharField(
        max_length=24,
        choices=ObjectionStatus.choices,
        default=ObjectionStatus.RECEIVED,
    )
    resolution = models.TextField(blank=True, default="")
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Double Teacher Objection")
        verbose_name_plural = _("HR Double Teacher Objections")
        indexes = [
            models.Index(fields=["application_id"]),
        ]

    def __str__(self) -> str:
        return f"Objection App#{self.application_id_id} [{self.status}]"
