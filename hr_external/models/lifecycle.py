"""
hr_external/models/lifecycle.py —— HrExternalLifecycleEvent（S2，总册 §103 Outbox Events / 00 §15）。

- 事件信封：eventId/eventType/eventVersion/tenantId/aggregateType/aggregateId/aggregateVersion/
  occurredAt/effectiveAt/correlationId/causationId/payload（00 §15）。
- 幂等：idempotency_key tenant 内唯一（00 §16 消费者幂等）。
- 正式事务必须 domain state + audit + outbox 同事务（00 §16）；发布失败可重试。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class LifecycleEventStatus(models.TextChoices):
    PENDING = "PENDING", _("Pending")
    PUBLISHED = "PUBLISHED", _("Published")
    FAILED = "FAILED", _("Failed")
    RETRYING = "RETRYING", _("Retrying")


class HrExternalLifecycleEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    event_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    event_type = models.CharField(max_length=64, db_index=True)
    event_version = models.PositiveIntegerField(default=1)
    aggregate_type = models.CharField(max_length=64, blank=True, default="")
    aggregate_id = models.UUIDField(null=True, blank=True)
    aggregate_version = models.BigIntegerField(default=1)
    engagement_id = models.ForeignKey(
        "hr_external.HrExternalEngagement",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lifecycle_events",
    )
    occurred_at = models.DateTimeField(auto_now_add=True)
    effective_at = models.DateTimeField(null=True, blank=True)
    correlation_id = models.CharField(max_length=64, blank=True, default="")
    causation_id = models.CharField(max_length=64, blank=True, default="")
    payload_json = models.JSONField(default=dict, blank=True)
    idempotency_key = models.CharField(max_length=128, db_index=True)
    status = models.CharField(
        max_length=16,
        choices=LifecycleEventStatus.choices,
        default=LifecycleEventStatus.PENDING,
    )
    retry_count = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _("HR External Lifecycle Event")
        verbose_name_plural = _("HR External Lifecycle Events")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "idempotency_key"],
                name="uniq_hr_external_lifecycle_idem",
            ),
            models.CheckConstraint(
                condition=models.Q(event_version__gte=1),
                name="hr_external_lifecycle_version_gte_1",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "event_type", "occurred_at"],
                name="hr_external_lifecycle_type_time_idx",
            ),
            models.Index(
                fields=["tenant_id", "engagement_id", "occurred_at"],
                name="hr_external_lifecycle_eng_time_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] {self.event_type} {self.status}"
