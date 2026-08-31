"""
hr_changes/models/outbox.py —— HrChangeOutboxEvent（00 §16 / 总册 §59）。

正式事务必须 domain state + audit + outbox 同事务；发布失败可重试；消费者按 eventId 幂等。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class HrChangeOutboxEvent(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        SENT = "SENT", _("Sent")
        FAILED = "FAILED", _("Failed")
        DROPPED = "DROPPED", _("Dropped")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    event_id = models.CharField(max_length=64, unique=True)
    event_type = models.CharField(max_length=64, db_index=True)
    event_version = models.PositiveIntegerField(default=1)
    aggregate_type = models.CharField(max_length=32, blank=True, default="")
    aggregate_id = models.CharField(max_length=64, blank=True, default="")
    correlation_id = models.CharField(max_length=64, blank=True, default="")
    payload_json = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    occurred_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("HR Change Outbox Event")
        verbose_name_plural = _("HR Change Outbox Events")
        indexes = [
            models.Index(fields=["tenant_id", "status", "occurred_at"]),
        ]

    def __str__(self):
        return f"{self.event_type}:{self.status}"
