"""
hr_control_center/services/todo_service.py

TodoService —— HR01-02 我的待办聚合服务。

聚合各 HrTodoProvider：
- 模块未启用 → ProviderResult(UNAVAILABLE)，不 fake-zero。
- 不做审批动作（HR01 不是第二审批中心）。
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from hr_control_center.context import HrRequestContext
from hr_control_center.providers.base import ProviderResult
from hr_control_center.providers.todo_base import HrTodoProvider, TodoItem, TodoSummary
from hr_control_center.providers.todo_recruitment import RecruitmentTodoProvider


def _all_providers() -> List[HrTodoProvider]:
    return [RecruitmentTodoProvider()]


class TodoService:
    def get_summary(self, context: HrRequestContext) -> dict:
        """聚合各 provider 的待办统计。"""
        total = overdue = today = week = 0
        partial_sources = []
        for provider in _all_providers():
            try:
                s = provider.get_summary(context)
                total += s.total
                overdue += s.overdue
                today += s.today
                week += s.week
            except Exception:
                partial_sources.append(provider.provider_key)
        return {
            "overdue": overdue,
            "today": today,
            "week": week,
            "total": total,
            "partialSources": partial_sources,
        }

    def list_todos(
        self,
        context: HrRequestContext,
        filters: Optional[dict] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """聚合各 provider 的待办列表（DB 分页，禁止前端分页）。"""
        filters = filters or {}
        all_items: List[TodoItem] = []
        total = 0
        partial_sources = []

        for provider in _all_providers():
            try:
                result = provider.list_todos(context, filters, page=page, page_size=page_size)
                if not result.get("available", True):
                    partial_sources.append(provider.provider_key)
                    continue
                total += result.get("total", 0)
                for raw in result.get("items", []):
                    item = TodoItem(**{k: v for k, v in raw.items() if k in TodoItem.__dataclass_fields__})
                    all_items.append(item)
            except Exception:
                partial_sources.append(provider.provider_key)

        # 排序：CRITICAL > 逾期 > dueAt > submittedAt（总册 10.5）
        def sort_key(item: TodoItem):
            severity_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
            return (
                severity_rank.get(item.severity, 4),
                0 if not item.is_overdue else 1,
                item.due_at or datetime.max,
                item.submitted_at or datetime.max,
            )

        all_items.sort(key=sort_key)

        # 简单分页（聚合后）
        start = (page - 1) * page_size
        page_items = all_items[start : start + page_size]

        return {
            "items": [item.__dict__ for item in page_items],
            "pagination": {
                "page": page,
                "pageSize": page_size,
                "total": len(all_items),
            },
            "partialSources": partial_sources,
        }
