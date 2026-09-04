"""
hr_control_center/services/quick_action_service.py

QuickActionService —— HR01-05 快捷办理（总册 13 节）。

核心合同：
- 前端只消费服务端计算后的 Action Catalog，禁止前端自行 hide/授权。
- 无权限或 data scope 不允许 → 直接不返回该 action（避免点击后才 403）。
- disabled 时必须有明确 reasonCode。
- 不返回全量 registry 让前端自行鉴权。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from django.urls import reverse

from hr_control_center.context import HrRequestContext


@dataclass(frozen=True)
class QuickAction:
    key: str
    label: str
    description: str
    required_permissions: tuple = ()
    route_url: str = "#"
    icon: str = ""
    priority: int = 100
    audiences: tuple = ()
    allowed_scope_types: tuple = ("SCHOOL", "COLLEGE", "DEPARTMENT")
    required_module: Optional[str] = None
    feature_flag: Optional[str] = None


# 快捷动作（总册 13.2），只指向 HR01~HR18 正式工作区。
QUICK_ACTIONS: List[QuickAction] = [
    QuickAction(
        key="staff.create",
        label="新增教职工",
        description="录入新教职工的基本信息与任职关系",
        required_permissions=("employee.add_employee",),
        route_url="/hr/staff/",
        icon="user-plus",
        priority=10,
        audiences=("HR_ADMIN", "COLLEGE_HR_SECRETARY"),
        allowed_scope_types=("SCHOOL", "COLLEGE"),
    ),
    QuickAction(
        key="staff.export_roster",
        label="导出教职工名册",
        description="导出当前范围在岗教职工名册",
        required_permissions=("employee.view_employee", "hr.dashboard.export"),
        route_url="/hr/staff/",
        icon="download",
        priority=20,
        audiences=("HR_ADMIN", "HR_OFFICE_HEAD"),
        allowed_scope_types=("SCHOOL",),
    ),
    QuickAction(
        key="recruitment.create",
        label="创建招聘项目",
        description="发起一个新的招聘项目",
        required_permissions=("recruitment.add_recruitment",),
        route_url="/hr/recruitment/campaigns",
        icon="briefcase",
        priority=30,
        audiences=("HR_ADMIN",),
        required_module="recruitment",
        allowed_scope_types=("SCHOOL",),
    ),
    QuickAction(
        key="onboarding.create",
        label="办理入职",
        description="为新入职教职工办理入职流程",
        required_permissions=("onboarding.add_onboarding",),
        route_url="/hr/onboarding/prehires",
        icon="user-check",
        priority=40,
        audiences=("HR_ADMIN", "COLLEGE_HR_SECRETARY"),
        required_module="onboarding",
        allowed_scope_types=("SCHOOL", "COLLEGE"),
    ),
    QuickAction(
        key="contract.renew",
        label="合同续签",
        description="处理即将到期的合同续签",
        required_permissions=("payroll.change_contract",),
        route_url="/hr/contracts/",
        icon="file-signature",
        priority=50,
        audiences=("HR_ADMIN",),
        required_module="payroll",
        allowed_scope_types=("SCHOOL",),
    ),
    QuickAction(
        key="leave.create",
        label="创建请假申请",
        description="教职工请假申请入口",
        required_permissions=("leave.add_leaverequest",),
        route_url="/hr/time/leave/",
        icon="calendar-minus",
        priority=60,
        audiences=("ALL",),
        required_module="leave",
        allowed_scope_types=("SCHOOL", "COLLEGE", "DEPARTMENT"),
    ),
]


class QuickActionService:
    def get_catalog(self, context: HrRequestContext, user) -> List[dict]:
        """
        服务端过滤（总册 13.5）：
        tenant + permission + data scope + module + feature flag + business availability。
        返回已计算好的 Action Catalog，前端不授权。
        """
        result = []
        for action in QUICK_ACTIONS:
            entry = self._evaluate(action, context, user)
            if entry is not None:
                result.append(entry)
        result.sort(key=lambda a: a["priority"])
        return result

    def _evaluate(self, action: QuickAction, context: HrRequestContext, user) -> Optional[dict]:
        # 1. 权限
        if not user.is_superuser:
            if not all(user.has_perm(p) for p in action.required_permissions):
                return None  # 无权限 → 不返回

        # 2. module enabled
        if action.required_module:
            from django.apps import apps

            if not apps.is_installed(action.required_module):
                return None  # 模块未启用 → 不返回

        # 3. data scope 类型
        if context.scope.scope_type not in action.allowed_scope_types:
            return None  # scope 不允许 → 不返回

        # 4. 返回已授权的 action
        return {
            "key": action.key,
            "label": action.label,
            "description": action.description,
            "icon": action.icon,
            "url": action.route_url,
            "priority": action.priority,
            "audiences": list(action.audiences),
            "state": "ENABLED",
        }
