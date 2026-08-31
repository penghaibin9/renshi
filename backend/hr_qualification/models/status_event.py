"""
hr_qualification/models/status_event.py —— HrCredentialStatusEvent（总册 §133）。

证书状态变更历史链。
- from_status → to_status
- reason + actor + evidence（可链接）
- 不可删除，只能追加
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class HrCredentialStatusEvent(models.Model):
    """证书状态变更记录。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    credential_id = models.ForeignKey(
        "hr_qualification.HrPersonCredential",
        on_delete=models.PROTECT,
        related_name="status_events",
    )
    from_status = models.CharField(max_length=24, blank=True, default="")
    to_status = models.CharField(max_length=24)
    reason = models.TextField(blank=True, default="")
    actor_id = models.BigIntegerField(null=True, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)
    evidence_event_id = models.UUIDField(null=True, blank=True)

    class Meta:
        verbose_name = _("HR Credential Status Event")
        verbose_name_plural = _("HR Credential Status Events")
        ordering = ["occurred_at"]
        indexes = [
            models.Index(fields=["credential_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.from_status} → {self.to_status} at {self.occurred_at}"
