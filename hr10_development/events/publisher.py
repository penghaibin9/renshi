"""
hr10_development/events/publisher.py

Outbox 事件发布器。

领域服务中完成 domain state + audit + outbox 同事务写入。
此模块读取 PENDING 事件并发布到外部（HTTP / message queue / event bus）。

当前 S9 实现：从 HrDevelopmentOutboxEvent 表读取 PENDING → 标记 PUBLISHED。
后续可扩展为真正的外部投递（Kafka / RabbitMQ / HTTP webhook）。
"""

import logging
from datetime import datetime, timezone

from hr10_development.models.outbox import HrDevelopmentOutboxEvent

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


def dispatch_pending_events(batch_size: int = 100) -> int:
    """
    从 outbox 表读取 PENDING 事件并发布。

    返回成功发布的数量。
    """
    pending = (
        HrDevelopmentOutboxEvent.objects
        .filter(status="PENDING")
        .order_by("created_at")[:batch_size]
    )

    published_count = 0
    for event in pending:
        try:
            # 实际投递逻辑（S9: 日志输出；生产: HTTP/Kafka）
            _publish_to_consumers(event)

            event.status = "PUBLISHED"
            event.published_at = datetime.now(timezone.utc)
            event.save(update_fields=["status", "published_at", "updated_at"])
            published_count += 1

        except Exception as exc:
            event.retry_count += 1
            if event.retry_count >= MAX_RETRIES:
                event.status = "FAILED"
                logger.error("Outbox event %s/%s failed after %d retries: %s",
                             event.event_type, event.aggregate_id, MAX_RETRIES, exc)
            event.last_error = str(exc)[:1000]
            event.save(update_fields=["retry_count", "status", "last_error", "updated_at"])

    return published_count


def _publish_to_consumers(event: HrDevelopmentOutboxEvent):
    """
    向消费者投递事件。

    S9 阶段：记录日志 + 调用已注册 consumer handler。
    生产阶段：HTTP POST / Kafka produce 等。
    """
    from hr10_development.events.registry import DevelopmentEventRegistry

    spec = DevelopmentEventRegistry.get_by_type(event.event_type)
    consumers = spec.consumers if spec else []

    logger.info(
        "Publishing event %s (agg=%s/%s v%d) to consumers: %s",
        event.event_type,
        event.aggregate_type,
        event.aggregate_id,
        event.aggregate_version,
        consumers,
    )

    # HR09 Evidence: rebuild index on fact events
    if event.event_type in ("DevelopmentFactVerified", "DevelopmentFactSuperseded"):
        _rebuild_hr09_evidence_index(event)

    # HR11 time window: on enrollment / practice assignment
    if event.event_type in ("LearningEnrollmentCreated", "PracticeAssignmentCreated",
                            "PracticeAssignmentStarted"):
        _notify_hr11_time_window(event)


def _rebuild_hr09_evidence_index(event: HrDevelopmentOutboxEvent):
    """HR09 证据索引重建。生产阶段通过异步 job 执行。"""
    from hr10_development.services.development_fact_service import DevelopmentFactService
    try:
        DevelopmentFactService.rebuild_hr09_index(
            tenant_id=event.tenant_id,
            staff_master_id=event.payload_json.get("staffMasterId"),
        )
    except Exception as exc:
        logger.warning("HR09 evidence index rebuild skipped: %s", exc)


def _notify_hr11_time_window(event: HrDevelopmentOutboxEvent):
    """通知 HR11 更新授权培训/企业实践时间窗口。"""
    logger.info(
        "HR11 time window update: tenant=%s staff=%s event=%s",
        event.tenant_id,
        event.payload_json.get("staffMasterId"),
        event.event_type,
    )
