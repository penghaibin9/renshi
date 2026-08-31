"""
hr_staff/models/events.py —— Outbox 事件（总册 §30，S10）。

原则：
- 正式事实变化 → 写入 HrOutboxEvent（同一事务），后台发布；
- Payload：stable IDs + tenant + effective date + version + changed field codes
  （避免无必要传敏感值）+ correlation/request ID；
- 跨域写只走 Provider/Event/command API，不直接改其他模块表。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class HrOutboxEvent(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        PUBLISHED = "PUBLISHED", _("Published")
        FAILED = "FAILED", _("Failed")
        DEAD = "DEAD", _("Dead")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    event_type = models.CharField(max_length=64, db_index=True)
    payload_json = models.JSONField(default=dict, blank=True)  # 只含 stable IDs/effective date/field codes，禁敏感值
    correlation_id = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.CharField(max_length=512, blank=True, default="")
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Outbox Event")
        verbose_name_plural = _("HR Outbox Events")
        indexes = [
            models.Index(fields=["tenant_id", "status", "created_at"]),
            models.Index(fields=["tenant_id", "event_type", "correlation_id"]),
        ]

    def __str__(self):
        return f"{self.event_type} [{self.status}] {self.correlation_id}"


class HrBusinessEventInbox(models.Model):
    """
    业务域 → HR03 事件收件箱（HR05/06/07/13/14/16 生效事实接收）。

    幂等：source_business_type + source_business_id 唯一；
    消费后置 status=CONSUMED；重复事件不重复写 authority。
    """

    class Status(models.TextChoices):
        RECEIVED = "RECEIVED", _("Received")
        PROCESSING = "PROCESSING", _("Processing")
        CONSUMED = "CONSUMED", _("Consumed")
        FAILED = "FAILED", _("Failed")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    event_type = models.CharField(max_length=64)  # HR05_ONBOARDING / HR06_TRANSFER / HR07_CONTRACT / HR13_TITLE_APPOINTMENT / HR14_APPOINTMENT / HR16_EXIT / HR16_REHIRE
    source_business_type = models.CharField(max_length=64)
    source_business_id = models.CharField(max_length=64)
    payload_json = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.RECEIVED
    )
    idempotency_key = models.CharField(max_length=128, unique=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.CharField(max_length=512, blank=True, default="")
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Business Event Inbox")
        verbose_name_plural = _("HR Business Event Inboxes")
        indexes = [
            models.Index(fields=["tenant_id", "status"]),
            models.Index(fields=["tenant_id", "source_business_type", "source_business_id"]),
        ]

    def __str__(self):
        return f"{self.event_type} {self.source_business_id} [{self.status}]"
