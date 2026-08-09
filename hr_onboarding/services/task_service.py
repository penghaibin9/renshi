"""
hr_onboarding/services/task_service.py

入职协同任务（HR05-04，总册 §14）：
- instantiate_tasks：模板 → 实例（幂等：case+definition+cycle 唯一）；assignee 按角色解析；
- start/complete/waive：权威 9 态状态机；waive 必须 reason+authority+audit；
- prerequisite：任务 DAG 前置校验（防环，TASK_PREREQUISITE_NOT_MET）；
- 完成必须有 completion_payload（完成人/时间/备注/证据）。
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional

from django.db import transaction
from django.utils import timezone

from hr_onboarding.api.exceptions import (
    Hr05ApiError,
    TaskAlreadyCompletedError,
    TaskPrerequisiteNotMetError,
)
from hr_onboarding.constants import ResponsibleRole, TaskStatus
from hr_onboarding.models import HrOnboardingTaskDefinition, HrOnboardingTaskInstance
from hr_onboarding.policies.state_machine import assert_task_transition

logger = logging.getLogger(__name__)


class TaskService:
    def __init__(self, *, tenant_id: int, actor_user_id: Optional[int] = None):
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id

    # ------------------------------------------------------------------
    # 实例化
    # ------------------------------------------------------------------
    @transaction.atomic
    def instantiate_tasks(self, case, *, assignee_overrides: Optional[dict] = None) -> int:
        """按 case.template_version 的任务定义实例化（幂等）。返回新建数。"""
        if case.template_version is None:
            return 0
        created = 0
        definitions = HrOnboardingTaskDefinition.objects.filter(
            tenant_id=self.tenant_id, template_version=case.template_version
        ).order_by("sequence")
        base = timezone.now()
        for definition in definitions:
            _, was_created = HrOnboardingTaskInstance.objects.get_or_create(
                tenant_id=self.tenant_id,
                case=case,
                definition=definition,
                cycle="INITIAL",
                defaults={
                    "assignee_type": definition.responsible_role,
                    "assignee_id": (assignee_overrides or {}).get(definition.responsible_role),
                    "status": TaskStatus.NOT_STARTED,
                    "available_at": base + timedelta(days=definition.available_offset_days),
                    "due_at": base + timedelta(days=definition.due_offset_days),
                },
            )
            if was_created:
                created += 1
        return created

    # ------------------------------------------------------------------
    # 状态推进
    # ------------------------------------------------------------------
    def _check_prerequisites(self, instance: HrOnboardingTaskInstance) -> None:
        """前置任务（definition.prerequisite_codes）必须 COMPLETED/WAIVED。"""
        prereq_codes = (instance.definition.prerequisite_codes or [])
        if not prereq_codes:
            return
        done_statuses = (TaskStatus.COMPLETED, TaskStatus.WAIVED)
        missing = []
        for code in prereq_codes:
            dep = HrOnboardingTaskInstance.objects.filter(
                case=instance.case,
                definition__code=code,
                cycle=instance.cycle,
            ).first()
            if dep is None or dep.status not in done_statuses:
                missing.append(code)
        if missing:
            raise TaskPrerequisiteNotMetError(
                f"前置任务未完成: {missing}",
                details={"missing": missing},
            )

    @transaction.atomic
    def start_task(self, instance: HrOnboardingTaskInstance) -> HrOnboardingTaskInstance:
        instance = HrOnboardingTaskInstance.objects.select_for_update().get(id=instance.id)
        if instance.status == TaskStatus.COMPLETED:
            raise TaskAlreadyCompletedError("任务已完成")
        assert_task_transition(instance.status, TaskStatus.IN_PROGRESS)
        instance.status = TaskStatus.IN_PROGRESS
        instance.started_at = timezone.now()
        instance.version += 1
        instance.save(update_fields=["status", "started_at", "version", "updated_at"])
        return instance

    @transaction.atomic
    def complete_task(
        self,
        instance: HrOnboardingTaskInstance,
        *,
        note: str = "",
        evidence: Optional[dict] = None,
    ) -> HrOnboardingTaskInstance:
        instance = HrOnboardingTaskInstance.objects.select_for_update().get(id=instance.id)
        self._check_prerequisites(instance)
        if instance.status == TaskStatus.COMPLETED:
            raise TaskAlreadyCompletedError("任务已完成")
        assert_task_transition(instance.status, TaskStatus.COMPLETED)
        instance.status = TaskStatus.COMPLETED
        instance.completed_at = timezone.now()
        instance.completion_payload = {
            "completed_by": self.actor_user_id,
            "completed_at": instance.completed_at.isoformat(),
            "note": note,
            "evidence": evidence or {},
        }
        instance.version += 1
        instance.save(
            update_fields=["status", "completed_at", "completion_payload", "version", "updated_at"]
        )
        return instance

    @transaction.atomic
    def waive_task(self, instance: HrOnboardingTaskInstance, *, reason: str) -> HrOnboardingTaskInstance:
        instance = HrOnboardingTaskInstance.objects.select_for_update().get(id=instance.id)
        if not reason:
            raise Hr05ApiError("豁免必须填写 reason（WAIVED 语义：reason+authority+audit）")
        if instance.status == TaskStatus.COMPLETED:
            raise TaskAlreadyCompletedError("任务已完成")
        assert_task_transition(instance.status, TaskStatus.WAIVED)
        instance.status = TaskStatus.WAIVED
        instance.completion_payload = {
            "waived_by": self.actor_user_id,
            "waived_at": timezone.now().isoformat(),
            "reason": reason,
        }
        instance.version += 1
        instance.save(update_fields=["status", "completion_payload", "version", "updated_at"])
        return instance
