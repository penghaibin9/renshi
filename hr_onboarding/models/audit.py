"""
hr_onboarding/models/audit.py

HR05 正式业务审计（替代 HorillaAuditLog 作正式审计；00 §35）。
- 业务管理员不能 CRUD 删除；Legal Hold 高于 purge；
- 高敏 payload 禁止进日志。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class HrOnboardingAuditEvent(models.Model):
    """HR05 业务审计事件。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    case_id = models.UUIDField(null=True, blank=True, db_index=True)
    actor_user_id = models.BigIntegerField(null=True, blank=True)
    action = models.CharField(max_length=64)
    business_type = models.CharField(max_length=32, blank=True, default="")
    business_id = models.CharField(max_length=128, blank=True, default="")
    before_snapshot_ref = models.CharField(max_length=128, blank=True, default="")
    after_snapshot_ref = models.CharField(max_length=128, blank=True, default="")
    reason = models.TextField(blank=True, default="")
    request_id = models.CharField(max_length=64, blank=True, default="")
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Onboarding Audit Event")
        verbose_name_plural = _("HR Onboarding Audit Events")
        indexes = [
            models.Index(fields=["tenant_id", "case_id", "occurred_at"]),
            models.Index(fields=["tenant_id", "action"]),
        ]
        ordering = ["-occurred_at"]

    def __str__(self):
        return f"{self.action}:{self.business_id}"
