"""
hr_external/models/portal.py —— 外聘本人门户 token（B6，总册 §90/§134/00 §134）。

- 本人门户（External Teacher Portal）只允许本人数据：profile 必要部分/engagement/task/
  协议可见版本/workload/通知（§90）；
- 公开入口用 token 解析学校，禁止客户端传 tenant_id（00 §134）；
- token SHA-256 存储，明文只签发一次（对齐 HR05 token_service 模式）。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class PortalTokenStatus(models.TextChoices):
    ACTIVE = "ACTIVE", _("Active")
    EXPIRED = "EXPIRED", _("Expired")
    REVOKED = "REVOKED", _("Revoked")


class HrExternalPortalToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    external_profile_id = models.ForeignKey(
        "hr_external.HrExternalTeacherProfile",
        on_delete=models.PROTECT,
        related_name="portal_tokens",
    )
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    status = models.CharField(
        max_length=16,
        choices=PortalTokenStatus.choices,
        default=PortalTokenStatus.ACTIVE,
    )
    expires_at = models.DateTimeField()
    issued_by = models.BigIntegerField(null=True, blank=True)
    issued_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("HR External Portal Token")
        verbose_name_plural = _("HR External Portal Tokens")
        indexes = [
            models.Index(
                fields=["tenant_id", "external_profile_id", "status"],
                name="hex_portal_token_profile_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] portal token {self.status}"
