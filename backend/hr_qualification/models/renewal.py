"""
hr_qualification/models/renewal.py —— HrCredentialRenewal（总册 §28）。

证书续期代际链。
- 续证不是修改 valid_to，而是新建 HrPersonCredential
- 保留 original → new 外键链
- renewal_type：同等级续 / 升级 / 更正
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_qualification.constants import RenewalType


class HrCredentialRenewal(models.Model):
    """证书续期（代际链）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    original_credential_id = models.ForeignKey(
        "hr_qualification.HrPersonCredential",
        on_delete=models.PROTECT,
        related_name="renewals_as_original",
    )
    new_credential_id = models.ForeignKey(
        "hr_qualification.HrPersonCredential",
        on_delete=models.PROTECT,
        related_name="renewals_as_new",
        null=True,
        blank=True,
    )
    renewal_type = models.CharField(
        max_length=24, choices=RenewalType.choices, default=RenewalType.SAME_LEVEL
    )
    reason = models.TextField(blank=True, default="")
    submitted_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("HR Credential Renewal")
        verbose_name_plural = _("HR Credential Renewals")
        indexes = [
            models.Index(fields=["original_credential_id"]),
        ]

    def __str__(self) -> str:
        return f"Renewal[{self.renewal_type}] #{self.original_credential_id_id}"
