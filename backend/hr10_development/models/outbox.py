"""
hr10_development/models/outbox.py

HR10 Outbox 事件模型（对齐 HR03 HrOutboxEvent 模式）。
事务内写 domain state + audit + outbox 同事务。
"""

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from hr10_development.constants import DevelopmentEventType
from hr10_development.models.base import DevelopmentTenantModel


class HrDevelopmentOutboxEvent(DevelopmentTenantModel):
    """
    HR10 Outbox 事件。

    状态：PENDING → PUBLISHED（成功）/ FAILED（可重试）/ DEAD（达上限）。
    """

    event_type = models.CharField(
        max_length=128,
        choices=DevelopmentEventType.choices,
        db_index=True,
        verbose_name=_("事件类型"),
    )

    event_version = models.IntegerField(
        default=1,
        verbose_name=_("事件版本"),
    )

    aggregate_type = models.CharField(
        max_length=128,
        verbose_name=_("聚合类型"),
    )

    aggregate_id = models.CharField(
        max_length=64,
        verbose_name=_("聚合 ID"),
    )

    aggregate_version = models.IntegerField(
        default=1,
        verbose_name=_("聚合版本"),
    )

    occurred_at = models.DateTimeField(
        default=timezone.now,
        verbose_name=_("发生时间"),
    )

    effective_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("生效时间"),
    )

    correlation_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name=_("关联 ID"),
    )

    causation_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name=_("因果 ID"),
    )

    payload_json = models.JSONField(
        default=dict,
        verbose_name=_("事件负载"),
    )

    status = models.CharField(
        max_length=16,
        default="PENDING",
        db_index=True,
        verbose_name=_("状态"),
    )

    retry_count = models.IntegerField(
        default=0,
        verbose_name=_("重试次数"),
    )

    last_error = models.TextField(
        blank=True,
        default="",
        verbose_name=_("最近错误"),
    )

    published_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("发布时间"),
    )

    class Meta:
        db_table = "hr_development_outbox_event"
        verbose_name = _("发展 Outbox 事件")
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["aggregate_type", "aggregate_id"]),
            models.Index(fields=["correlation_id"]),
        ]

    def __str__(self):
        return f"{self.event_type} ({self.aggregate_type}/{self.aggregate_id})"
