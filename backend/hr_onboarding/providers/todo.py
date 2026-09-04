"""Canonical HR05 collaboration-task todos for the HR01 workbench."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from django.db.models import Q

from hr_control_center.providers.todo_base import (
    HrTodoProvider,
    TodoItem,
    TodoProviderUnavailable,
    TodoSummary,
)
from hr_onboarding.constants import BlockingLevel, TaskStatus


_ACTIVE = {
    TaskStatus.NOT_STARTED,
    TaskStatus.READY,
    TaskStatus.IN_PROGRESS,
    TaskStatus.WAITING_EXTERNAL,
    TaskStatus.BLOCKED,
    TaskStatus.FAILED,
}

_STATUS_LABELS = {
    "NOT_STARTED": "未开始",
    "READY": "待办理",
    "IN_PROGRESS": "办理中",
    "WAITING_EXTERNAL": "等待外部协同",
    "BLOCKED": "已阻塞",
    "FAILED": "办理失败",
}


class OnboardingTaskTodoProvider(HrTodoProvider):
    provider_key = "hr05_onboarding"
    required_permission = "hr.onboarding.task.manage"

    @staticmethod
    def _assert_current(context) -> None:
        if not context.tenant_id:
            raise TodoProviderUnavailable(
                "hr05_onboarding", "TENANT_CONTEXT_REQUIRED", "缺少学校租户"
            )
        if context.as_of != context.today():
            raise TodoProviderUnavailable(
                "hr05_onboarding",
                "HISTORICAL_TODO_UNAVAILABLE",
                "入职协同待办只提供当前任务",
            )

    def _qs(self, context):
        from hr_onboarding.models import HrOnboardingTaskInstance

        self._assert_current(context)
        query = HrOnboardingTaskInstance.objects.filter(
            tenant_id=context.tenant_id,
            status__in=_ACTIVE,
        )
        if context.user_id:
            query = query.filter(
                Q(assignee_id=context.user_id) | Q(assignee_id__isnull=True)
            )
        return query

    @staticmethod
    def _day_bounds(context):
        today = context.today()
        start = datetime.combine(today, time.min, tzinfo=context.tzinfo())
        return start, start + timedelta(days=1), start + timedelta(days=8)

    def get_summary(self, context) -> TodoSummary:
        query = self._qs(context)
        start, tomorrow, week_end = self._day_bounds(context)
        return TodoSummary(
            total=query.count(),
            overdue=query.filter(due_at__lt=start).count(),
            today=query.filter(due_at__gte=start, due_at__lt=tomorrow).count(),
            week=query.filter(due_at__gte=start, due_at__lt=week_end).count(),
        )

    def _to_item(self, task, context) -> TodoItem:
        due_at = task.due_at
        overdue = bool(due_at and due_at < context.now())
        blocking = task.definition.blocking_level
        severity = (
            "CRITICAL"
            if task.status in {TaskStatus.BLOCKED, TaskStatus.FAILED}
            or blocking in {BlockingLevel.BLOCKS_PAYROLL, BlockingLevel.BLOCKS_WORK_ACCESS}
            else ("HIGH" if overdue else "MEDIUM")
        )
        return TodoItem(
            provider=self.provider_key,
            business_type="onboarding_task",
            business_id=str(task.id),
            title=task.definition.title,
            subject_name=task.case.case_no,
            current_stage=_STATUS_LABELS.get(task.status, task.status),
            severity=severity,
            submitted_at=task.started_at or task.created_at,
            due_at=due_at,
            is_overdue=overdue,
            assignee_type=task.assignee_type,
            action_label="办理入职任务",
            action_url=f"/hr/onboarding/collaboration?case_id={task.case_id}",
            permission_code=self.required_permission,
            version=str(task.version),
        )

    def list_todos(self, context, filters=None, page=1, page_size=20):
        query = self._qs(context).select_related("case", "definition").order_by(
            "due_at", "created_at"
        )
        total = query.count()
        start = (page - 1) * page_size
        items = [
            self._to_item(task, context).__dict__
            for task in query[start : start + page_size]
        ]
        return {"items": items, "total": total, "available": True}
