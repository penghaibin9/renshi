"""Durable controls for retiring the legacy PMS writer.

The seal deliberately lives in the HR12 authority database.  A cache flag alone
is not a cutover control: it can disappear on restart or differ between workers.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone


class HrLegacyPmsWriterSeal(models.Model):
    """Singleton, durable state for the legacy PMS formal writer."""

    SEAL_KEY = "PMS_FORMAL_WRITER"

    key = models.CharField(max_length=50, primary_key=True, default=SEAL_KEY, editable=False)
    is_frozen = models.BooleanField(default=False, db_index=True)
    revision = models.PositiveBigIntegerField(default=0)
    reason = models.CharField(max_length=500, blank=True, default="")
    operator = models.CharField(max_length=150, blank=True, default="SYSTEM")
    frozen_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "hr_assessment_legacy_pms_writer_seal"
        verbose_name = "Legacy PMS writer seal"

    def apply(self, *, frozen: bool, reason: str, operator: str) -> None:
        self.is_frozen = frozen
        self.reason = reason.strip()
        self.operator = operator.strip() or "SYSTEM"
        self.revision += 1
        self.frozen_at = timezone.now() if frozen else None


class HrLegacyPmsWriterSealEvent(models.Model):
    """Append-only audit record for every freeze or rollback."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    action = models.CharField(max_length=20)
    revision = models.PositiveBigIntegerField()
    reason = models.CharField(max_length=500, blank=True, default="")
    operator = models.CharField(max_length=150, default="SYSTEM")
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "hr_assessment_legacy_pms_writer_seal_event"
        ordering = ("-occurred_at",)
        verbose_name = "Legacy PMS writer seal event"
