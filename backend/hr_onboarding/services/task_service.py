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
    # 模板 DAG 校验
    # ------------------------------------------------------------------
    def validate_no_cycles(self, template_version_id) -> None:
        """校验一个模板版本的任务依赖图必须是闭合 DAG。

        依赖只允许引用同 tenant、同 template_version 下的任务 code。检测到
        不存在的前置任务或任意环（自环/互环/长环）均 fail-closed，避免模板
        被激活后出现永远无法完成的 onboarding task chain。
        """
        definitions = list(
            HrOnboardingTaskDefinition.objects.filter(
                tenant_id=self.tenant_id,
                template_version_id=template_version_id,
            ).only("code", "prerequisite_codes")
        )
        graph = {
            definition.code: list(definition.prerequisite_codes or [])
            for definition in definitions
        }

        unknown = sorted(
            {
                prerequisite
                for prerequisites in graph.values()
                for prerequisite in prerequisites
                if prerequisite not in graph
            }
        )
        if unknown:
            raise TaskPrerequisiteNotMetError(
                f"前置任务不存在: {unknown}",
                details={"missingDefinitions": unknown},
            )

        visiting: set[str] = set()
        visited: set[str] = set()
        path: list[str] = []

        def visit(code: str) -> None:
            if code in visited:
                return
            if code in visiting:
                start = path.index(code) if code in path else 0
                cycle = path[start:] + [code]
                raise TaskPrerequisiteNotMetError(
                    f"任务前置关系存在环: {' -> '.join(cycle)}",
                    details={"cycle": cycle},
                )

            visiting.add(code)
            path.append(code)
            for prerequisite in graph[code]:
                visit(prerequisite)
            path.pop()
            visiting.remove(code)
            visited.add(code)

        for code in graph:
            visit(code)

    # ------------------------------------------------------------------
    # 实例化
    # ------------------------------------------------------------------
    @transaction.atomic
    def instantiate_tasks(self, case, *, assignee_overrides: Optional[dict] = None) -> int:
        """按 case.template_version 的任务定义实例化（幂等）。返回新建数。"""
        if case.template_version is None:
            return 0
        self.validate_no_cycles(case.template_version_id)
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
                tenant_id=self.tenant_id,
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

    def _promote_ready_if_possible(
        self, instance: HrOnboardingTaskInstance
    ) -> HrOnboardingTaskInstance:
        """Resolve NOT_STARTED lazily once prerequisites are satisfied.

        Instances intentionally start as NOT_STARTED. The first actionable
        operation may therefore need to pass through READY before entering the
        public action state. Keeping that promotion inside the service avoids
        weakening the state machine with direct NOT_STARTED -> action edges.
        """
        if instance.status != TaskStatus.NOT_STARTED:
            return instance
        self._check_prerequisites(instance)
        assert_task_transition(instance.status, TaskStatus.READY)
        instance.status = TaskStatus.READY
        instance.version += 1
        instance.save(update_fields=["status", "version", "updated_at"])
        return instance

    @transaction.atomic
    def start_task(self, instance: HrOnboardingTaskInstance) -> HrOnboardingTaskInstance:
        instance = HrOnboardingTaskInstance.objects.select_for_update().get(
            tenant_id=self.tenant_id,
            id=instance.id,
        )
        if instance.status == TaskStatus.COMPLETED:
            raise TaskAlreadyCompletedError("任务已完成")
        instance = self._promote_ready_if_possible(instance)
        self._check_prerequisites(instance)
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
        instance = HrOnboardingTaskInstance.objects.select_for_update().get(
            tenant_id=self.tenant_id,
            id=instance.id,
        )
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
        instance = HrOnboardingTaskInstance.objects.select_for_update().get(
            tenant_id=self.tenant_id,
            id=instance.id,
        )
        if not reason:
            raise Hr05ApiError("豁免必须填写 reason（WAIVED 语义：reason+authority+audit）")
        if instance.status == TaskStatus.COMPLETED:
            raise TaskAlreadyCompletedError("任务已完成")
        instance = self._promote_ready_if_possible(instance)
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
