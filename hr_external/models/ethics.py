"""
hr_external/models/ethics.py —— HrExternalEthicsReview 师德/伦理审查（S2，总册 §36）。

- 状态：PENDING / PASS / NEEDS_REVIEW / FAIL / EXPIRED。
- 系统只提供合规流程，不自行推断政治倾向或敏感属性（§36 明确红线）。
- 具体政治/师德审查内容按学校制度配置。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_external.constants import EthicsReviewStatus


class HrExternalEthicsReview(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    person_id = models.ForeignKey(
        "hr_staff.HrPerson",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="external_ethics_reviews",
    )
    case_id = models.ForeignKey(
        "hr_external.HrExternalHiringCase",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ethics_reviews",
    )
    review_type = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=EthicsReviewStatus.choices,
        default=EthicsReviewStatus.PENDING,
    )
    reviewer = models.BigIntegerField(null=True, blank=True)
    evidence = models.CharField(max_length=512, blank=True, default="")
    conclusion = models.TextField(blank=True, default="")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR External Ethics Review")
        verbose_name_plural = _("HR External Ethics Reviews")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="hr_external_ethics_version_gte_1",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "person_id"],
                name="hr_external_ethics_person_idx",
            ),
            models.Index(
                fields=["tenant_id", "case_id", "status"],
                name="hr_external_ethics_case_status_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] ethics {self.status}"
