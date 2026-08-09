"""
hr_onboarding/models/authority.py

HR05 Authority 切换状态（05 §44 / 00 §56）：
- 三态：LEGACY_ONBOARDING_ONLY → DUAL_READ_COMPARE → HR05_AUTHORITY；
- tenant 级切换（禁止全局一锅端，00 §64）；
- 每次切换记录 operator/old_mode/new_mode/reason/reconcile_report_id；
- 进入 HR05_AUTHORITY 后禁止自动 fallback legacy（00 §57）。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class HrOnboardingAuthorityMode(models.Model):
    class Mode(models.TextChoices):
        LEGACY_ONBOARDING_ONLY = "LEGACY_ONBOARDING_ONLY", _("Legacy Onboarding Only")
        DUAL_READ_COMPARE = "DUAL_READ_COMPARE", _("Dual Read Compare")
        HR05_AUTHORITY = "HR05_AUTHORITY", _("HR05 Authority")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(unique=True, db_index=True)
    mode = models.CharField(
        max_length=32, choices=Mode.choices, default=Mode.LEGACY_ONBOARDING_ONLY
    )
    switched_by = models.BigIntegerField(null=True, blank=True)
    old_mode = models.CharField(max_length=32, blank=True, default="")
    new_mode = models.CharField(max_length=32, blank=True, default="")
    reason = models.TextField(blank=True, default="")
    reconcile_report_id = models.CharField(max_length=64, blank=True, default="")
    switched_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Onboarding Authority Mode")
        verbose_name_plural = _("HR Onboarding Authority Modes")

    def __str__(self):
        return f"tenant={self.tenant_id}:{self.mode}"
