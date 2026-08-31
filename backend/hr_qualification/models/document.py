"""
hr_qualification/models/document.py —— HrCredentialDocument（总册 §26-27）。

证书相关附件/文档。
- sensitivity 分级，配合文件安全管控
- checksum（SHA-256），防止文件篡改
- version_no 支持文件多版本
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_qualification.constants import CredentialDocumentType


class HrCredentialDocument(models.Model):
    """证书附件。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    credential_id = models.ForeignKey(
        "hr_qualification.HrPersonCredential",
        on_delete=models.PROTECT,
        related_name="documents",
    )
    document_type = models.CharField(
        max_length=32,
        choices=CredentialDocumentType.choices,
        default=CredentialDocumentType.CERTIFICATE_SCAN,
    )
    # 文件存储引用（对接 horilla_documents 或对象存储）
    file_id = models.CharField(max_length=200)
    version_no = models.PositiveIntegerField(default=1)
    checksum = models.CharField(max_length=128, blank=True, default="")  # SHA-256
    source = models.CharField(max_length=64, blank=True, default="")
    verified = models.BooleanField(default=False)
    sensitivity = models.CharField(
        max_length=32, blank=True, default="RESTRICTED_HR"
    )  # PUBLIC_HR / RESTRICTED_HR / SENSITIVE
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Credential Document")
        verbose_name_plural = _("HR Credential Documents")
        indexes = [
            models.Index(fields=["credential_id"]),
        ]

    def __str__(self) -> str:
        return f"Doc[{self.document_type}] v{self.version_no}"
