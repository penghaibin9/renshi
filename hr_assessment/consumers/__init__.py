"""HR12 — S10 补齐：Outbox 消费者接口 + Legacy PMS 迁移管理命令。"""

from __future__ import annotations

import logging

logger = logging.getLogger("hr_assessment.consumers")


class AssessmentResultConsumer:
    """考核结果下游消费者抽象 — HR07/HR13/HR14/HR15/HR16/HR18 集成点。"""

    def __init__(self, consumer_domain: str):
        self.consumer_domain = consumer_domain

    def consume(self, result_id: str, result_version: int, grade_code: str) -> dict:
        """消费考核结果 — S10 骨架，各下游域各自实现。"""
        logger.info(
            "AssessmentResultConsumed",
            extra={
                "consumer_domain": self.consumer_domain,
                "result_id": result_id,
                "result_version": result_version,
                "grade_code": grade_code,
            },
        )
        return {
            "consumer_domain": self.consumer_domain,
            "result_id": result_id,
            "ack": True,
        }

    def on_revision(self, result_id: str, old_version: int, new_version: int) -> dict:
        logger.info(
            "DownstreamAssessmentReviewRequired",
            extra={
                "consumer_domain": self.consumer_domain,
                "result_id": result_id,
                "old_version": old_version,
                "new_version": new_version,
            },
        )
        return {"consumer_domain": self.consumer_domain, "review_required": True}


# 下游消费者注册表
CONSUMER_REGISTRY = {
    "hr_contracts": AssessmentResultConsumer("hr_contracts"),
    "hr_title": AssessmentResultConsumer("hr_title"),
    "hr_appointment": AssessmentResultConsumer("hr_appointment"),
    "hr_payroll": AssessmentResultConsumer("hr_payroll"),
    "hr_exit": AssessmentResultConsumer("hr_exit"),
    "hr_data": AssessmentResultConsumer("hr_data"),
}


def get_consumer(domain: str) -> AssessmentResultConsumer | None:
    return CONSUMER_REGISTRY.get(domain)


def notify_all_consumers(result_id: str, result_version: int, grade_code: str) -> dict[str, dict]:
    results = {}
    for domain, consumer in CONSUMER_REGISTRY.items():
        try:
            results[domain] = consumer.consume(result_id, result_version, grade_code)
        except Exception as e:
            results[domain] = {"error": str(e)[:500], "ack": False}
    return results
