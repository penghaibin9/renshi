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


def mark_sent(event_id: str, *, external_ref: str) -> None:
    """兼容入口：只有携带稳定外部回执的消费者确认才可标记 SENT。"""
    from django.utils import timezone

    external_ref = str(external_ref or "").strip()
    if not external_ref:
        raise ValueError("HR05_OUTBOX_ACK_RECEIPT_REQUIRED")
    HrOnboardingOutboxEvent.objects.filter(
        event_id=event_id,
        status=HrOnboardingOutboxEvent.Status.PENDING,
    ).update(
        status=HrOnboardingOutboxEvent.Status.SENT,
        external_ref=external_ref[:255],
        sent_at=timezone.now(),
        next_attempt_at=None,
        lease_owner="",
        lease_expires_at=None,
        last_error="",
    )


def mark_failed(event_id: str, error: str) -> None:
    HrOnboardingOutboxEvent.objects.filter(
        event_id=event_id,
        status=HrOnboardingOutboxEvent.Status.PENDING,
    ).update(
        status=HrOnboardingOutboxEvent.Status.FAILED,
        last_error=error[:2000],
        next_attempt_at=None,
        lease_owner="",
        lease_expires_at=None,
    )
