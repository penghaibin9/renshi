"""
hr_changes/models/authority.py —— HrChangeAuthorityMode（S12，00 §56）。

Authority 切换阶段：LEGACY_ACTIVE → DUAL_READ_COMPARE → HR06_AUTHORITY → LEGACY_READONLY_PROJECTION。
切换显式记录 + 审计；禁止 silent fallback。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class HrChangeAuthorityMode(models.Model):
    class Mode(models.TextChoices):
        LEGACY_ACTIVE = "LEGACY_ACTIVE", _("Legacy Active")
        DUAL_READ_COMPARE = "DUAL_READ_COMPARE", _("Dual Read Compare")
        HR06_AUTHORITY = "HR06_AUTHORITY", _("HR06 Authority")
        LEGACY_READONLY_PROJECTION = "LEGACY_READONLY_PROJECTION", _("Legacy Readonly Projection")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True, unique=True)
    mode = models.CharField(max_length=32, choices=Mode.choices, default=Mode.LEGACY_ACTIVE)
    switched_by = models.BigIntegerField(null=True, blank=True)
    switched_at = models.DateTimeField(auto_now=True)
    note = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = _("HR Change Authority Mode")
        verbose_name_plural = _("HR Change Authority Modes")

    def __str__(self):
        return f"tenant={self.tenant_id} {self.mode}"
