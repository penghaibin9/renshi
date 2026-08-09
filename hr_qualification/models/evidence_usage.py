"""
hr_qualification/models/evidence_usage.py —— HrEvidenceUsage（总册 §131）。

证据反向引用图。
- 用于：证据失效时 → 遍历受影响 Application/Recognition → 开 RecheckCase
- 全库 JSON 扫描效率低 → 建索引表
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class HrEvidenceUsage(models.Model):
    """证据引用追踪。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    evidence_type = models.CharField(max_length=64)
    evidence_ref = models.CharField(max_length=200)  # source_domain + source_object_id
    application_id = models.ForeignKey(
        "hr_qualification.HrDoubleTeacherApplication",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="evidence_usages",
    )
    rule_id = models.ForeignKey(
        "hr_qualification.HrDoubleTeacherRule",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="evidence_usages",
    )
    recognition_id = models.ForeignKey(
        "hr_qualification.HrDoubleTeacherRecognition",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="evidence_usages",
    )
    snapshot_hash = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Evidence Usage")
        verbose_name_plural = _("HR Evidence Usages")
        indexes = [
            models.Index(fields=["evidence_type", "evidence_ref"]),
            models.Index(fields=["application_id"]),
            models.Index(fields=["recognition_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.evidence_type}:{self.evidence_ref}"
