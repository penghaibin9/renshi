"""
hr_qualification/models/batch.py —— HrDoubleTeacherRecognitionBatch（总册 §52-53）。

双师认定批次。
- 绑定一个 frozen RulePackVersion
- 状态机 DRAFT→PUBLISHED→APPLICATION_OPEN→CLOSED→REVIEWING→RESULT_PUBLISHED→CLOSED
- eligible_scope 定义哪些人员可申报
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_qualification.constants import BatchStatus, RecognitionLevel


class HrDoubleTeacherRecognitionBatch(models.Model):
    """双师型教师认定批次。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    batch_no = models.CharField(max_length=64)
    name = models.CharField(max_length=200)
    school_year = models.CharField(max_length=16, blank=True, default="")  # 如 "2026-2027"
    application_start = models.DateField(null=True, blank=True)
    application_end = models.DateField(null=True, blank=True)
    rule_pack_version_id = models.ForeignKey(
        "hr_qualification.HrDoubleTeacherRulePackVersion",
        on_delete=models.PROTECT,
        related_name="batches",
    )
    eligible_scope = models.JSONField(null=True, blank=True)  # 申报范围
    target_levels = models.JSONField(null=True, blank=True)   # 可选层级
    status = models.CharField(
        max_length=24, choices=BatchStatus.choices, default=BatchStatus.DRAFT, db_index=True
    )
    panel_policy_version = models.CharField(max_length=64, blank=True, default="")
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Double Teacher Recognition Batch")
        verbose_name_plural = _("HR Double Teacher Recognition Batches")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "batch_no"],
                name="uniq_batch_tenant_no",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "status"]),
        ]

    def __str__(self) -> str:
        return f"Batch {self.batch_no}: {self.name} [{self.status}]"
