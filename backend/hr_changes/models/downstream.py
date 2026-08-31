"""
hr_changes/models/downstream.py —— HrChangeDownstreamEffect 下游同步（总册 §49/§50）。

人事事实生效后下游失败不回滚（Change=EFFECTIVE + Downstream=PARTIAL_FAILED）；
自动重试 + 人工修复；本表记录每次效果状态。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_changes.constants import DownstreamEffectStatus


class HrChangeDownstreamEffect(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    change_case_id = models.ForeignKey(
        "hr_changes.HrPersonnelChangeCase",
        on_delete=models.CASCADE,
        related_name="downstream_effects",
    )
    tenant_id = models.BigIntegerField(db_index=True)
    target_domain = models.CharField(max_length=32, db_index=True)  # HR02/HR03/HR07/HR11/HR14/HR15/IAM/ACADEMIC/FINANCE
    effect_type = models.CharField(max_length=64)  # PersonnelChangeEffective/ContractReviewRequired/...
    status = models.CharField(
        max_length=24,
        choices=DownstreamEffectStatus.choices,
        default=DownstreamEffectStatus.PENDING,
        db_index=True,
    )
    blocking_level = models.CharField(max_length=16, blank=True, default="")  # BLOCKER/WARNING/INFO
    external_ref = models.CharField(max_length=128, blank=True, default="")
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    last_tried_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Change Downstream Effect")
        verbose_name_plural = _("HR Change Downstream Effects")
        constraints = [
            models.UniqueConstraint(
                fields=["change_case_id", "target_domain", "effect_type"],
                name="uniq_hr_change_downstream_case_domain_type",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "status", "last_tried_at"]),
        ]

    def __str__(self):
        return f"{self.change_case_id.case_no} {self.target_domain}:{self.status}"
