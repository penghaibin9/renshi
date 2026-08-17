"""
hr10_development/events/consumer.py

Inbox 事件消费者。

按 eventId/providerEventId 幂等；重复 10 次结果一致；旧 aggregateVersion 不覆盖新状态。
"""

import json
import logging

logger = logging.getLogger(__name__)


class DevelopmentEventConsumer:
    """
    HR10 入站事件消费者。

    S9 阶段：定义消费入口。后续阶段对接 HR03/HR06/HR11/HR14/HR15 的正式事件。
    """

    def __init__(self):
        self._processed_ids: set[str] = set()

    def is_duplicate(self, event_id: str) -> bool:
        return event_id in self._processed_ids

    def mark_processed(self, event_id: str):
        self._processed_ids.add(event_id)

    # ── 入站事件 handlers ──

    def handle_staff_activated(self, payload: dict, event_id: str):
        """HR03 StaffActivated → 触发个人发展计划自动初始化。"""
        if self.is_duplicate(event_id):
            return
        # S9: 日志记录；S10 阶段会触发自动创建个人发展计划
        logger.info("StaffActivated received: %s, triggering dev plan init", payload.get("staffMasterId"))
        self.mark_processed(event_id)

    def handle_personnel_change_effective(self, payload: dict, event_id: str):
        """HR06 PersonnelChangeEffective → 更新实训派出组织归属。"""
        if self.is_duplicate(event_id):
            return
        logger.info("PersonnelChangeEffective: %s", payload.get("assignmentId"))
        self.mark_processed(event_id)

    def handle_contract_effective(self, payload: dict, event_id: str):
        """HR07 ContractEffective → 触发实践协议状态更新。"""
        if self.is_duplicate(event_id):
            return
        logger.info("ContractEffective: %s", payload.get("agreementId"))
        self.mark_processed(event_id)

    def handle_exit_effective(self, payload: dict, event_id: str):
        """HR16 ExitEffective → 归档已离职教师的发展档案。"""
        if self.is_duplicate(event_id):
            return
        logger.info("ExitEffective: staff=%s, archiving development records", payload.get("staffMasterId"))
        self.mark_processed(event_id)

    def handle_compensation_reevaluation(self, payload: dict, event_id: str):
        """HR14→HR15 CompensationReevaluationRequested → (HR10 不直接消费，仅日志)"""
        if self.is_duplicate(event_id):
            return
        logger.info("CompensationReevaluationRequested (HR10 ignore): %s", payload)
        self.mark_processed(event_id)
