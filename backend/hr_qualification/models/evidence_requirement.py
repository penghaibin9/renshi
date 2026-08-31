"""
hr_qualification/models/evidence_requirement.py —— HrDoubleTeacherEvidenceRequirement（总册 §39）。

双师规则中的证据要求。
- 每个 Rule 可以有若干证据要求
- 定义证据类别、数量、时长、等级、来源域、是否需要文档、是否需要核验
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class HrDoubleTeacherEvidenceRequirement(models.Model):
    """双师证据要求。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rule_id = models.ForeignKey(
        "hr_qualification.HrDoubleTeacherRule",
        on_delete=models.CASCADE,
        related_name="evidence_requirements",
    )
    evidence_category = models.CharField(max_length=64)  # 证据类别码
    min_count = models.PositiveIntegerField(default=1)    # 最少数量
    min_duration = models.PositiveIntegerField(null=True, blank=True)  # 最少时长（天）
    min_level = models.CharField(max_length=64, blank=True, default="")  # 最低等级
    # 允许的证据来源域
    allowed_source_domains = models.JSONField(null=True, blank=True)
    document_required = models.BooleanField(default=False)
    verification_required = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Double Teacher Evidence Requirement")
        verbose_name_plural = _("HR Double Teacher Evidence Requirements")
        indexes = [
            models.Index(fields=["rule_id"]),
        ]

    def __str__(self) -> str:
        return f"EvidenceReq({self.evidence_category}) × {self.min_count}"
