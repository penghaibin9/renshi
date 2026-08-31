"""
hr_qualification/models/risk.py —— HrQualificationRiskCase（总册 §92-93）。

资格风险案例。
- 可以指向 PersonCredential 或 DoubleTeacherRecognition
- 风险类型、严重度、责任人、到期日、状态闭环
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_qualification.constants import RiskSeverity, RiskStatus, RiskType


class HrQualificationRiskCase(models.Model):
    """资格/双师风险案例。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    person_id = models.ForeignKey(
        "hr_staff.HrPerson",
        on_delete=models.PROTECT,
        related_name="qualification_risks",
    )
    credential_id = models.UUIDField(null=True, blank=True, db_index=True)
    recognition_id = models.UUIDField(null=True, blank=True, db_index=True)
    risk_type = models.CharField(max_length=48, choices=RiskType.choices)
    severity = models.CharField(
        max_length=16, choices=RiskSeverity.choices, default=RiskSeverity.MEDIUM
    )
    opened_at = models.DateTimeField(auto_now_add=True)
    owner = models.CharField(max_length=200, blank=True, default="")
    due_at = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=24, choices=RiskStatus.choices, default=RiskStatus.OPEN, db_index=True
    )
    resolution = models.TextField(blank=True, default="")
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.BigIntegerField(null=True, blank=True)
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Qualification Risk Case")
        verbose_name_plural = _("HR Qualification Risk Cases")
        indexes = [
            models.Index(fields=["tenant_id", "risk_type", "severity", "status"]),
            models.Index(fields=["credential_id"]),
            models.Index(fields=["recognition_id"]),
        ]

    def __str__(self) -> str:
        return f"Risk[{self.risk_type}] {self.severity} [{self.status}]"
