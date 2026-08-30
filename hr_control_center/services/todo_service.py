"""
hr_control_center/services/todo_service.py

TodoService —— HR01-02 我的待办聚合服务。

聚合各 HrTodoProvider：
- 模块未启用 → ProviderResult(UNAVAILABLE)，不 fake-zero。
- 不做审批动作（HR01 不是第二审批中心）。
"""

from __future__ import annotations

from typing import List, Optional

from hr_control_center.context import HrRequestContext
from hr_control_center.providers.todo_base import (
    HrTodoProvider,
    TodoItem,
    TodoProviderUnavailable,
)
from hr_control_center.providers.todo_recruitment import RecruitmentTodoProvider
from hr_control_center.providers.todo_registry import (
    register_todo_provider,
    todo_provider_registry,
)


register_todo_provider(RecruitmentTodoProvider)

def _all_providers() -> List[HrTodoProvider]:
    return list(todo_provider_registry.create_all())


class TodoService:
    def __init__(self, providers=None):
        self.providers = tuple(providers) if providers is not None else tuple(_all_providers())

    @staticmethod
    def _allowed(provider, user) -> bool:
        permission = getattr(provider, "required_permission", "")
        if not permission or user is None:
            return True
        return bool(getattr(user, "is_superuser", False) or user.has_perm(permission))

    @staticmethod
    def _source_failure(provider, exc) -> dict:
        if isinstance(exc, TodoProviderUnavailable):
            return {
                "source": provider.provider_key,
                "status": "UNAVAILABLE",
                "reasonCode": exc.reason_code,
                "message": exc.message,
            }
        return {
            "source": provider.provider_key,
            "status": "ERROR",
            "reasonCode": "PROVIDER_ERROR",
            "message": "来源暂时不可用",
        }

    def get_summary(self, context: HrRequestContext, user=None) -> dict:
        """聚合各 provider 的待办统计。"""
        total = overdue = today = week = 0
        partial_sources = []
        source_health = []
        successful_sources = 0
        visible_sources = 0
        for provider in self.providers:
            if not self._allowed(provider, user):
                source_health.append({"source": provider.provider_key, "status": "FILTERED"})
                continue
            visible_sources += 1
            try:
                s = provider.get_summary(context)
                successful_sources += 1
                total += s.total
                overdue += s.overdue
                today += s.today
                week += s.week
                source_health.append({"source": provider.provider_key, "status": "OK"})
            except Exception as exc:
                partial_sources.append(provider.provider_key)
                source_health.append(self._source_failure(provider, exc))
        unavailable = visible_sources > 0 and successful_sources == 0
        return {
            "status": "UNAVAILABLE" if unavailable else ("PARTIAL" if partial_sources else "OK"),
            "overdue": None if unavailable else overdue,
            "today": None if unavailable else today,
            "week": None if unavailable else week,
            "total": None if unavailable else total,
            "asOf": context.as_of.isoformat(),
            "requestSnapshotAt": context.request_snapshot_at.isoformat(),
            "partialSources": partial_sources,
            "sourceHealth": source_health,
        }

    def list_todos(
        self,
        context: HrRequestContext,
        filters: Optional[dict] = None,
        page: int = 1,
        page_size: int = 20,
        user=None,
    ) -> dict:
        """聚合各 provider 的待办列表（DB 分页，禁止前端分页）。"""
        filters = filters or {}
        all_items: List[TodoItem] = []
        total = 0
        partial_sources = []

        source_health = []
        visible_sources = 0
        successful_sources = 0
        fetch_size = page * page_size
        for provider in self.providers:
            if not self._allowed(provider, user):
                source_health.append({"source": provider.provider_key, "status": "FILTERED"})
                continue
            visible_sources += 1
            try:
                result = provider.list_todos(context, filters, page=1, page_size=fetch_size)
                if not result.get("available", True):
                    partial_sources.append(provider.provider_key)
                    source_health.append({"source": provider.provider_key, "status": "UNAVAILABLE"})
                    continue
                successful_sources += 1
                total += result.get("total", 0)
                for raw in result.get("items", []):
                    item = TodoItem(**{k: v for k, v in raw.items() if k in TodoItem.__dataclass_fields__})
                    all_items.append(item)
                source_health.append({"source": provider.provider_key, "status": "OK"})
            except Exception as exc:
                partial_sources.append(provider.provider_key)
                source_health.append(self._source_failure(provider, exc))

        # 排序：CRITICAL > 逾期 > dueAt > submittedAt（总册 10.5）
        def sortable_timestamp(value):
            if value is None:
                return float("inf")
            if value.tzinfo is None:
                value = value.replace(tzinfo=context.tzinfo())
            return value.timestamp()

        def sort_key(item: TodoItem):
            severity_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
            return (
                severity_rank.get(item.severity, 4),
                0 if item.is_overdue else 1,
                sortable_timestamp(item.due_at),
                sortable_timestamp(item.submitted_at),
            )

        all_items.sort(key=sort_key)

        # 简单分页（聚合后）
        start = (page - 1) * page_size
        page_items = all_items[start : start + page_size]

        return {
            "status": (
                "UNAVAILABLE"
                if visible_sources > 0 and successful_sources == 0
                else ("PARTIAL" if partial_sources else "OK")
            ),
            "items": [item.__dict__ for item in page_items],
            "pagination": {
                "page": page,
                "pageSize": page_size,
                "total": total,
            },
            "asOf": context.as_of.isoformat(),
            "requestSnapshotAt": context.request_snapshot_at.isoformat(),
            "partialSources": partial_sources,
            "sourceHealth": source_health,
        }
