"""
hr_changes/integrations/outbox.py —— HR06 Outbox 入队（00 §16，S8）。

在领域事务内调用（同事务写入 outbox 表）；消费者按 eventId 幂等。
"""

from __future__ import annotations

import uuid
from typing import Optional

from hr_changes.models import HrChangeOutboxEvent


def enqueue_outbox(
    *,
    tenant_id: int,
    event_type: str,
    aggregate_type: str = "",
    aggregate_id: str = "",
    correlation_id: str = "",
    payload: Optional[dict] = None,
    event_id: Optional[str] = None,
) -> HrChangeOutboxEvent:
    return HrChangeOutboxEvent.objects.create(
        tenant_id=tenant_id,
        event_id=event_id or uuid.uuid4().hex,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=str(aggregate_id),
        correlation_id=correlation_id,
        payload_json=payload or {},
    )


def mark_sent(event_id: str) -> None:
    from django.utils import timezone

    HrChangeOutboxEvent.objects.filter(event_id=event_id).update(
        status=HrChangeOutboxEvent.Status.SENT,
        sent_at=timezone.now(),
    )


def mark_failed(event_id: str, error: str) -> None:
    HrChangeOutboxEvent.objects.filter(event_id=event_id).update(
        status=HrChangeOutboxEvent.Status.FAILED,
        last_error=error[:2000],
    )
