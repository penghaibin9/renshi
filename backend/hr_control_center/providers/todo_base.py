"""
hr_control_center/providers/todo_base.py

HrTodoProvider 协议（总册 10.2）：
- 各业务域决定：谁是待办人、状态是否合法、能做什么动作。
- HR01 只聚合，不复制业务状态机。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class TodoItem:
    """TodoItem 标准合同（总册 10.3）。"""

    provider: str
    business_type: str
    business_id: str
    title: str
    subject_name: str = ""
    org_name: str = ""
    current_stage: str = ""
    severity: str = "MEDIUM"  # CRITICAL / HIGH / MEDIUM / LOW
    submitted_at: Optional[datetime] = None
    due_at: Optional[datetime] = None
    is_overdue: bool = False
    assignee_type: str = ""
    action_label: str = ""
    action_url: str = ""
    permission_code: str = ""
    version: str = "1"
    batch_action_supported: bool = False


@dataclass
class TodoSummary:
    overdue: int = 0
    today: int = 0
    week: int = 0
    total: int = 0


class HrTodoProvider:
    """
    Provider 基类。子类实现 get_summary / list_todos。
    HR01 不直接查业务表；通过 provider 聚合。
    """

    provider_key = "base"
    required_permission = ""

    def get_summary(self, context) -> TodoSummary:
        raise NotImplementedError

    def list_todos(self, context, filters=None, page=1, page_size=20):
        raise NotImplementedError


class TodoProviderUnavailable(Exception):
    """A provider could not produce a trustworthy current result."""

    def __init__(self, provider_key: str, reason_code: str, message: str = ""):
        self.provider_key = provider_key
        self.reason_code = reason_code
        self.message = message
        super().__init__(message or reason_code)
