"""
hr_assessment/permissions.py —— 权限与 Data Scope 框架（生产级）。

遵循 hr_staff 模式：自定义装饰器 + 权限枚举 + SoD 检查。
"""

from __future__ import annotations

from enum import Enum
from functools import wraps
from typing import Any, Callable, Optional

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, JsonResponse

from hr_assessment.api.response import api_error
from hr_assessment.constants import DataScope
from hr_assessment.context import (
    HrAssessmentContextError,
    resolve_authenticated_staff_id,
)


class Scope(str, Enum):
    SELF = "SELF"
    ASSIGNED_CASES = "ASSIGNED_CASES"
    DIRECT_REPORTS = "DIRECT_REPORTS"
    ORG = "ORG"
    ORG_DESCENDANTS = "ORG_DESCENDANTS"
    COLLEGE = "COLLEGE"
    SCHOOL = "SCHOOL"


ASSESSMENT_PERMISSIONS = [
    ("hr.assessment.policy.admin", "考核政策管理"),
    ("hr.assessment.cycle.admin", "考核周期管理"),
    ("hr.assessment.hr_reviewer", "校级人事评审"),
    ("hr.assessment.college_reviewer", "学院评审"),
    ("hr.assessment.manager_reviewer", "主管评审"),
    ("hr.assessment.panel_member", "评审委员会成员"),
    ("hr.assessment.calibration_manager", "校准管理"),
    ("hr.assessment.final_decider", "审定决策"),
    ("hr.assessment.result.correct", "追加更正或撤销已封板考核结果"),
    ("hr.assessment.ethics_reviewer", "师德评审"),
    ("hr.assessment.special_reviewer", "专项评审"),
    ("hr.assessment.archive_manager", "档案管理"),
    ("hr.assessment.auditor", "审计"),
    ("hr.assessment.employee_self", "本人自助"),
    ("hr.assessment.analytics_view", "统计分析"),
]

SOD_CONFLICT_PAIRS = [
    ("hr.assessment.policy.admin", "hr.assessment.final_decider"),
    ("hr.assessment.calibration_manager", "hr.assessment.hr_reviewer"),
    ("hr.assessment.auditor", "hr.assessment.final_decider"),
]

PERMISSION_SCOPE = {
    "hr.assessment.policy.admin": Scope.SCHOOL,
    "hr.assessment.cycle.admin": Scope.SCHOOL,
    "hr.assessment.hr_reviewer": Scope.SCHOOL,
    "hr.assessment.college_reviewer": Scope.COLLEGE,
    "hr.assessment.manager_reviewer": Scope.DIRECT_REPORTS,
    "hr.assessment.panel_member": Scope.ASSIGNED_CASES,
    "hr.assessment.calibration_manager": Scope.COLLEGE,
    "hr.assessment.final_decider": Scope.COLLEGE,
    "hr.assessment.result.correct": Scope.SCHOOL,
    "hr.assessment.ethics_reviewer": Scope.ASSIGNED_CASES,
    "hr.assessment.special_reviewer": Scope.ASSIGNED_CASES,
    "hr.assessment.archive_manager": Scope.SCHOOL,
    "hr.assessment.auditor": Scope.SCHOOL,
    "hr.assessment.employee_self": Scope.SELF,
    "hr.assessment.analytics_view": Scope.SCHOOL,
}


def require_assessment_permission(
    perm_code: str | tuple[str, ...],
    sensitive: bool = False,
    staff_mapping_required: bool = False,
) -> Callable:
    """视图装饰器 — 校验权限 + 租户上下文。

    模拟 hr_staff 的 @require_hr_staff_permission() 模式。
    """
    def decorator(view_func: Callable) -> Callable:
        @wraps(view_func)
        def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> JsonResponse:
            permission_codes = (
                (perm_code,) if isinstance(perm_code, str) else tuple(perm_code)
            )
            if not request.user.is_authenticated:
                raise PermissionDenied("未登录")
            if not request.user.is_superuser and not any(
                request.user.has_perm(code) for code in permission_codes
            ):
                raise PermissionDenied(
                    "缺少权限: " + " / ".join(permission_codes)
                )
            tenant_id = getattr(request, "tenant_id", None)
            if not tenant_id:
                return JsonResponse(
                    api_error("TENANT_CONTEXT_REQUIRED", "请选择当前学校", http_status=403),
                    status=403,
                )
            if not request.user.is_superuser:
                from base.auth_backends import get_allowed_company_ids

                if int(tenant_id) not in (get_allowed_company_ids(request.user) or ()):
                    return JsonResponse(
                        api_error(
                            "TENANT_CONTEXT_REQUIRED",
                            "当前账号无权访问该学校数据",
                            http_status=403,
                        ),
                        status=403,
                    )
            non_self_permission_codes = tuple(
                code
                for code in permission_codes
                if code != "hr.assessment.employee_self"
            )
            self_mapping_required = (
                "hr.assessment.employee_self" in permission_codes
                and (
                    len(permission_codes) == 1
                    or (
                        not request.user.is_superuser
                        and not any(
                            request.user.has_perm(code)
                            for code in non_self_permission_codes
                        )
                    )
                )
            )
            try:
                request.staff_id = resolve_authenticated_staff_id(
                    request,
                    int(tenant_id),
                    required=staff_mapping_required or self_mapping_required,
                )
            except HrAssessmentContextError as exc:
                return JsonResponse(
                    api_error(exc.code, exc.message, http_status=exc.status),
                    status=exc.status,
                )
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def check_sod_conflict(user_perm_codes: list[str]) -> list[tuple[str, str]]:
    conflicts = []
    for a, b in SOD_CONFLICT_PAIRS:
        if a in user_perm_codes and b in user_perm_codes:
            conflicts.append((a, b))
    return conflicts


def resolve_scope(user_perm_codes: list[str]) -> Scope:
    resolved = Scope.SELF
    order = [
        Scope.SELF, Scope.ASSIGNED_CASES, Scope.DIRECT_REPORTS,
        Scope.ORG, Scope.ORG_DESCENDANTS, Scope.COLLEGE, Scope.SCHOOL,
    ]
    for code in user_perm_codes:
        scope = PERMISSION_SCOPE.get(code)
        if scope and order.index(scope) > order.index(resolved):
            resolved = scope
    return resolved
