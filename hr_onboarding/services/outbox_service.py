"""
hr_onboarding/services/outbox_service.py

Outbox 入队（与领域事务同事务，00 §16）。
消费者按 eventId 幂等；重复投递结果一致。
"""

from __future__ import annotations

import uuid
from typing import Optional

from hr_onboarding.models import HrOnboardingOutboxEvent


def enqueue_outbox(
    *,
    tenant_id: int,
    event_type: str,
    aggregate_type: str = "",
    aggregate_id: str = "",
    correlation_id: str = "",
    payload: Optional[dict] = None,
    event_id: Optional[str] = None,
) -> HrOnboardingOutboxEvent:
    """在领域事务内调用（同事务写入 outbox 表）。"""
    return HrOnboardingOutboxEvent.objects.create(
        tenant_id=tenant_id,
        event_id=event_id or uuid.uuid4().hex,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=str(aggregate_id),
        correlation_id=correlation_id,
        payload_json=payload or {},
    )


def mark_sent(event_id: str) -> None:
    """消费者确认后标记 SENT（外部投递成功）。"""
    from django.utils import timezone

    HrOnboardingOutboxEvent.objects.filter(event_id=event_id).update(
        status=HrOnboardingOutboxEvent.Status.SENT,
        sent_at=timezone.now(),
    )


def mark_failed(event_id: str, error: str) -> None:
    HrOnboardingOutboxEvent.objects.filter(event_id=event_id).update(
        status=HrOnboardingOutboxEvent.Status.FAILED,
        last_error=error[:2000],
    )
