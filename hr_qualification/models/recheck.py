"""
hr_qualification/models/recheck.py —— HrDoubleTeacherRecheckCase（总册 §87-90）。

复核案例。
- 触发类型：定时复核/证书失效/证书撤销/师德审查/数据更正/政策要求/投诉/审计
- 复核决策：保留/升级/降级/挂起/撤销/到期/需进一步审查
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_qualification.constants import RecheckDecision, RecheckTrigger


class HrDoubleTeacherRecheckCase(models.Model):
    """双师复核案例。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recognition_id = models.ForeignKey(
        "hr_qualification.HrDoubleTeacherRecognition",
        on_delete=models.PROTECT,
        related_name="recheck_cases",
    )
    trigger = models.CharField(max_length=32, choices=RecheckTrigger.choices)
    due_at = models.DateField(null=True, blank=True)
    rule_version = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(max_length=24, default="OPEN")
    evidence_snapshot = models.JSONField(null=True, blank=True)
    decision = models.CharField(
        max_length=32,
        choices=RecheckDecision.choices,
        null=True,
        blank=True,
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.BigIntegerField(null=True, blank=True)
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Double Teacher Recheck Case")
        verbose_name_plural = _("HR Double Teacher Recheck Cases")
        indexes = [
            models.Index(fields=["recognition_id", "status"]),
        ]

    def __str__(self) -> str:
        return f"Recheck[{self.trigger}] → {self.decision or 'PENDING'}"
