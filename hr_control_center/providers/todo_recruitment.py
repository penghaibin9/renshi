"""
hr_control_center/providers/todo_recruitment.py

RecruitmentTodoProvider —— 招聘流程待办（真实数据源）。

接 Horilla recruitment 模块：
- 开放中的招聘项目（open recruitment）→ 待办（HR 管理员负责推进）
- 待办人不推断业务审批状态机，只聚合"当前开放需跟进"的招聘项目。

硬合同：模块未启用 → UNAVAILABLE；禁止 fake-zero；禁止 except pass。
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import List, Optional

from django.apps import apps

from hr_control_center.context import HrRequestContext
from hr_control_center.providers.todo_base import (
    HrTodoProvider,
    TodoItem,
    TodoProviderUnavailable,
    TodoSummary,
)


class RecruitmentTodoProvider(HrTodoProvider):
    provider_key = "recruitment"
    required_permission = "recruitment.view_recruitment"

    def _module_available(self) -> bool:
        return apps.is_installed("recruitment")

    def _assert_available(self, context: HrRequestContext) -> None:
        if not self._module_available():
            raise TodoProviderUnavailable(
                self.provider_key, "MODULE_NOT_AVAILABLE", "招聘模块未启用"
            )
        if context.as_of != context.today():
            raise TodoProviderUnavailable(
                self.provider_key,
                "HISTORICAL_TODO_UNAVAILABLE",
                "招聘待办只提供当前任务，不能用当前快照回答历史日期",
            )

    def _qs(self, context: HrRequestContext):
        from recruitment.models import Recruitment

        if not context.tenant_id:
            raise TodoProviderUnavailable(
                self.provider_key, "TENANT_CONTEXT_REQUIRED", "缺少学校租户"
            )
        return Recruitment.objects.filter(
            company_id_id=context.tenant_id,
            closed=False,
            is_active=True,
        )

    def get_summary(self, context: HrRequestContext) -> TodoSummary:
        self._assert_available(context)
        today = context.today()
        qs = self._qs(context)
        return TodoSummary(
            total=qs.count(),
            overdue=qs.filter(end_date__lt=today).count(),
            today=qs.filter(end_date=today).count(),
            week=qs.filter(end_date__gte=today, end_date__lte=today + timedelta(days=7)).count(),
        )

    def list_todos(
        self,
        context: HrRequestContext,
        filters: Optional[dict] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        self._assert_available(context)
        qs = self._qs(context).order_by("end_date", "-id")
        total = qs.count()
        start = (page - 1) * page_size
        items: List[TodoItem] = []
        for rec in qs[start : start + page_size]:
            submitted_at = datetime.combine(
                rec.start_date, time.min, tzinfo=context.tzinfo()
            ) if rec.start_date else None
            due_at = datetime.combine(
                rec.end_date, time.max, tzinfo=context.tzinfo()
            ) if rec.end_date else None
            items.append(
                TodoItem(
                    provider=self.provider_key,
                    business_type="recruitment",
                    business_id=str(rec.id),
                    title=f"招聘项目跟进：{rec.title or '未命名'}",
                    subject_name=rec.title or "",
                    current_stage="开放中",
                    severity="HIGH" if rec.end_date and rec.end_date < context.today() else "MEDIUM",
                    submitted_at=submitted_at,
                    due_at=due_at,
                    is_overdue=bool(rec.end_date and rec.end_date < context.today()),
                    action_label="查看招聘",
                    action_url=f"/recruitment/recruitment-view/{rec.id}/",
                    permission_code=self.required_permission,
                )
            )
        return {
            "items": [i.__dict__ for i in items],
            "total": total,
            "available": True,
        }
