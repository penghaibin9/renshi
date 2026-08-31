"""
hr_structure/models/cutover.py

Hr02AuthorityCutover —— tenant 级 authority mode（总册 50.8）。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class Hr02AuthorityCutover(models.Model):
    class Mode(models.TextChoices):
        LEGACY_STRUCTURE_ONLY = "LEGACY_STRUCTURE_ONLY", _("Legacy Structure Only")
        DUAL_READ_COMPARE = "DUAL_READ_COMPARE", _("Dual Read Compare")
        HR02_AUTHORITY = "HR02_AUTHORITY", _("HR02 Authority")

    tenant_id = models.BigIntegerField(unique=True)
    mode = models.CharField(max_length=32, choices=Mode.choices, default=Mode.LEGACY_STRUCTURE_ONLY)
    cutover_at = models.DateTimeField(auto_now=True)
    operator = models.CharField(max_length=128, blank=True, default="")
    old_mode = models.CharField(max_length=32, blank=True, default="")
    reason = models.CharField(max_length=255, blank=True, default="")
    reconcile_report_id = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        verbose_name = _("HR02 Authority Cutover")
        verbose_name_plural = _("HR02 Authority Cutovers")

    def __str__(self):
        return f"tenant={self.tenant_id} mode={self.mode}"
