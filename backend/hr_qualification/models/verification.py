"""
hr_qualification/models/verification.py —— HrCredentialVerification（总册 §22-24）。

核验历史（多记录审计链）。
- 一个 Credential 可以有多次核验记录
- 核验类型：人工原件核验/官方数据库/第三方/发证机构确认/导入信任源/迁移核验
- 核验结果：VERIFIED/NOT_FOUND/MISMATCH/EXPIRED/REVOKED/NEEDS_MANUAL_REVIEW/PROVIDER_UNAVAILABLE
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_qualification.constants import VerificationResult, VerificationType


class HrCredentialVerification(models.Model):
    """证书核验记录。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    credential_id = models.ForeignKey(
        "hr_qualification.HrPersonCredential",
        on_delete=models.PROTECT,
        related_name="verifications",
    )
    verification_type = models.CharField(
        max_length=32,
        choices=VerificationType.choices,
        default=VerificationType.MANUAL_ORIGINAL_REVIEW,
    )
    # 核验渠道/提供者标识
    provider = models.CharField(max_length=100, blank=True, default="")
    provider_reference = models.CharField(max_length=200, blank=True, default="")
    result = models.CharField(
        max_length=32,
        choices=VerificationResult.choices,
        default=VerificationResult.PENDING,
    )
    verified_by = models.BigIntegerField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    verification_valid_until = models.DateTimeField(null=True, blank=True)
    # 核验原始结果文档（可选）
    raw_result_document_id = models.UUIDField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Credential Verification")
        verbose_name_plural = _("HR Credential Verifications")
        indexes = [
            models.Index(fields=["credential_id"]),
            models.Index(fields=["result"]),
        ]

    def __str__(self) -> str:
        return f"Verification [{self.verification_type}] → {self.result}"
