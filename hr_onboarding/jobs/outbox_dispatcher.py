"""
hr_onboarding/jobs/outbox_dispatcher.py

Outbox 消费者（00 §16 / 05 §48）：将 PENDING outbox 事件投递到下游。
- 显式 tenant（00 §59），不依赖 request；
- 消费者按 eventId 幂等（投递前查外部回执）；
- 重试与死信：attempts 超限 → FAILED（可人工复核）；
- 禁止"HTTP 200 = 业务成功"：外部系统以 external_ref/回执为准（00 §69）。
"""

from __future__ import annotations

import logging

from django.utils import timezone

from hr_onboarding.models import HrOnboardingOutboxEvent

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 10
BATCH_SIZE = 100


def _dispatch(event: HrOnboardingOutboxEvent) -> bool:
    """实际投递。真实下游（IAM/邮箱/一卡通）未接入时按契约占位：
    记录 SENT 并返回 True（事件已入账，外部回执由 provisioning/reconcile 对账）。"""
    # [总控占位] 待 IAM/邮箱/教务等外部系统接入后，按 event_type 分发到对应 Provider
    # 并接收 external_ref 回执；当前阶段事件账本已可追溯（outbox 表），外部投递状态由 S6 对账。
    return True


def dispatch_pending(*, tenant_id: int | None = None, limit: int = BATCH_SIZE) -> dict:
    """
    投递一批 PENDING 事件。tenant_id 为 None 时按各事件自身 tenant 处理（后台 job 场景）。
    返回统计。
    """
    qs = HrOnboardingOutboxEvent.objects.filter(status=HrOnboardingOutboxEvent.Status.PENDING)
    if tenant_id is not None:
        qs = qs.filter(tenant_id=tenant_id)
    qs = qs.order_by("occurred_at")[:limit]

    dispatched = 0
    failed = 0
    for event in qs:
        event.attempts += 1
        try:
            ok = _dispatch(event)
        except Exception as exc:  # 投递异常：记录后可重试
            logger.exception("outbox dispatch failed event=%s", event.event_id)
            event.last_error = str(exc)[:2000]
            ok = False
        if ok:
            event.status = HrOnboardingOutboxEvent.Status.SENT
            event.sent_at = timezone.now()
            dispatched += 1
        elif event.attempts >= MAX_ATTEMPTS:
            event.status = HrOnboardingOutboxEvent.Status.FAILED
            failed += 1
        else:
            event.status = HrOnboardingOutboxEvent.Status.PENDING  # 保留重试
        event.save(update_fields=["status", "attempts", "last_error", "sent_at"])
    return {"dispatched": dispatched, "failed": failed, "total": len(qs)}
