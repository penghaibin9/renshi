"""
hr_qualification/models/requirement.py —— HrCredentialRequirement（总册 §29-30）。

资格需求定义：某岗位/认定级别需要什么资格。
- 与 PersonCredential 分离（资格持有 ≠ 资格需求）
- Person vs Requirement 对比服务在 services/requirement_service.py
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_qualification.constants import CredentialCategory, HardOrSoft, RequirementTargetType


class HrCredentialRequirement(models.Model):
    """资格需求定义。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    target_type = models.CharField(
        max_length=32, choices=RequirementTargetType.choices, default=RequirementTargetType.OTHER_TARGET
    )
    target_ref = models.CharField(max_length=200, blank=True, default="")  # 目标引用
    credential_category = models.CharField(
        max_length=32, choices=CredentialCategory.choices, blank=True, default=""
    )
    catalog_item_id = models.ForeignKey(
        "hr_qualification.HrCredentialCatalogItem",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="requirements",
    )
    minimum_level = models.CharField(max_length=64, blank=True, default="")
    verification_required = models.BooleanField(default=False)
    valid_on_date_required = models.BooleanField(default=False)
    hard_or_soft = models.CharField(
        max_length=8,
        choices=HardOrSoft.choices,
        default=HardOrSoft.HARD,
    )
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Credential Requirement")
        verbose_name_plural = _("HR Credential Requirements")
        indexes = [
            models.Index(fields=["tenant_id", "target_type"]),
            models.Index(fields=["tenant_id", "credential_category"]),
        ]

    def __str__(self) -> str:
        return f"Req[{self.target_type}] → {self.credential_category}"
