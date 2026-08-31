"""
hr_staff/models/identity.py —— HrPersonIdentityDocument 身份证明（HIGH_SENSITIVE，总册 §8.3）。

要求：
- document_number 明文加密存储（document_number_ciphertext）；
- 检索去重使用 tenant-aware fingerprint（document_number_fingerprint）；
- API 默认只返回 masked_display；
- 明文查看必须独立 permission + purpose + audit；
- 日志禁止打印明文。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_staff.constants import DocumentIdentityType, VerificationStatus


class HrPersonIdentityDocument(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    person_id = models.ForeignKey(
        "hr_staff.HrPerson", on_delete=models.PROTECT, related_name="identity_documents"
    )
    document_type = models.CharField(
        max_length=24, choices=DocumentIdentityType.choices, default=DocumentIdentityType.NATIONAL_ID
    )
    document_number_ciphertext = models.TextField(blank=True, default="")
    document_number_fingerprint = models.CharField(max_length=64, db_index=True, blank=True, default="")
    masked_display = models.CharField(max_length=64, blank=True, default="")
    issuing_country = models.CharField(max_length=8, blank=True, default="CN")
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    verification_status = models.CharField(
        max_length=16,
        choices=VerificationStatus.choices,
        default=VerificationStatus.UNVERIFIED,
    )
    verified_by = models.BigIntegerField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Person Identity Document")
        verbose_name_plural = _("HR Person Identity Documents")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "document_number_fingerprint"],
                condition=models.Q(document_number_fingerprint__isnull=False)
                & ~models.Q(document_number_fingerprint=""),
                name="uniq_hr_identity_fingerprint_tenant",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "person_id", "document_type"]),
        ]

    def __str__(self):
        return f"{self.document_type}: {self.masked_display}"
