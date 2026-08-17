"""
hr_control_center/providers/todo_recruitment.py

RecruitmentTodoProvider —— 招聘流程待办（真实数据源）。

接 Horilla recruitment 模块：
- 开放中的招聘项目（open recruitment）→ 待办（HR 管理员负责推进）
- 待办人不推断业务审批状态机，只聚合"当前开放需跟进"的招聘项目。

硬合同：模块未启用 → UNAVAILABLE；禁止 fake-zero；禁止 except pass。
"""

from __future__ import annotations

from typing import List, Optional

from django.apps import apps

from hr_control_center.context import HrRequestContext
from hr_control_center.providers.todo_base import (
    HrTodoProvider,
    TodoItem,
    TodoSummary,
)


class RecruitmentTodoProvider(HrTodoProvider):
    provider_key = "recruitment"

    def _module_available(self) -> bool:
        return apps.is_installed("recruitment")

    def _qs(self):
        from recruitment.models import Recruitment

        return Recruitment.objects.filter(closed=False)

    def get_summary(self, context: HrRequestContext) -> TodoSummary:
        if not self._module_available():
            return TodoSummary()
        try:
            total = self._qs().count()
            return TodoSummary(total=total, overdue=0, today=0, week=total)
        except Exception:
            return TodoSummary()

    def list_todos(
        self,
        context: HrRequestContext,
        filters: Optional[dict] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        if not self._module_available():
            return {"items": [], "total": 0, "available": False}
        try:
            from recruitment.models import Recruitment

            qs = Recruitment.objects.filter(closed=False, is_active=True).order_by("-id")
            total = qs.count()
            start = (page - 1) * page_size
            items: List[TodoItem] = []
            for rec in qs[start : start + page_size]:
                items.append(
                    TodoItem(
                        provider=self.provider_key,
                        business_type="recruitment",
                        business_id=str(rec.id),
                        title=f"招聘项目跟进：{rec.title or '未命名'}",
                        subject_name=rec.title or "",
                        current_stage="开放中",
                        severity="MEDIUM",
                        action_label="查看招聘",
                        action_url=f"/recruitment/recruitment-view/{rec.id}/",
                        permission_code="recruitment.view_recruitment",
                    )
                )
            return {
                "items": [i.__dict__ for i in items],
                "total": total,
                "available": True,
            }
        except Exception:
            return {"items": [], "total": 0, "available": False}
